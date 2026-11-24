"""Motor de ejecución (paper). Órdenes, posiciones, SL/TP y persistencia.

La interfaz del ejecutor es deliberadamente estrecha (``arm``, ``on_bar``,
``close``, ``cancel_all``) para que un adaptador de broker real (Tradovate,
IBKR, Rithmic) pueda sustituirlo sin tocar estrategia ni UI.
"""

from __future__ import annotations

import time
import uuid
from typing import Callable

from .config import Settings
from .models import Order, Position, Signal, TradeRecord
from .timeutil import et_minutes, hm_to_minutes


def pos_label(direction: str) -> str:
    return "larga" if direction == "long" else "corta"


class ExecutionEngine:
    def __init__(
        self,
        settings: Settings,
        emit: Callable[[str, str, str, dict | None], None] | None = None,
        mode: str = "paper",
    ) -> None:
        self.settings = settings
        self.emit = emit or (lambda *a, **k: None)
        self.mode = mode
        self.position: Position | None = None
        self.pending_entry: Signal | None = None
        self.pending_orders: list[Order] = []
        self.closed_trades: list[TradeRecord] = []
        self.last_exit_ts: int | None = None
        self.daily_realized = 0.0
        self._day: str | None = None
        self.seen_signals: set[str] = set()
        self.ambiguous_bars: list[dict] = []
        self.ambiguous_count = 0

    # ------------------------------------------------------------------ helpers
    @property
    def tick(self) -> float:
        return self.settings.execution.tick_size

    def _slip(self) -> float:
        """Slippage adverso efectivo, acotado por ``max_slippage_ticks``."""
        ecfg = self.settings.execution
        return min(ecfg.slippage_ticks, ecfg.max_slippage_ticks) * self.tick

    def ambiguous_report(self) -> dict:
        """Informe auditable de velas donde se tocaron SL y TP a la vez."""
        return {"count": self.ambiguous_count, "items": list(self.ambiguous_bars)}

    def open_risk(self) -> float:
        return self.position.risk_amount if self.position else 0.0

    # -------------------------------------------------------------------- entry
    def arm(self, signal: Signal) -> None:
        if self.position or self.pending_entry:
            return
        self.pending_entry = signal
        order = Order.new(
            symbol=self.settings.instrument,
            side="buy" if signal.direction == "long" else "sell",
            qty=signal.qty,
            order_type="market",
            limit_price=None,
            role="entry",
            created_ts=int(time.time()),
        )
        self.pending_orders.append(order)
        self.emit("INFO", "order", f"Orden de entrada enviada ({signal.direction}, {signal.qty} contratos)", {"signal_id": signal.id})

    def cancel_all(self, reason: str = "Cancelación manual") -> int:
        count = len(self.pending_orders)
        for order in self.pending_orders:
            order.status = "cancelled"
            order.reason = reason
        self.pending_orders = []
        self.pending_entry = None
        if count:
            self.emit("WARNING", "order", f"{count} órden(es) pendientes canceladas: {reason}")
        return count

    def _entry_excluded(self, ts: int) -> bool:
        """Misma ventana semiabierta [inicio, fin) que usa ``RiskManager``."""
        rcfg = self.settings.risk
        if not (rcfg.entry_exclusion_start and rcfg.entry_exclusion_end):
            return False
        minute = et_minutes(ts, self.settings.orb.timezone)
        return (
            hm_to_minutes(rcfg.entry_exclusion_start)
            <= minute
            < hm_to_minutes(rcfg.entry_exclusion_end)
        )

    def _cancel_pending_entry(self, reason: str) -> bool:
        """Cancela una entrada aún no ejecutada y evita que se rearme."""
        signal = self.pending_entry
        if signal is None:
            return False
        self.pending_entry = None
        for order in self.pending_orders:
            if order.role == "entry" and order.status == "pending":
                order.status = "cancelled"
                order.reason = reason
        self.pending_orders = [
            order for order in self.pending_orders if order.status == "pending"
        ]
        self.seen_signals.add(signal.id)
        self.emit(
            "WARNING",
            "order",
            f"Entrada pendiente cancelada: {reason}",
            {"signal_id": signal.id},
        )
        return True

    def on_bar(self, bar) -> None:
        """Procesa una vela de 1m: fills de entrada y gestión de SL/TP."""
        # Una orden armada antes de la exclusión no puede llenarse dentro de
        # la ventana: se cancela antes del fill. La posición ya abierta no se
        # toca y sigue gestionándose por SL/TP/sesión.
        if self.pending_entry is not None and self._entry_excluded(bar.ts):
            # El remanente de un fill parcial es la segunda tranche de una
            # entrada ya aprobada y abierta, no una entrada nueva: completa la
            # posición hasta el tamaño planificado. Si la posición ya cerró, el
            # remanente abriría una posición nueva dentro de la ventana y se
            # cancela como cualquier otra entrada pendiente.
            completes_open_position = (
                self.pending_entry.meta.get("partial") and self.position is not None
            )
            if not completes_open_position:
                self._cancel_pending_entry(
                    "entrada pendiente al entrar en la ventana de exclusión"
                )
        if self.pending_entry is not None and bar.ts >= self.pending_entry.ts:
            self._fill_entry(bar)
        if self.position is not None:
            self._manage_position(bar)

    def _fill_entry(self, bar) -> None:
        sig = self.pending_entry
        assert sig is not None
        slip = self._slip()
        base = bar.open if self.settings.execution.fill_model == "next_open" else sig.entry_price
        price = base + slip if sig.direction == "long" else base - slip
        price = round(price / self.tick) * self.tick

        qty = sig.qty
        # El ratio modela el fill inicial, no cada tranche: el remanente se
        # llena entero para que la posición alcance el tamaño planificado.
        partial = (
            self.settings.execution.simulate_partial_fills
            and qty >= 2
            and not sig.meta.get("partial")
        )
        filled_qty = max(1, int(qty * self.settings.execution.partial_fill_ratio)) if partial else qty

        stop_ticks = abs(price - sig.stop) / self.tick
        # ``risk_amount`` de la posición es el riesgo efectivo al fill. El
        # planificado se conserva en ``meta`` para poder comparar ambos.
        risk_amount = round(filled_qty * stop_ticks * self.settings.execution.tick_value, 2)

        # Relleno parcial de una entrada ya abierta: se amplía la posición
        # existente en lugar de crear una segunda (evita duplicar riesgo).
        if self.position is not None and sig.meta.get("partial"):
            pos = self.position
            total = pos.qty + filled_qty
            pos.entry_price = round((pos.entry_price * pos.qty + price * filled_qty) / total, 2)
            pos.qty = total
            pos.risk_amount = round(
                abs(pos.entry_price - pos.initial_stop) / self.tick * self.settings.execution.tick_value * total, 2
            )
            self.pending_entry = None
            self.pending_orders = [o for o in self.pending_orders if o.status == "pending"]
            self.emit("INFO", "execution", f"Relleno parcial completado: +{filled_qty} contratos @ {price:.2f}")
            return

        self.position = Position(
            id=uuid.uuid4().hex[:12],
            symbol=self.settings.instrument,
            direction=sig.direction,
            qty=filled_qty,
            entry_price=round(price, 2),
            entry_ts=bar.ts,
            stop=sig.stop,
            target=sig.target,
            initial_stop=sig.stop,
            risk_amount=risk_amount,
            signal_id=sig.id,
            signal_type=sig.signal_type,
            entry_reason=sig.entry_reason,
            mode=self.mode,
            meta={
                **sig.meta,
                "planned_qty": qty,
                "planned_risk_amount": sig.risk_amount,
                "signal_entry": sig.entry_price,
            },
        )
        for order in self.pending_orders:
            if order.role == "entry":
                order.status = "filled"
                order.filled_ts = bar.ts
                order.filled_price = round(price, 2)
        self.pending_orders = [o for o in self.pending_orders if o.status == "pending"]
        self.pending_entry = None
        self.seen_signals.add(sig.id)

        if partial and filled_qty < qty:
            remainder = qty - filled_qty
            self.pending_entry = Signal(
                id=f"{sig.id}-partial",
                ts=bar.ts + 60,
                direction=sig.direction,
                entry_price=sig.entry_price,
                stop=sig.stop,
                target=sig.target,
                qty=remainder,
                risk_amount=0.0,
                signal_type=sig.signal_type,
                entry_reason=sig.entry_reason,
                reference_level=sig.reference_level,
                breakout_level=sig.breakout_level,
                smt_bias=sig.smt_bias,
                meta={**sig.meta, "partial": True},
            )
            self.emit("WARNING", "execution", f"Ejecución parcial {filled_qty}/{qty} contratos @ {price:.2f}")

        self.emit(
            "SUCCESS",
            "execution",
            f"Entrada ejecutada {sig.direction} {filled_qty} @ {price:.2f} · SL {sig.stop:.2f} · TP {sig.target:.2f}",
            {"signal_id": sig.id},
        )

    def _manage_position(self, bar) -> None:
        pos = self.position
        assert pos is not None
        # Tras un reinicio con replay desde el inicio de sesión, no se evalúan
        # velas anteriores a la entrada real de la posición.
        if bar.ts < pos.entry_ts:
            return
        self._update_excursions(pos, bar)
        if pos.direction == "long":
            hit_stop = bar.low <= pos.stop
            hit_target = bar.high >= pos.target
            gap_stop = bar.open < pos.stop
            gap_target = bar.open > pos.target
        else:
            hit_stop = bar.high >= pos.stop
            hit_target = bar.low <= pos.target
            gap_stop = bar.open > pos.stop
            gap_target = bar.open < pos.target
        # Si ambos niveles se tocan en la misma vela se asume el peor caso: SL.
        # La ambigüedad queda registrada para auditoría; no se inventa un camino intrabar.
        if hit_stop and hit_target:
            record = self._ambiguous_record(pos, bar, gap_stop=gap_stop, gap_target=gap_target)
            pos.meta["ambiguous_bar"] = True
            pos.meta["gap_stop"] = gap_stop
            trade = self.close(self._stop_exit_price(pos, bar, gap_stop), bar.ts, "stop_loss")
            self._finish_ambiguous_record(record, trade)
        elif hit_stop:
            pos.meta["gap_stop"] = gap_stop
            self.close(self._stop_exit_price(pos, bar, gap_stop), bar.ts, "stop_loss")
        elif hit_target:
            pos.meta["gap_target"] = gap_target
            self.close(self._target_exit_price(pos, bar, gap_target), bar.ts, "take_profit")

    # --------------------------------------------------------------- intrabar
    def _stop_exit_price(self, pos, bar, gap_stop: bool) -> float:
        """Stop market: si la vela abre más allá del stop, el fill es al open."""
        base = bar.open if gap_stop else pos.stop
        price = base - self._slip() if pos.direction == "long" else base + self._slip()
        return round(price / self.tick) * self.tick

    def _target_exit_price(self, pos, bar, gap_target: bool) -> float:
        """Take profit: descuento adverso al target; un gap favorable es mejora."""
        if gap_target:
            return round(bar.open / self.tick) * self.tick
        price = pos.target - self._slip() if pos.direction == "long" else pos.target + self._slip()
        return round(price / self.tick) * self.tick

    def _update_excursions(self, pos, bar) -> None:
        """Actualiza MFE/MAE y el drawdown máximo del P&L no realizado."""
        point = self.settings.execution.point_value
        if pos.direction == "long":
            favorable = bar.high - pos.entry_price
            adverse = bar.low - pos.entry_price
        else:
            favorable = pos.entry_price - bar.low
            adverse = pos.entry_price - bar.high
        risk = abs(pos.entry_price - pos.initial_stop)
        if risk > 0:
            pos.mfe_r = round(max(pos.mfe_r, favorable / risk), 4)
            pos.mae_r = round(min(pos.mae_r, adverse / risk), 4)
        favorable_usd = favorable * point * pos.qty
        adverse_usd = adverse * point * pos.qty
        pos.mfe_usd = round(max(pos.mfe_usd, favorable_usd), 2)
        pos.mae_usd = round(min(pos.mae_usd, adverse_usd), 2)
        # Se asume primero el extremo favorable y después el adverso: el drawdown
        # abierto resultante es el peor dentro de la vela, no una media inventada.
        peak = max(pos.peak_unrealized, favorable_usd)
        pos.peak_unrealized = round(peak, 2)
        pos.open_drawdown = round(max(pos.open_drawdown, peak - adverse_usd), 2)

    def _ambiguous_record(self, pos, bar, *, gap_stop: bool, gap_target: bool) -> dict:
        return {
            "ts": bar.ts,
            "symbol": pos.symbol,
            "qty": pos.qty,
            "entry_ts": pos.entry_ts,
            "entry_price": pos.entry_price,
            "direction": pos.direction,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "stop": pos.stop,
            "target": pos.target,
            "gap_stop": gap_stop,
            "gap_target": gap_target,
            "resolution": "stop_loss_first",
            "mfe_r": pos.mfe_r,
            "mae_r": pos.mae_r,
            "open_drawdown": pos.open_drawdown,
        }

    def _finish_ambiguous_record(self, record: dict, trade: TradeRecord | None) -> None:
        if trade is not None:
            trade.meta["ambiguous_bar"] = True
            record["trade_id"] = trade.id
            record["exit_price"] = trade.exit_price
            record["pnl"] = trade.pnl
        self.ambiguous_count += 1
        self.ambiguous_bars.append(record)
        self.emit(
            "WARNING",
            "execution",
            f"Vela ambigua {pos_label(record['direction'])} en {record['ts']}: SL y TP tocados; se aplica SL primero"
            + (" con gap al open" if record["gap_stop"] else ""),
            {"ambiguous": record},
        )

    # --------------------------------------------------------------------- exit
    def close(self, price: float, ts: int, reason: str) -> TradeRecord | None:
        pos = self.position
        if pos is None:
            return None
        ecfg = self.settings.execution
        gross = (price - pos.entry_price) * ecfg.point_value * pos.qty
        if pos.direction == "short":
            gross = (pos.entry_price - price) * ecfg.point_value * pos.qty
        fees = ecfg.commission_per_contract_side * 2 * pos.qty
        pnl = round(gross - fees, 2)
        risk_dist = abs(pos.entry_price - pos.initial_stop)
        r_mult = round((price - pos.entry_price) * (1 if pos.direction == "long" else -1) / risk_dist, 2) if risk_dist else 0.0
        trade = TradeRecord(
            id=uuid.uuid4().hex[:12],
            symbol=pos.symbol,
            direction=pos.direction,
            qty=pos.qty,
            entry_ts=pos.entry_ts,
            entry_price=pos.entry_price,
            exit_ts=ts,
            exit_price=round(price, 2),
            stop=pos.initial_stop,
            target=pos.target,
            pnl=pnl,
            gross_pnl=round(gross, 2),
            fees=round(fees, 2),
            r_multiple=r_mult,
            risk_amount=pos.risk_amount,
            signal_type=pos.signal_type,
            entry_reason=pos.entry_reason,
            exit_reason=reason,
            duration_sec=max(0, ts - pos.entry_ts),
            mode=self.mode,
            mfe_r=round(pos.mfe_r, 2),
            mae_r=round(pos.mae_r, 2),
            mfe_usd=round(pos.mfe_usd, 2),
            mae_usd=round(pos.mae_usd, 2),
            open_drawdown=round(pos.open_drawdown, 2),
            contract=str(pos.meta.get("contract") or ""),
            expiry=str(pos.meta.get("expiry") or ""),
            meta={"signal_id": pos.signal_id, **pos.meta},
        )
        self.closed_trades.append(trade)
        self.position = None
        self.last_exit_ts = ts
        self.daily_realized += pnl
        label = {
            "stop_loss": "Stop Loss",
            "take_profit": "Take Profit",
            "manual": "cierre manual",
            "session_close": "cierre de sesión",
            "emergency": "parada de emergencia",
        }.get(reason, reason)
        level = "SUCCESS" if pnl > 0 else "WARNING" if pnl == 0 else "ERROR"
        self.emit(
            level,
            "execution",
            f"Posición cerrada por {label} @ {price:.2f} · P&L {pnl:+.2f} USD ({r_mult:+.2f} R)",
            {"trade_id": trade.id, "exit_reason": reason},
        )
        return trade

    # -------------------------------------------------------------------- state
    def orders_snapshot(self) -> list[dict]:
        out = [o.as_dict() for o in self.pending_orders]
        if self.position:
            out.append(
                Order.new(
                    symbol=self.position.symbol,
                    side="sell" if self.position.direction == "long" else "buy",
                    qty=self.position.qty,
                    order_type="stop",
                    limit_price=self.position.stop,
                    role="stop",
                ).as_dict()
            )
            out.append(
                Order.new(
                    symbol=self.position.symbol,
                    side="sell" if self.position.direction == "long" else "buy",
                    qty=self.position.qty,
                    order_type="limit",
                    limit_price=self.position.target,
                    role="target",
                ).as_dict()
            )
        return out

    def restore_position(self, data: dict | None) -> None:
        if not data:
            return
        try:
            self.position = Position(**{k: v for k, v in data.items() if k in Position.__dataclass_fields__})
            self.emit("WARNING", "system", "Posición abierta restaurada desde la base de datos", {"position_id": self.position.id})
        except Exception as exc:  # noqa: BLE001
            self.emit("ERROR", "system", f"No se pudo restaurar la posición: {exc}")

    def position_dict(self, price: float | None = None) -> dict | None:
        if not self.position:
            return None
        return self.position.as_dict(price, self.settings.execution.point_value)
