"""Motor de trading: orquesta datos, estrategia, riesgo, ejecución y estado.

El motor no conoce FastAPI ni React. Expone un snapshot JSON y una API de
control; la interfaz es un consumidor más.
"""

from __future__ import annotations

import asyncio
import os
import time
import traceback
from collections import deque
from dataclasses import asdict
from typing import Any

from .config import Settings, apply_settings, save_settings
from .db import Store
from .execution import ExecutionEngine
from .experiments import ExperimentError, assert_parity, identity_from_feed
from .market.feed import MarketFeed, build_feed
from .models import Bar
from .risk import RiskManager
from .stats import compute_stats
from .strategy.strategy import PHASE_ORDER, Assess, ORBStrategy
from .timeutil import et_date, et_date_str, et_hm, et_minutes, hm_to_minutes, local_dt

RECENT_TRADE_LIMIT = 200
CHART_HISTORY_LIMIT = 6000


class TradingEngine:
    def __init__(self, store: Store, settings: Settings) -> None:
        self.store = store
        self.settings = settings
        self.events: deque[dict] = deque(maxlen=400)
        self._subs: set[asyncio.Queue] = set()
        self.risk = RiskManager(settings)
        self.strategy = ORBStrategy(settings)
        self.execution = ExecutionEngine(settings, self._emit, mode="paper")
        self.status = "stopped"
        self._task: asyncio.Task | None = None
        self.feed: MarketFeed | None = None
        self.feed_error: str | None = None
        self._build_feed()

        self.nq: list[Bar] = []
        self.mnq: list[Bar] = []
        self.es: list[Bar] = []
        # Velas MNQ de sesiones anteriores. Se conservan para que el gráfico
        # pueda mostrar el historial y no solo la sesión en curso.
        self.chart_history: deque[dict] = deque(maxlen=CHART_HISTORY_LIMIT)
        self.session_date: str | None = None
        self.assess = Assess()
        self.last_tick_ts: int | None = None
        self._last_received_wall = 0.0
        self._rejected: set[str] = set()
        self._persisted: set[str] = set()
        # Señales ya operadas, persistidas en SQLite. El id de señal de la
        # estrategia es determinista (fecha-dirección-ruptura), así que un replay
        # reiniciado desde el inicio de la sesión vuelve a emitir los mismos ids.
        self._traded_signals: set[str] = set()
        # Contadores del día guardados para reanudar un replay de la misma sesión.
        self._restored_day: dict[str, Any] | None = None
        self._entry_phases: list[dict] = []
        self._entry_signal_id: str | None = None
        # Línea de tiempo de la sesión. La estrategia reconstruye el estado en
        # cada vela y, al expirar el setup, retorna antes de recalcular la SMT:
        # sin esta memoria la tarjeta volvería a "esperando".
        self._phase_history: dict[str, dict] = {}
        self._session_smt: dict | None = None
        self._session_retest: dict | None = None
        self._session_markers: list[dict] = []
        self.equity = settings.risk.initial_capital
        self.day_start_equity = self.equity
        self.day_realized = 0.0
        self.trades_today = 0
        self.consecutive_losses = 0
        self._stats_cache: tuple[int, dict] = (0, {})
        self.started_at = int(time.time())
        self._restore()
        for ev in reversed(self.store.list_events(limit=60)):
            self.events.append(ev)

    # ------------------------------------------------------------------- setup
    def _build_feed(self) -> None:
        try:
            self.feed = build_feed(self.settings)
            self.feed_error = None
        except Exception as exc:  # noqa: BLE001
            self.feed = None
            self.feed_error = str(exc)

    def _restore(self) -> None:
        trades = self.store.all_closed_trades(self.execution.mode)
        self.equity = self.settings.risk.initial_capital + sum(float(t["pnl"]) for t in trades)
        state = self.store.get_kv("engine_state", {}) or {}
        today = et_date_str(int(time.time()))
        if state.get("session_date") == today:
            day_realized = float(state.get("day_realized", 0.0))
            trades_today = int(state.get("trades_today", 0))
            consecutive_losses = int(state.get("consecutive_losses", 0))
            day_start_equity = float(state.get("day_start_equity", self.equity))
            self._restored_day = {
                "date": today,
                "day_realized": day_realized,
                "trades_today": trades_today,
                "consecutive_losses": consecutive_losses,
                "day_start_equity": day_start_equity,
            }
            self.day_realized = day_realized
            self.trades_today = trades_today
            self.consecutive_losses = consecutive_losses
            self.day_start_equity = day_start_equity
        if state.get("emergency"):
            self.risk.trigger_emergency(state.get("emergency_reason", "Restaurada"), int(state.get("emergency_ts") or time.time()))
        self.execution.restore_position(state.get("position"))
        last_exit = state.get("last_exit_ts")
        try:
            self.execution.last_exit_ts = int(last_exit) if last_exit else None
        except (TypeError, ValueError):
            self.execution.last_exit_ts = None
        try:
            self._traded_signals = self.store.traded_signal_ids(self.execution.mode)
        except Exception as exc:  # noqa: BLE001
            self._traded_signals = set()
            self._emit("ERROR", "system", f"No se pudo cargar la deduplicación de señales: {exc}")
        if self.execution.position:
            self._emit(
                "WARNING",
                "system",
                "Posición restaurada tras reinicio; el motor seguirá gestionando SL/TP.",
                {"position_id": self.execution.position.id},
            )

    # ------------------------------------------------------------------ helpers
    @property
    def last_price(self) -> float:
        return self.mnq[-1].close if self.mnq else 0.0

    def _trade_window_open(self, ts: int) -> bool:
        minute = et_minutes(ts, self.settings.orb.timezone)
        return (
            hm_to_minutes(self.settings.risk.trade_window_start)
            <= minute
            <= hm_to_minutes(self.settings.risk.trade_window_end)
        )

    # ------------------------------------------------------------------ control
    async def start(self) -> tuple[bool, str]:
        if self.settings.mode == "live":
            ok, msg = self._live_ready()
            if not ok:
                return False, msg
        if self.feed is None:
            return False, self.feed_error or "Sin proveedor de datos disponible"
        if (
            getattr(self.feed, "quality", None) == "simulated"
            and os.environ.get("YED_ALLOW_SIMULATED", "").strip() != "1"
        ):
            return False, (
                "Ejecución bloqueada: el feed es sintético y no representa el mercado real. "
                "Configura un CSV histórico validado o exporta YED_ALLOW_SIMULATED=1 "
                "solo para una demo explícita."
            )
        if self.status == "running" and self._task and not self._task.done():
            return True, "Motor en marcha"
        try:
            identity = identity_from_feed(self.settings, self.feed)
            anchor = self.store.get_kv("experiment.parity")
            if anchor:
                # Paper debe operar exactamente la configuración y el código
                # del último backtest persistido. El dataset solo se exime en
                # un feed live, que por definición no es el histórico.
                assert_parity(
                    identity,
                    anchor,
                    compare_dataset=getattr(self.feed, "kind", None) != "live",
                    context="paper",
                )
            self.store.set_kv("experiment.paper", identity.as_dict())
        except ExperimentError as exc:
            self._emit("ERROR", "config", str(exc))
            return False, str(exc)
        self.status = "running"
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="yedbot-engine")
        self._emit("SUCCESS", "system", "Motor iniciado")
        return True, "Motor iniciado"

    def pause(self, reason: str = "Pausa manual desde la interfaz") -> tuple[bool, str]:
        if self.status != "running":
            return False, "El motor no está en marcha"
        self.status = "paused"
        self._emit("WARNING", "system", f"Motor pausado: {reason}")
        return True, "Motor pausado"

    def resume(self) -> tuple[bool, str]:
        if self.status != "paused":
            return False, "El motor no está pausado"
        # Un resume solo tiene sentido si el loop sigue vivo esperando en pausa.
        # Si la tarea terminó (feed agotado, cancelación externa...), poner
        # `running` dejaría un estado fantasma sin ningún replay detrás.
        if self._task is None or self._task.done():
            # Sin loop no hay una pausa real: el motor está detenido. Dejarlo
            # en `paused` mantendría un botón de reanudar que nunca funciona;
            # `stopped` hace que la UI ofrezca Iniciar.
            self.status = "stopped"
            self._task = None
            message = (
                "No hay una tarea de replay activa; el motor queda detenido. "
                "Usa Iniciar para arrancarlo de nuevo"
            )
            self._emit("WARNING", "system", f"No se puede reanudar: {message}")
            self._broadcast()
            return False, message
        self.status = "running"
        self._emit("INFO", "system", "Motor reanudado")
        return True, "Motor reanudado"

    async def stop(self) -> tuple[bool, str]:
        self.status = "stopped"
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._task = None
        self._emit("WARNING", "system", "Motor detenido")
        self._broadcast()
        return True, "Motor detenido"

    def _live_ready(self) -> tuple[bool, str]:
        live = self.settings.live
        if live.broker == "none":
            return False, "LIVE bloqueado: configura un broker (Tradovate, IBKR o Rithmic)."
        if not live.live_enabled:
            return False, "LIVE bloqueado: activa 'live_enabled' tras validar paper trading."
        if live.live_confirmation.strip().upper() != "HABILITAR LIVE":
            return False, "LIVE bloqueado: escribe 'HABILITAR LIVE' en la confirmación explícita."
        return False, (
            "LIVE no disponible: el adaptador del broker aún no está conectado a una cuenta real. "
            "Se requieren credenciales, permisos de datos CME y validación previa en paper."
        )

    # --------------------------------------------------------------------- loop
    async def _loop(self) -> None:
        while True:
            if self.status != "running":
                await asyncio.sleep(0.15)
                continue
            try:
                tick = await self.feed.next_tick() if self.feed else None
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self._emit("ERROR", "data", f"Error en el feed de datos: {exc}")
                await asyncio.sleep(3)
                continue
            if tick is None:
                self.status = "stopped"
                self._emit("WARNING", "data", "Fin de los datos disponibles; motor detenido")
                self._broadcast()
                return
            try:
                self._process(tick)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self._emit("ERROR", "engine", f"Error procesando vela: {exc}", {"trace": traceback.format_exc()[-1500:]})

    def _record_chart_bar(self, bar: Bar) -> None:
        """Añade una vela al historial, recortando si el replay rebobina."""
        while self.chart_history and self.chart_history[-1]["t"] >= bar.ts:
            self.chart_history.pop()
        self.chart_history.append(bar.as_dict())

    def _process(self, tick) -> None:
        nq_bar = tick.bars["NQ"]
        mnq_bar = tick.bars["MNQ"]
        es_bar = tick.bars["ES"]
        day = et_date(nq_bar.ts, self.settings.orb.timezone)
        if self.session_date != day.isoformat():
            self._new_session(day, mnq_bar)

        self.nq.append(nq_bar)
        self.mnq.append(mnq_bar)
        self.es.append(es_bar)
        self._record_chart_bar(mnq_bar)
        self.last_tick_ts = nq_bar.ts
        self._last_received_wall = time.time()

        self.execution.on_bar(mnq_bar)
        self._persist_new_trades()

        if self.status == "running":
            self._evaluate(nq_bar.ts)

        self._session_guard(mnq_bar)
        self._persist_state()
        self._broadcast()

    def _new_session(self, day, first_bar: Bar) -> None:
        if self.execution.position:
            entry_day = et_date(self.execution.position.entry_ts, self.settings.orb.timezone)
            # Un replay puede rebobinar a una sesión anterior a la entrada.
            # Solo se cierra la posición cuando el replay avanza de día.
            if entry_day < day:
                self.execution.close(self.last_price or first_bar.open, first_bar.ts, "session_close")
                self._persist_new_trades()
        self.session_date = day.isoformat()
        self.nq.clear()
        self.mnq.clear()
        self.es.clear()
        self.assess = Assess()
        self._reset_timeline()
        self._rejected.clear()
        self.execution.seen_signals.clear()
        restored = self._restored_day
        if restored and restored["date"] == self.session_date:
            self.day_realized = restored["day_realized"]
            self.trades_today = restored["trades_today"]
            self.consecutive_losses = restored["consecutive_losses"]
            self.day_start_equity = restored["day_start_equity"]
            self._restored_day = None
            self._emit("INFO", "session", f"Sesión {self.session_date} reanudada · contadores del día restaurados")
        else:
            self.day_realized = 0.0
            self.trades_today = 0
            self.consecutive_losses = 0
            self.day_start_equity = self.equity
            self._emit("INFO", "session", f"Sesión {self.session_date} iniciada · OR {self.settings.orb.start}–{self.settings.orb.end} ET")

    def _evaluate(self, bar_ts: int) -> None:
        now_ts = bar_ts + 60
        assess = self.strategy.evaluate(self.nq, self.es, self._trade_window_open(now_ts))
        self.assess = assess
        self._remember(assess)
        signal = assess.signal
        if signal is None:
            return
        if signal.id in self._traded_signals:
            # El replay repite la sesión desde el inicio tras un reinicio: la
            # señal ya se ejecutó y contabilizó, no debe volver a armarse.
            return
        if signal.id in self._rejected or signal.id in self.execution.seen_signals:
            return
        if self.execution.position or self.execution.pending_entry:
            return
        decision = self.risk.evaluate(
            signal,
            equity=self.equity,
            open_positions=1 if self.execution.position else 0,
            day_pnl=self.day_realized,
            day_start_equity=self.day_start_equity,
            trades_today=self.trades_today,
            now_ts=now_ts,
            last_exit_ts=self.execution.last_exit_ts,
            consecutive_losses=self.consecutive_losses,
            has_pending_entry=self.execution.pending_entry is not None,
        )
        if not decision.ok:
            self._rejected.add(signal.id)
            self._emit("WARNING", "risk", f"Señal descartada: {decision.reason}", {"signal_id": signal.id})
            return
        signal.qty = decision.qty
        signal.risk_amount = decision.risk_amount
        manifest = getattr(self.feed, "manifest", None) or {}
        active = (manifest.get("contracts_by_session") or {}).get(et_date_str(bar_ts), {})
        if active.get("MNQ"):
            signal.meta["contract"] = active["MNQ"]
            signal.meta["expiry"] = (manifest.get("expiry_by_session") or {}).get(
                et_date_str(bar_ts), {}
            ).get("MNQ")
        self._entry_phases = [dict(p) for p in assess.phases]
        self._entry_signal_id = signal.id
        self.execution.arm(signal)
        self._emit(
            "SUCCESS",
            "signal",
            f"Señal {signal.signal_type} {'LARGA' if signal.direction == 'long' else 'CORTA'} · "
            f"{decision.qty} contratos @ {signal.entry_price:.2f} · riesgo {decision.risk_amount:.2f} USD",
            {"signal_id": signal.id},
        )

    def _persist_new_trades(self) -> None:
        for trade in self.execution.closed_trades:
            if trade.id in self._persisted:
                continue
            self._persisted.add(trade.id)
            signal_id = str((trade.meta or {}).get("signal_id") or "")
            if signal_id and signal_id in self._traded_signals:
                # Red de seguridad: nunca insertar dos operaciones para la misma
                # señal ni sumar su P&L dos veces al capital.
                self._emit(
                    "WARNING",
                    "execution",
                    "Operación duplicada ignorada: la señal ya estaba registrada",
                    {"signal_id": signal_id, "trade_id": trade.id},
                )
                continue
            self.store.insert_trade(asdict(trade))
            if signal_id:
                self._traded_signals.add(signal_id)
            self.equity += trade.pnl
            self.day_realized += trade.pnl
            self.trades_today += 1
            self.consecutive_losses = self.consecutive_losses + 1 if trade.pnl < 0 else 0
            self.store.insert_equity(trade.exit_ts, round(self.equity, 2), trade.mode)
            self._stats_cache = (0, {})
            if self.execution.position is None:
                self._entry_phases = []
                self._entry_signal_id = None
            self._emit(
                "SUCCESS" if trade.pnl > 0 else "ERROR",
                "trade",
                f"Operación cerrada {trade.direction} {trade.qty} · P&L neto {trade.pnl:+.2f} USD "
                f"({trade.r_multiple:+.2f} R) · {trade.exit_reason}",
                {"trade_id": trade.id},
            )

    def _session_guard(self, bar: Bar) -> None:
        rcfg = self.settings.risk
        if not (rcfg.close_at_session_end and self.execution.position):
            return
        if et_hm(bar.ts, self.settings.orb.timezone) >= rcfg.session_close_time:
            self.execution.close(bar.close, bar.ts + 60, "session_close")
            self._persist_new_trades()

    # --------------------------------------------------------------- commands
    def close_position(self) -> tuple[bool, str]:
        if not self.execution.position:
            return False, "No hay posición abierta"
        trade = self.execution.close(self.last_price, int(time.time()), "manual")
        self._persist_new_trades()
        return (True, f"Posición cerrada a {self.last_price:.2f}") if trade else (False, "No se pudo cerrar")

    def cancel_orders(self) -> tuple[bool, str]:
        count = self.execution.cancel_all("Cancelación manual desde la interfaz")
        self._broadcast()
        return (True, f"{count} órdenes canceladas") if count else (True, "No había órdenes pendientes")

    def emergency(self, reason: str, close_positions: bool) -> tuple[bool, str]:
        self.risk.trigger_emergency(reason or "Intervención manual", int(time.time()))
        self.execution.cancel_all(f"Parada de emergencia: {reason}")
        if close_positions and self.execution.position:
            self.execution.close(self.last_price, int(time.time()), "emergency")
            self._persist_new_trades()
        self._emit("ERROR", "risk", f"PARADA DE EMERGENCIA: {reason}. Entradas bloqueadas.", {"close_positions": close_positions})
        self._persist_state()
        self._broadcast()
        return True, "Parada de emergencia activada"

    def clear_emergency(self) -> tuple[bool, str]:
        self.risk.clear_emergency()
        self._emit("WARNING", "risk", "Parada de emergencia desactivada manualmente")
        self._persist_state()
        self._broadcast()
        return True, "Emergencia desactivada"

    async def update_settings(self, patch: dict, force: bool = False) -> tuple[bool, str]:
        critical = {"strategy", "risk", "execution", "orb", "smt", "mode"}
        if self.execution.position and critical.intersection(patch.keys()) and not force:
            return False, (
                "Hay una posición abierta. Los cambios de estrategia/riesgo no se aplican "
                "a una operación en curso sin confirmación explícita."
            )
        try:
            new = apply_settings(self.settings, patch)
        except Exception as exc:  # noqa: BLE001
            return False, f"Configuración inválida: {exc}"
        if new.mode == "live":
            ok, msg = self._live_ready()
            if not ok:
                return False, msg
        feed_changed = (
            new.feed.provider != self.settings.feed.provider
            or new.feed.csv_path != self.settings.feed.csv_path
            or new.feed.start_date != self.settings.feed.start_date
        )
        candidate = None
        if feed_changed:
            try:
                candidate = build_feed(new)
            except Exception as exc:  # noqa: BLE001
                return False, f"Configuración no aplicada: {exc}"
        self.settings = new
        self.execution.settings = new
        self.risk.settings = new
        self.strategy = ORBStrategy(new)
        save_settings(new)
        if candidate is not None:
            was_running = self.status == "running"
            self.status = "paused"
            self.feed = candidate
            self.feed_error = None
            self.nq.clear()
            self.mnq.clear()
            self.es.clear()
            self.chart_history.clear()
            self.session_date = None
            self.last_tick_ts = None
            self._last_received_wall = 0.0
            self.assess = Assess()
            self._reset_timeline()
            if was_running:
                self.status = "running"
            self._emit("INFO", "config", f"Proveedor de datos: {self.feed.label}")
        self._emit("INFO", "config", "Configuración actualizada")
        self._broadcast()
        return True, "Configuración guardada"

    async def reset_settings(self) -> tuple[bool, str]:
        return await self.update_settings(Settings().model_dump(), force=True)

    async def reset_stats(self, delete_backtests: bool = False) -> tuple[bool, str]:
        """Borra operaciones, equidad y eventos; conserva backtests y configuración.

        Es una acción explícita del operador: detiene el motor si está activo
        y desactiva una parada de emergencia, pero nunca cierra una posición
        abierta. La equidad vuelve al capital inicial ya configurado, sin
        reescribir la configuración. Los backtests guardados solo se eliminan
        con ``delete_backtests=True``.
        """
        if self.execution.position:
            return False, (
                "Hay una posición abierta. Ciérrala antes de reiniciar las "
                "estadísticas."
            )
        emergency_was_active = self.risk.emergency
        if self.status in ("running", "paused"):
            await self.stop()
        self.execution.cancel_all("Reinicio de estadísticas")

        deleted = self.store.clear_history(delete_backtests=delete_backtests)
        self.execution.closed_trades.clear()
        self.execution.seen_signals.clear()
        self.execution.pending_entry = None
        self.execution.pending_orders.clear()
        self.execution.last_exit_ts = None
        self.execution.daily_realized = 0.0
        self.execution._day = None
        self.execution.ambiguous_bars.clear()
        self.execution.ambiguous_count = 0

        self._persisted.clear()
        self._traded_signals.clear()
        self._rejected.clear()
        self._stats_cache = (0, {})
        self._restored_day = None
        self._entry_phases = []
        self._entry_signal_id = None
        self.nq.clear()
        self.mnq.clear()
        self.es.clear()
        self.chart_history.clear()
        self.session_date = None
        self.last_tick_ts = None
        self._last_received_wall = 0.0
        self.assess = Assess()
        self._reset_timeline()
        # Un reinicio de estadísticas también rebobina el replay. Si se dejara
        # el feed en su índice actual, al pulsar Iniciar el gráfico continuaría
        # por la sesión donde quedó en vez de empezar por la primera del CSV.
        try:
            if self.feed is None:
                self.feed = build_feed(self.settings)
            else:
                self.feed.rewind()
            self.feed_error = None
        except Exception as exc:  # noqa: BLE001
            self.feed_error = f"No se pudo rebobinar el feed: {exc}"
        initial_capital = self.settings.risk.initial_capital
        self.equity = initial_capital
        self.day_start_equity = initial_capital
        self.day_realized = 0.0
        self.trades_today = 0
        self.consecutive_losses = 0
        self.risk.clear_emergency()
        self.events.clear()
        capital_label = f"{initial_capital:,.0f}".replace(",", ".")
        message = (
            f"Estadísticas reiniciadas · {deleted['trades']} operaciones eliminadas · "
            f"equidad inicial {capital_label} USD"
        )
        if delete_backtests:
            message += f" · backtests eliminados: {deleted.get('backtests', 0)}"
        if deleted.get("vacuum_error"):
            message += " · la compactación de SQLite quedó pendiente; los datos ya se borraron"
        if emergency_was_active:
            message += " · parada de emergencia desactivada"
        self._persist_state()
        self._emit("INFO", "system", message)
        self._broadcast()
        return True, message

    # ------------------------------------------------------------------ events
    def _emit(self, level: str, category: str, message: str, meta: dict | None = None) -> None:
        try:
            event = self.store.insert_event(level, category, message, meta)
        except Exception:  # noqa: BLE001
            event = {"id": int(time.time() * 1000), "ts": int(time.time() * 1000), "level": level, "category": category, "message": message, "meta": meta or {}}
        self.events.append(event)
        if hasattr(self, "_subs"):
            payload = {"type": "event", "data": event}
            for q in list(self._subs):
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    pass

    def _persist_state(self) -> None:
        state = {
            "session_date": self.session_date,
            "day_realized": round(self.day_realized, 2),
            "trades_today": self.trades_today,
            "consecutive_losses": self.consecutive_losses,
            "day_start_equity": round(self.day_start_equity, 2),
            "equity": round(self.equity, 2),
            "last_exit_ts": self.execution.last_exit_ts,
            "position": self.execution.position_dict(),
            "status": self.status,
            "emergency": self.risk.emergency,
            "emergency_reason": self.risk.emergency_reason,
            "emergency_ts": self.risk.emergency_ts,
        }
        try:
            self.store.set_kv("engine_state", state)
        except Exception:  # noqa: BLE001
            pass

    # ----------------------------------------------------------------- pub/sub
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=8)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def _broadcast(self) -> None:
        if not self._subs:
            return
        payload = {"type": "snapshot", "data": self.snapshot()}
        for q in list(self._subs):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                # Se descarta el snapshot viejo para no bloquear el motor.
                try:
                    q.get_nowait()
                    q.put_nowait(payload)
                except Exception:  # noqa: BLE001
                    pass

    # --------------------------------------------------------------- timeline
    def _reset_timeline(self) -> None:
        """Olvida los hitos al cambiar de sesión o de proveedor de datos."""
        self._phase_history = {}
        self._session_smt = None
        self._session_retest = None
        self._session_markers = []

    def _remember(self, assess: Assess) -> None:
        """Conserva lo que ya ocurrió en la sesión.

        ``ORBStrategy.evaluate`` parte de cero en cada vela. Cuando el setup
        expira, retorna antes de la fase SMT y las tarjetas retroceden a
        "esperando". Aquí se conservan los hitos: una fase confirmada no se
        degrada a pendiente y la SMT confirmada no se pierde cuando la
        divergencia deja de ser reciente.
        """
        if assess.smt:
            self._session_smt = assess.smt
        if assess.retest:
            self._session_retest = assess.retest
        self._remember_markers(assess.markers)
        for phase in assess.phases:
            key = phase.get("key")
            if not key:
                continue
            status = phase.get("status")
            previous = self._phase_history.get(key)
            if previous is not None:
                previous_status = previous.get("status")
                # La SMT y la entrada, una vez confirmadas, son un hecho de la
                # sesión: no se reescriben como pendientes ni como caducadas.
                if (
                    key in ("smt", "entry")
                    and previous_status == "confirmed"
                    and status != "confirmed"
                ):
                    continue
                if status in ("pending", "waiting") and previous_status not in (
                    "pending",
                    "waiting",
                ):
                    continue
            self._phase_history[key] = dict(phase)

    def _remember_markers(self, markers: list[dict]) -> None:
        known = {
            (marker.get("type"), marker.get("ts"), marker.get("direction"))
            for marker in self._session_markers
        }
        for marker in markers:
            key = (marker.get("type"), marker.get("ts"), marker.get("direction"))
            if key in known:
                continue
            self._session_markers.append(dict(marker))
            known.add(key)

    def _timeline_phases(self) -> list[dict]:
        if not self._phase_history:
            return [dict(phase) for phase in self.assess.phases]
        phases = []
        for key, label in PHASE_ORDER:
            phase = self._phase_history.get(key)
            if phase is None:
                phase = {
                    "key": key,
                    "label": label,
                    "status": "waiting" if key == "management" else "pending",
                    "detail": "",
                    "ts": None,
                }
            phases.append(dict(phase))
        return phases

    def _phases_for_position(self, position: dict) -> list[dict]:
        """Fases del setup ejecutado, congeladas al entrar.

        Mientras hay posición no se muestra el estado recalculado del día (que ya
        habrá expirado): se muestra la secuencia que produjo la operación.
        """
        if self._entry_phases and self._entry_signal_id == position.get("signal_id"):
            phases = [dict(p) for p in self._entry_phases]
        else:
            meta = position.get("meta") or {}
            signal_type = position.get("signal_type") or "ORB"
            phases = _pending_phases()
            detail = {
                "session": f"Sesión del {et_date_str(position['entry_ts'])}",
                "opening_range": (
                    f"H {meta.get('orb_high')} · L {meta.get('orb_low')} · Mid {meta.get('orb_mid')}"
                    if meta.get("orb_high") is not None
                    else "Opening Range confirmado"
                ),
                "breakout": "Ruptura confirmada según la señal",
                "smt": "Confirmada" if "SMT" in signal_type else "Desactivada en la señal",
                "retest": "Confirmado" if "Retest" in signal_type else "Entrada directa",
                "entry": f"{position.get('direction')} {position.get('qty')} @ {position.get('entry_price')}",
                "management": "Posición abierta",
            }
            stamps = {
                "session": meta.get("breakout_ts"),
                "opening_range": meta.get("breakout_ts"),
                "breakout": meta.get("breakout_ts"),
                "smt": meta.get("retest_ts"),
                "retest": meta.get("retest_ts"),
                "entry": position.get("entry_ts"),
                "management": position.get("entry_ts"),
            }
            for phase in phases:
                phase["detail"] = detail.get(phase["key"], "")
                phase["ts"] = stamps.get(phase["key"])
                phase["status"] = "confirmed" if phase["key"] != "management" else "in_progress"
        for phase in phases:
            if phase["key"] == "management":
                phase.update(
                    status="in_progress",
                    detail=f"Posición abierta {position['qty']} contratos · P&L {position['unrealized']:+.2f} USD",
                    ts=position["entry_ts"],
                )
        return phases

    # ---------------------------------------------------------------- snapshot
    def quote(self, symbol: str) -> dict:
        bars = {"MNQ": self.mnq, "NQ": self.nq, "ES": self.es}[symbol]
        if not bars:
            return {
                "symbol": symbol,
                "last": 0.0,
                "change": 0.0,
                "change_pct": 0.0,
                "ts": None,
                "volume": 0,
            }
        first = bars[0].open
        last_bar = bars[-1]
        last = last_bar.close
        return {
            "symbol": symbol,
            "last": round(last, 2),
            "change": round(last - first, 2),
            "change_pct": round((last - first) / first * 100, 3) if first else 0.0,
            "ts": last_bar.ts,
            "volume": round(sum(b.volume for b in bars)),
        }

    def stats(self) -> dict:
        trades = self.store.all_closed_trades()
        cached_count, cached = self._stats_cache
        if cached_count != len(trades) or not cached:
            cached = compute_stats(trades, self.settings.risk.initial_capital)
            self._stats_cache = (len(trades), cached)
        return cached

    def _blocked_reason(self) -> str | None:
        if self.risk.emergency:
            return f"Parada de emergencia: {self.risk.emergency_reason}"
        if self.status == "paused":
            return "Motor pausado"
        if self.status == "stopped":
            return "Motor detenido"
        if self.trades_today >= self.settings.risk.max_trades_per_day:
            return "Máximo de operaciones diarias alcanzado"
        loss_limit = -self.day_start_equity * self.settings.risk.max_daily_loss_pct / 100
        if self.day_realized <= loss_limit:
            return "Límite de pérdida diaria alcanzado"
        if self.execution.position:
            return "Posición abierta; esperando gestión"
        return None

    def snapshot(self) -> dict[str, Any]:
        now_ms = int(time.time() * 1000)
        position = self.execution.position_dict(self.last_price) if self.execution.position else None
        unrealized = position["unrealized"] if position else 0.0
        equity_now = self.equity + unrealized
        open_drawdown = float(position.get("open_drawdown") or 0.0) if position else 0.0
        stats = self.stats()
        day_trades = [
            t for t in self.store.list_trades({"date_from": _day_start_ts(self.last_tick_ts)}, limit=500)
        ] if self.last_tick_ts else []
        day_stats = compute_stats(day_trades, self.settings.risk.initial_capital)
        feed = self.feed.describe() if self.feed else {
            "kind": "none",
            "label": "SIN CONEXIÓN",
            "quality": "offline",
            "connected": False,
            "detail": self.feed_error or "Sin proveedor de datos",
        }
        feed.update(
            {
                "last_bar_ts": self.last_tick_ts,
                "last_update_ms": int(self._last_received_wall * 1000) if self._last_received_wall else None,
                "stale": bool(self._last_received_wall and time.time() - self._last_received_wall > 20 and self.status == "running"),
                "delayed": False,
            }
        )
        phases = self._timeline_phases()
        if position:
            phases = self._phases_for_position(position)
        if not phases:
            # Motor detenido antes de procesar velas: se muestra el pipeline pendiente.
            phases = _pending_phases()
        markers = (
            list(self._session_markers)
            if self._session_markers
            else list(self.assess.markers)
        )
        for trade in day_trades[:12]:
            markers.append(
                {
                    "ts": trade["entry_ts"],
                    "price": trade["entry_price"],
                    "type": "trade_entry",
                    "direction": trade["direction"],
                    "label": f"Entrada {trade['direction']}",
                }
            )
            markers.append(
                {
                    "ts": trade["exit_ts"],
                    "price": trade["exit_price"],
                    "type": "trade_exit",
                    "direction": trade["direction"],
                    "label": f"Salida {'TP' if trade['pnl'] > 0 else 'SL'}",
                }
            )
        markers.sort(key=lambda m: m["ts"])
        risk_cfg = self.settings.risk
        session = {
            "date": self.session_date,
            "or_start": self.settings.orb.start,
            "or_end": self.settings.orb.end,
            "timezone": self.settings.orb.timezone,
            "trade_window_start": risk_cfg.trade_window_start,
            "trade_window_end": risk_cfg.trade_window_end,
            "close_time": risk_cfg.session_close_time,
        }
        return {
            "server_time": now_ms,
            "status": self.status,
            "mode": self.settings.mode,
            "instrument": self.settings.instrument,
            "reference_symbol": self.settings.reference_symbol,
            "comparison_symbol": self.settings.comparison_symbol,
            "data": feed,
            "session": session,
            "quotes": {s: self.quote(s) for s in ("MNQ", "NQ", "ES")},
            "opening_range": self.assess.opening_range,
            "assessment": {
                "phases": phases,
                "breakout": self.assess.breakout,
                "smt": self.assess.smt or self._session_smt,
                "retest": self.assess.retest or self._session_retest,
                "reject": None if position else self.assess.reject,
                "signal": self.assess.signal.as_dict() if self.assess.signal else None,
                "reference_level": self.assess.reference_level,
                "atr": self.assess.atr,
            },
            "position": position,
            "orders": self.execution.orders_snapshot(),
            "risk": {
                "equity": round(equity_now, 2),
                "day_start_equity": round(self.day_start_equity, 2),
                "daily_pnl": round(self.day_realized + unrealized, 2),
                "daily_pnl_pct": round((self.day_realized + unrealized) / self.day_start_equity * 100, 2) if self.day_start_equity else 0.0,
                "cum_pnl": round(equity_now - self.settings.risk.initial_capital, 2),
                "risk_per_trade_pct": risk_cfg.risk_per_trade_pct,
                "risk_open_pct": self.risk.open_risk_pct(self.execution.open_risk(), equity_now),
                "risk_open_amount": round(self.execution.open_risk(), 2),
                "trades_today": self.trades_today,
                "max_trades_per_day": risk_cfg.max_trades_per_day,
                "daily_loss_limit": round(self.risk.daily_loss_limit(), 2),
                "daily_profit_limit": self.risk.daily_profit_limit(),
                "max_daily_loss_pct": risk_cfg.max_daily_loss_pct,
                "max_drawdown_pct": stats.get("max_drawdown_pct", 0.0),
                "open_drawdown": round(open_drawdown, 2),
                "open_drawdown_pct": round(open_drawdown / equity_now * 100, 2) if equity_now else 0.0,
                "max_open_drawdown": stats.get("max_open_drawdown", 0.0),
                "emergency": self.risk.emergency,
                "emergency_reason": self.risk.emergency_reason or None,
                "blocked_reason": self._blocked_reason(),
                "initial_capital": self.settings.risk.initial_capital,
            },
            "stats": stats,
            "day_stats": day_stats,
            "recent_trades": self.store.list_trades(limit=6),
            "ambiguous_bars": {
                "count": self.execution.ambiguous_count,
                "recent": self.execution.ambiguous_bars[-10:],
            },
            "events": self.store.list_events(limit=40),
            "chart": {
                "bars": [b.as_dict() for b in self.mnq],
                "nq": [{"t": b.ts, "c": round(b.close, 2)} for b in self.nq],
                "es": [{"t": b.ts, "c": round(b.close, 2)} for b in self.es],
                "markers": markers,
                "smt": self.assess.smt or self._session_smt,
            },
            "config": {
                "confirm_tf": self.settings.strategy.confirm_tf,
                "entry_reference": self.settings.strategy.entry_reference,
                "use_smt": self.settings.strategy.use_smt,
                "sl_mode": self.settings.strategy.sl_mode,
                "tp_rr": self.settings.strategy.tp_rr,
                "risk_per_trade_pct": risk_cfg.risk_per_trade_pct,
                "daily_loss_limit": round(self.risk.daily_loss_limit(), 2),
                "max_trades_per_day": risk_cfg.max_trades_per_day,
                "tick_size": self.settings.execution.tick_size,
                "tick_value": self.settings.execution.tick_value,
                "point_value": self.settings.execution.point_value,
                "provider": self.settings.feed.provider,
                "replay_speed": self.settings.feed.replay_speed,
                "broker": self.settings.live.broker,
                "live_enabled": self.settings.live.live_enabled,
            },
            "settings": self.settings.model_dump(),
        }


def _pending_phases() -> list[dict]:
    return [
        {
            "key": key,
            "label": label,
            "status": "waiting" if key == "management" else "pending",
            "detail": "Esperando datos de mercado",
            "ts": None,
        }
        for key, label in PHASE_ORDER
    ]


def _day_start_ts(ts: int | None) -> int:
    if not ts:
        return 0
    d = local_dt(ts)
    return int(d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
