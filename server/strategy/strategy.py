"""Fases B–E: ruptura, SMT, retesteo y entrada.

``ORBStrategy.evaluate`` es determinista: recibe únicamente velas de 1m ya
cerradas y reconstruye el estado de la sesión. No hay estado oculto que pueda
repintar ni lectura de índices futuros; el motor deduplica señales ya vistas
mediante ``signal.id``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ..config import Settings
from ..models import Bar, Divergence, Signal
from ..timeutil import et_date, et_hm, timestamp_for
from .indicators import aggregate, atr, find_swing
from .orb import OpeningRange, build_opening_range
from .smt import detect_divergences, recovery_of

PENDING = "pending"
IN_PROGRESS = "in_progress"
CONFIRMED = "confirmed"
REJECTED = "rejected"
EXPIRED = "expired"
WAITING = "waiting"

PHASE_ORDER: list[tuple[str, str]] = [
    ("session", "Sesión iniciada"),
    ("opening_range", "Opening Range completado"),
    ("breakout", "Ruptura detectada"),
    ("smt", "Divergencia SMT"),
    ("retest", "Retesteo"),
    ("entry", "Confirmación de entrada"),
    ("management", "Gestión de operación"),
]


@dataclass
class Assess:
    session_date: str | None = None
    opening_range: dict | None = None
    breakout: dict | None = None
    smt: dict | None = None
    retest: dict | None = None
    signal: Signal | None = None
    phases: list[dict] = field(default_factory=list)
    reject: str | None = None
    markers: list[dict] = field(default_factory=list)
    atr: float | None = None
    reference_level: float | None = None
    # Diagnóstico estructurado para el embudo del backtest. No participa en
    # ninguna decisión: solo evita que el registro dependa del texto de la UI.
    reject_code: str | None = None
    reject_ts: int | None = None
    smt_diagnostics: dict = field(default_factory=dict)
    # Observabilidad E-1 por evento. No participa en ninguna decisión ni
    # modifica precios, stops, sizing o fills.
    event_metrics: dict = field(default_factory=dict)

    def phase(self, key: str) -> dict | None:
        for p in self.phases:
            if p["key"] == key:
                return p
        return None


def _phase(key: str, label: str, status: str, detail: str, ts: int | None = None) -> dict:
    return {"key": key, "label": label, "status": status, "detail": detail, "ts": ts}


class _Phases:
    def __init__(self, detail: str = "Esperando datos de mercado") -> None:
        self.data = {key: _phase(key, label, PENDING, detail) for key, label in PHASE_ORDER}

    def set(self, key: str, status: str, detail: str, ts: int | None = None) -> None:
        self.data[key] = _phase(key, self.data[key]["label"], status, detail, ts)

    def as_list(self) -> list[dict]:
        return [self.data[key] for key, _ in PHASE_ORDER]


class ORBStrategy:
    def __init__(
        self,
        settings: Settings,
        price_offsets: dict[str, float] | None = None,
    ) -> None:
        self.settings = settings
        self.tick = settings.execution.tick_size
        # Offset acumulado de la serie adjusted por sesion. Permite redondear
        # los niveles en la base sin ajustar y trasladarlos despues, de modo
        # que raw y adjusted compartan exactamente la misma rejilla de precio.
        self.price_offsets = price_offsets or {}

    def _round_price(self, value: float, day: date) -> float:
        offset = self.price_offsets.get(day.isoformat(), 0.0)
        if offset:
            return round(value - offset, 2) + offset
        return round(value, 2)

    @property
    def cfg(self):
        return self.settings.strategy

    # ------------------------------------------------------------------ evaluate
    def evaluate(self, nq: list[Bar], es: list[Bar], trade_window_open: bool = True) -> Assess:
        sc, oc = self.settings.strategy, self.settings.orb
        tick = self.tick
        if len(nq) < 2:
            phases = _Phases()
            return Assess(phases=phases.as_list())

        last = nq[-1]
        day = et_date(last.ts)
        start_ts = timestamp_for(day, oc.start, oc.timezone)
        end_ts = timestamp_for(day, oc.end, oc.timezone)
        session = [b for b in nq if et_date(b.ts) == day and b.ts >= start_ts]
        if not session:
            return Assess(session_date=day.isoformat(), phases=_Phases("Esperando el inicio de la sesión").as_list())

        ph = _Phases()
        assess = Assess(session_date=day.isoformat())
        ph.set("session", CONFIRMED, f"Sesión {day.isoformat()} en curso", session[0].ts)

        # ------------------------------------------------------------- Fase A
        orb = build_opening_range(session, oc, tick)
        assess.opening_range = orb.as_dict() if orb else None
        or_reject: str | None = None
        if orb is None:
            ph.set("opening_range", IN_PROGRESS, "Formando rango")
        elif not orb.complete:
            ph.set(
                "opening_range",
                IN_PROGRESS,
                f"Formando rango ({orb.bars} velas) · máx {orb.high:.2f} / mín {orb.low:.2f}",
                last.ts,
            )
        else:
            if orb.width_pct > oc.max_width_pct:
                or_reject = f"Rango demasiado amplio ({orb.width_pct:.2f}% > {oc.max_width_pct:.2f}%)"
                assess.reject_code = "or_too_wide"
            elif orb.width < sc.min_range_ticks * tick:
                or_reject = f"Rango demasiado estrecho ({orb.width / tick:.0f} ticks)"
                assess.reject_code = "or_too_narrow"
            detail = or_reject or (
                f"H {orb.high:.2f} · L {orb.low:.2f} · Mid {orb.mid:.2f} · "
                f"amplitud {orb.width:.2f} pts ({orb.width_pct:.2f}%)"
            )
            ph.set("opening_range", REJECTED if or_reject else CONFIRMED, detail, orb.end_ts)
            if or_reject:
                assess.reject = or_reject
                assess.reject_ts = orb.end_ts

        ph.set("breakout", PENDING, "Esperando cierre posterior al Opening Range")
        ph.set("smt", PENDING, "Esperando divergencia NQ/ES")
        ph.set("retest", PENDING, "Sin ruptura confirmada")
        ph.set("entry", PENDING, "Sin señal")
        ph.set("management", WAITING, "En espera de ejecución")
        assess.phases = ph.as_list()

        if not orb or not orb.complete or or_reject:
            return assess

        conf_min = self.settings.confirm_minutes()
        post = [b for b in session if b.ts >= end_ts]
        bars_conf = aggregate(post, conf_min)
        buf = sc.breakout_buffer_ticks * tick
        orh, orl, mid = orb.high, orb.low, orb.mid

        # ------------------------------------------------------------- Fase B
        breakout: dict | None = None
        wick: dict | None = None
        bo_index: int | None = None
        for i, bar in enumerate(bars_conf):
            if bar.close > orh + buf:
                breakout, bo_index = self._breakout("long", orh, bar, i, conf_min, "close"), i
                break
            if bar.close < orl - buf:
                breakout, bo_index = self._breakout("short", orl, bar, i, conf_min, "close"), i
                break
            if bar.high > orh + buf:
                wick = self._breakout("long", orh, bar, i, conf_min, "wick")
            elif bar.low < orl - buf:
                wick = self._breakout("short", orl, bar, i, conf_min, "wick")

        if breakout is None and wick is not None and not sc.require_close_breakout:
            breakout, bo_index = dict(wick), wick["index"]
            breakout["type"] = "wick_accepted"

        if breakout is None:
            ph.set(
                "breakout",
                IN_PROGRESS,
                "Ruptura por mecha sin cierre de confirmación" if wick else "Esperando ruptura del rango",
                (wick or {}).get("ts"),
            )
            if wick:
                assess.breakout = dict(wick, rejected=True)
            assess.phases = ph.as_list()
            return assess

        assess.breakout = breakout
        assess.event_metrics = {
            "event_id": f"{day.isoformat()}-{breakout['direction']}-{breakout['ts']}",
            "retest_distance_ticks": None,
            "direct_stop_ticks": None,
            "entry_delay_min": None,
            "stop_ticks": None,
            "stop_cap_binding": False,
        }
        assess.markers.append(
            {
                "ts": breakout["ts"],
                "price": breakout["close"],
                "type": "breakout",
                "direction": breakout["direction"],
                "label": f"Ruptura {'alcista' if breakout['direction'] == 'long' else 'bajista'} confirmada",
            }
        )
        ph.set(
            "breakout",
            CONFIRMED,
            f"{'Alcista' if breakout['direction'] == 'long' else 'Bajista'} · cierre "
            f"{breakout['close']:.2f} {'>' if breakout['direction'] == 'long' else '<'} {breakout['level']:.2f} "
            f"({sc.confirm_tf})",
            breakout["ts"],
        )

        if bo_index is not None:
            for bar in bars_conf[bo_index + 1:]:
                failed = (breakout["direction"] == "long" and bar.close < orl - buf) or (
                    breakout["direction"] == "short" and bar.close > orh + buf
                )
                if failed:
                    assess.breakout = {**breakout, "failed": True, "failed_ts": bar.ts}
                    assess.reject = "Falso rompimiento: el precio cerró de vuelta al otro extremo del rango"
                    assess.reject_code = "false_breakout"
                    assess.reject_ts = bar.ts
                    ph.set("breakout", REJECTED, assess.reject, bar.ts)
                    ph.set("retest", PENDING, "Setup invalidado")
                    assess.markers.append(
                        {
                            "ts": bar.ts,
                            "price": bar.close,
                            "type": "false_breakout",
                            "direction": breakout["direction"],
                            "label": "Falso rompimiento",
                        }
                    )
                    assess.phases = ph.as_list()
                    return assess

        now_ts = last.ts + 60
        if now_ts - breakout["confirm_ts"] > sc.setup_validity_minutes * 60:
            return self._expire(assess, ph, now_ts)

        # ------------------------------------------------------------- Fase C
        direction = breakout["direction"]
        divergence: Divergence | None = None
        ready, smt_diagnostics = self._smt_candidates(session, es, direction, now_ts, buf)
        assess.smt_diagnostics = smt_diagnostics
        if not smt_diagnostics.get("enabled"):
            ph.set("smt", CONFIRMED, "SMT desactivado en la configuración", None)
        else:
            wanted = "bullish" if direction == "long" else "bearish"
            bias_label = "alcista" if wanted == "bullish" else "bajista"
            if not ready:
                if smt_diagnostics.get("pending_recovery"):
                    detail = f"Divergencia {bias_label} detectada · esperando recuperación del nivel"
                    ph.set("smt", IN_PROGRESS, detail, None)
                elif smt_diagnostics.get("matching"):
                    ph.set("smt", EXPIRED, f"Divergencia {bias_label} caducada antes de recuperar", None)
                else:
                    ph.set("smt", IN_PROGRESS, f"Sin divergencia {bias_label} confirmada todavía", None)
                ph.set("retest", PENDING, "Bloqueado: la estrategia exige divergencia SMT")
                assess.phases = ph.as_list()
                return assess

            # La divergencia relevante es la última confirmada ANTES de la
            # ruptura; si la SMT llegó después, se usa la primera posterior.
            divergence, rec_ts = self._select_divergence(ready, breakout)
            assess.smt = divergence.as_dict()
            ph.set(
                "smt",
                CONFIRMED,
                f"{bias_label.capitalize()} · NQ {divergence.primary_last:.2f} vs {divergence.primary_prev:.2f} · "
                f"ES {divergence.reference_last:.2f} vs {divergence.reference_prev:.2f}",
                rec_ts or divergence.confirm_ts,
            )
            assess.markers.append(
                {
                    "ts": divergence.pivot_ts,
                    "price": divergence.primary_last,
                    "type": "smt",
                    "direction": divergence.bias,
                    "label": f"Divergencia SMT {bias_label} (NQ vs ES)",
                }
            )

        # ------------------------------------------------------------- Fase D
        direct = sc.entry_reference == "none"
        retest_ts: int | None = None
        if direct:
            # Variante de entrada directa: sin esperar retesteo. Si la SMT se
            # confirma después de la ruptura, la entrada espera a esa confirmación.
            ref, ref_name = breakout["close"], "precio de ruptura"
            entry_ts = breakout["confirm_ts"]
            if divergence is not None:
                entry_ts = max(entry_ts, divergence.confirm_ts + 60)
            trigger_bar = next((b for b in session if b.ts + 60 >= entry_ts), session[-1])
            entry_price = trigger_bar.close
            entry_price = max(entry_price, ref) if direction == "long" else min(entry_price, ref)
            assess.event_metrics["retest_distance_ticks"] = 0.0
            self._observe_event(assess, breakout, divergence, orb, session, conf_min)
            ph.set("retest", CONFIRMED, "Entrada directa a la ruptura (variante configurada)", entry_ts)
        else:
            ref, ref_name = self._reference(breakout, orb, session)
            assess.event_metrics["retest_distance_ticks"] = round(
                abs(float(breakout["close"]) - ref) / tick, 1
            )
            self._observe_event(assess, breakout, divergence, orb, session, conf_min)
            tol = sc.retest_tolerance_ticks * tick
            after_bo = [b for b in session if b.ts >= breakout["ts"] + conf_min * 60]
            touch: Bar | None = None
            for bar in after_bo:
                if direction == "long" and bar.low <= ref + tol:
                    touch = bar
                    break
                if direction == "short" and bar.high >= ref - tol:
                    touch = bar
                    break

            if touch is None:
                ph.set(
                    "retest",
                    IN_PROGRESS,
                    f"Esperando retesteo de {ref_name} {ref:.2f} (tol {sc.retest_tolerance_ticks} ticks)",
                    None,
                )
                assess.phases = ph.as_list()
                return assess

            retest_ts = touch.ts
            assess.retest = {
                "level": round(ref, 2),
                "name": ref_name,
                "touch_ts": touch.ts,
                "touch_price": touch.close,
                "tolerance_ticks": sc.retest_tolerance_ticks,
            }
            assess.markers.append(
                {
                    "ts": touch.ts,
                    "price": ref,
                    "type": "retest",
                    "direction": direction,
                    "label": f"Retesteo {ref_name}",
                }
            )
            ph.set(
                "retest",
                CONFIRMED,
                f"Toque de {ref_name} {ref:.2f} a las {et_hm(touch.ts, oc.timezone)}",
                touch.ts,
            )

            # ``require_recovery_close`` es independiente de ``entry_trigger``:
            # - true  -> exige una vela que cierre de vuelta sobre el nivel.
            # - false -> acepta el rechazo dentro de la tolerancia (toque) y no
            #            espera confirmación adicional. Si entry_trigger=close,
            #            el cierre usado es el de la vela del toque.
            # - true + touch -> exige recuperación, pero usa el cierre del toque
            #                   como referencia de entrada.
            recovery: Bar | None = None
            if sc.require_recovery_close:
                for bar in session:
                    if bar.ts <= touch.ts:
                        continue
                    if direction == "long" and bar.close >= ref + buf:
                        recovery = bar
                        break
                    if direction == "short" and bar.close <= ref - buf:
                        recovery = bar
                        break
                if recovery is None:
                    ph.set("entry", IN_PROGRESS, f"Esperando cierre de recuperación sobre {ref:.2f}", None)
                    assess.phases = ph.as_list()
                    return assess

            trigger_bar = touch
            if recovery is not None and sc.entry_trigger == "close":
                trigger_bar = recovery
            entry_price = trigger_bar.close
            entry_ts = trigger_bar.ts + 60
            if direction == "long" and entry_price <= ref:
                entry_price = ref + buf
            if direction == "short" and entry_price >= ref:
                entry_price = ref - buf

        assess.reference_level = self._round_price(ref, day)
        if not trade_window_open:
            ph.set("entry", REJECTED, "Fuera de la ventana de operación", entry_ts)
            assess.reject = "Fuera de la ventana permitida para operar"
            assess.reject_code = "outside_window"
            assess.reject_ts = entry_ts
            assess.phases = ph.as_list()
            return assess

        # ------------------------------------------------------------- Fase E
        atr_value = atr(bars_conf[-max(sc.atr_period, 2):], sc.atr_period) or 0.0
        assess.atr = round(atr_value, 3) if atr_value else None
        stop = self._stop(entry_price, direction, orb, session, entry_ts, atr_value, conf_min)
        if stop is None:
            ph.set("entry", REJECTED, "No se pudo determinar el Stop Loss", entry_ts)
            assess.reject = "Sin referencia estructural válida para el Stop Loss"
            assess.reject_code = "no_stop"
            assess.reject_ts = entry_ts
            assess.phases = ph.as_list()
            return assess

        risk_distance = abs(entry_price - stop)
        if risk_distance / tick < 4:
            stop = entry_price - 4 * tick if direction == "long" else entry_price + 4 * tick
            risk_distance = abs(entry_price - stop)
        stop_ticks = risk_distance / tick
        # E-ATR-1: el tope es una guardia de elegibilidad compartida por control
        # y tratamiento. Se aplica antes del sizing; el 1 % no lo sustituye.
        if stop_ticks > self.settings.risk.max_sl_ticks:
            assess.event_metrics["stop_ticks"] = round(stop_ticks, 1)
            assess.event_metrics["stop_cap_binding"] = True
            assess.reject = f"Stop de {stop_ticks:.0f} ticks supera el máximo permitido ({self.settings.risk.max_sl_ticks})"
            assess.reject_code = "stop_cap"
            assess.reject_ts = entry_ts
            ph.set("entry", REJECTED, assess.reject, entry_ts)
            assess.phases = ph.as_list()
            return assess

        target = entry_price + sc.tp_rr * risk_distance * (1 if direction == "long" else -1)
        use_retest = not direct
        assess.event_metrics["entry_delay_min"] = round(
            (entry_ts - float(breakout["confirm_ts"])) / 60, 1
        )
        assess.event_metrics["stop_ticks"] = round(stop_ticks, 1)
        assess.event_metrics["stop_cap_binding"] = False
        signal = Signal(
            id=f"{day.isoformat()}-{direction}-{breakout['ts']}",
            ts=entry_ts,
            direction=direction,
            entry_price=self._round_price(entry_price, day),
            stop=self._round_price(stop, day),
            target=self._round_price(target, day),
            qty=0,
            risk_amount=0.0,
            signal_type=self._signal_type(bool(divergence), use_retest),
            entry_reason=self._reason(
                direction, breakout, divergence, ref, ref_name, trigger_bar, direct
            ),
            reference_level=self._round_price(ref, day),
            breakout_level=self._round_price(breakout["level"], day),
            smt_bias=divergence.bias if divergence else None,
            meta={
                "orb_high": orb.high,
                "orb_low": orb.low,
                "orb_mid": orb.mid,
                "stop_ticks": round(stop_ticks, 1),
                "rr": sc.tp_rr,
                "confirm_tf": sc.confirm_tf,
                "entry_reference": sc.entry_reference,
                "retest_depth": sc.retest_depth,
                "or_retracement_pct": sc.or_retracement_pct if sc.entry_reference == "or_retracement" else None,
                "event_id": assess.event_metrics.get("event_id"),
                "retest_distance_ticks": assess.event_metrics.get("retest_distance_ticks"),
                "direct_stop_ticks": assess.event_metrics.get("direct_stop_ticks"),
                "entry_delay_min": assess.event_metrics.get("entry_delay_min"),
                "sl_mode": sc.sl_mode,
                "require_recovery_close": sc.require_recovery_close,
                "structural_depth": sc.structural_depth,
                "sl_buffer_ticks": sc.sl_buffer_ticks,
                "breakout_ts": breakout["ts"],
                "retest_ts": retest_ts,
                "trigger_ts": trigger_bar.ts,
                "direct_entry": direct,
            },
        )
        assess.signal = signal
        assess.markers.append(
            {
                "ts": entry_ts,
                "price": signal.entry_price,
                "type": "entry",
                "direction": direction,
                "label": f"Entrada {signal.signal_type}",
            }
        )
        ph.set(
            "entry",
            CONFIRMED,
            f"{'Larga' if direction == 'long' else 'Corta'} @ {signal.entry_price:.2f} · "
            f"SL {signal.stop:.2f} · TP {signal.target:.2f} · {stop_ticks:.0f} ticks",
            entry_ts,
        )
        ph.set("management", PENDING, "Señal validada, pendiente de ejecución", entry_ts)
        assess.phases = ph.as_list()
        return assess

    # ------------------------------------------------------------------ pieces
    @staticmethod
    def _expire(assess: Assess, ph: _Phases, now_ts: int) -> Assess:
        """Cierre común del setup expirado, sin alterar el camino histórico."""
        assess.reject = "Setup expirado antes de completar el retesteo"
        assess.reject_code = "setup_expired"
        assess.reject_ts = now_ts
        ph.set("retest", EXPIRED, assess.reject, now_ts)
        assess.phases = ph.as_list()
        return assess

    def _smt_candidates(
        self,
        session: list[Bar],
        es: list[Bar],
        direction: str,
        now_ts: int,
        buffer: float,
    ) -> tuple[list[tuple[Divergence, int | None]], dict]:
        """Divergencias SMT vigentes y alineadas, listas para entrada."""
        if not (self.cfg.use_smt and self.settings.smt.enabled):
            return [], {"enabled": False}

        es_map = {b.ts: b for b in es}
        nq_al = [b for b in session if b.ts in es_map]
        es_al = [es_map[b.ts] for b in nq_al]
        wanted = "bullish" if direction == "long" else "bearish"
        all_divs = detect_divergences(nq_al, es_al, self.settings.smt, self.tick)
        matching = [d for d in all_divs if d.bias == wanted]
        fresh = [
            d
            for d in matching
            if now_ts - d.confirm_ts <= self.settings.smt.validity_minutes * 60
        ]
        ready: list[tuple[Divergence, int | None]] = []
        pending_recovery = False
        for divergence in fresh:
            recovered, recovery_ts = recovery_of(divergence, session, buffer)
            if self.settings.smt.require_recovery and not recovered:
                pending_recovery = True
                continue
            ready.append((divergence, recovery_ts))

        return ready, {
            "enabled": True,
            "matching": len(matching),
            "fresh": len(fresh),
            "ready": len(ready),
            "pending_recovery": pending_recovery,
            "expired_before_recovery": bool(matching) and not fresh and not ready,
        }

    @staticmethod
    def _select_divergence(
        ready: list[tuple[Divergence, int | None]], breakout: dict
    ) -> tuple[Divergence, int | None]:
        """Última SMT previa a la ruptura; si no hay, la primera posterior."""
        before = [item for item in ready if item[0].confirm_ts <= breakout["confirm_ts"]]
        return (
            max(before, key=lambda item: item[0].confirm_ts)
            if before
            else min(ready, key=lambda item: item[0].confirm_ts)
        )

    def _breakout(self, direction: str, level: float, bar: Bar, index: int, conf_min: int, kind: str) -> dict:
        return {
            "direction": direction,
            "level": round(level, 4),
            "open": round(bar.open, 4),
            "close": round(bar.close, 4),
            "high": round(bar.high, 4),
            "low": round(bar.low, 4),
            "ts": bar.ts,
            "confirm_ts": bar.ts + conf_min * 60,
            "timeframe": f"{conf_min}m",
            "type": kind,
            "index": index,
        }

    def _reference(self, breakout: dict, orb: OpeningRange, session: list[Bar]) -> tuple[float, str]:
        mode = self.cfg.entry_reference
        if mode == "or_mid":
            depth = self.cfg.retest_depth
            # El valor por defecto debe devolver exactamente el mid histórico,
            # sin introducir un error de coma flotante en la decisión.
            if depth == 1.0:
                return orb.mid, "50% del Opening Range"
            if breakout["direction"] == "long":
                level = orb.high - depth * (orb.high - orb.mid)
            else:
                level = orb.low + depth * (orb.mid - orb.low)
            return level, f"retesteo {depth * 100:g}% del semiancho"
        if mode == "or_retracement":
            pct = self.cfg.or_retracement_pct
            if breakout["direction"] == "long":
                level = orb.high - orb.width * pct
            else:
                level = orb.low + orb.width * pct
            label = f"retroceso {pct * 100:.1f}% del Opening Range".replace(".0%", "%")
            return level, label
        if mode == "breakout_level":
            return breakout["level"], "nivel de ruptura"
        if mode == "half_leg":
            leg = [b for b in session if b.ts >= breakout["ts"]]
            if breakout["direction"] == "long":
                extreme = max((b.high for b in leg), default=orb.high)
                return orb.high + (extreme - orb.high) * 0.5, "50% de la pierna de ruptura"
            extreme = min((b.low for b in leg), default=orb.low)
            return orb.low - (orb.low - extreme) * 0.5, "50% de la pierna de ruptura"
        return breakout["close"], "precio de ruptura"

    def _observe_event(
        self,
        assess: Assess,
        breakout: dict,
        divergence: Divergence | None,
        orb: OpeningRange,
        session: list[Bar],
        conf_min: int,
    ) -> None:
        """Completa las métricas E-1 del evento sin alterar la decisión.

        ``direct_stop_ticks`` simula únicamente el precio y el stop de una
        entrada directa en el mismo evento. No arma nada, no modifica la señal
        real y usa solo velas cerradas hasta ``entry_ts``.
        """
        metrics = assess.event_metrics
        if not metrics or not session:
            return
        direction = breakout["direction"]
        entry_ts = int(breakout["confirm_ts"])
        if divergence is not None:
            entry_ts = max(entry_ts, int(divergence.confirm_ts) + 60)
        trigger = next((b for b in session if b.ts + 60 >= entry_ts), session[-1])
        entry = trigger.close
        if direction == "long":
            entry = max(entry, float(breakout["close"]))
        else:
            entry = min(entry, float(breakout["close"]))
        history = [b for b in session if b.ts + 60 <= entry_ts]
        conf_bars = aggregate(history, conf_min)
        if not conf_bars:
            return
        atr_value = atr(conf_bars[-max(self.cfg.atr_period, 2):], self.cfg.atr_period) or 0.0
        stop = self._stop(
            entry, direction, orb, session, entry_ts, atr_value, conf_min
        )
        if stop is None:
            return
        metrics["direct_stop_ticks"] = round(abs(entry - stop) / self.tick, 1)

    def _stop(
        self,
        entry: float,
        direction: str,
        orb: OpeningRange,
        session: list[Bar],
        entry_ts: int,
        atr_value: float,
        conf_min: int,
    ) -> float | None:
        sc = self.cfg
        tick = self.tick
        buffer = sc.sl_buffer_ticks * tick
        min_distance = max(8 * tick, (atr_value or 0.0) * 0.25)
        if sc.sl_mode == "atr":
            # Un ATR ausente o nulo no debe caer silenciosamente al stop
            # estructural: la señal no tiene stop ATR válido y se rechaza.
            if not atr_value:
                return None
            base = entry - atr_value * sc.atr_sl_mult if direction == "long" else entry + atr_value * sc.atr_sl_mult
        elif sc.sl_mode == "or_mid":
            base = orb.mid - buffer if direction == "long" else orb.mid + buffer
        elif sc.sl_mode == "confirmation":
            # E-1: extremo de las últimas ``structural_depth`` velas de
            # confirmación, sin anclaje al mid del OR y sin ATR. El mínimo de
            # 8 ticks es parte de la definición pre-registrada.
            history = [b for b in session if b.ts + 60 <= entry_ts]
            conf_bars = aggregate(history, conf_min)
            if not conf_bars:
                return None
            recent = conf_bars[-max(sc.structural_depth, 1):]
            swing = (
                min(b.low for b in recent)
                if direction == "long"
                else max(b.high for b in recent)
            )
            base = swing - buffer if direction == "long" else swing + buffer
            minimum = 8 * tick
            return (
                min(base, entry - minimum)
                if direction == "long"
                else max(base, entry + minimum)
            )
        else:
            # Estructura en la temporalidad de confirmación (no micro-ruido de 1m).
            history = [b for b in session if b.ts + 60 <= entry_ts]
            conf_bars = aggregate(history, conf_min)
            swing = find_swing(conf_bars, direction, sc.structural_depth)
            if swing is None:
                swing = orb.low if direction == "long" else orb.high
            if direction == "long":
                base = min(swing, orb.mid) - buffer
            else:
                base = max(swing, orb.mid) + buffer
        if direction == "long":
            return min(base, entry - min_distance)
        return max(base, entry + min_distance)

    def _reason(
        self,
        direction: str,
        breakout: dict,
        divergence: Divergence | None,
        ref: float,
        ref_name: str,
        trigger: Bar,
        direct: bool = False,
    ) -> str:
        side = "alcista" if direction == "long" else "bajista"
        text = (
            f"Ruptura {side} del {'ORH' if direction == 'long' else 'ORL'} {breakout['level']:.2f} "
            f"confirmada por cierre {breakout['timeframe']}"
        )
        if divergence:
            text += (
                f" · SMT {'alcista' if divergence.bias == 'bullish' else 'bajista'} "
                f"(NQ {divergence.primary_last:.2f}, ES {divergence.reference_last:.2f})"
            )
        if direct:
            text += f" · entrada directa a {ref:.2f} (sin retesteo)"
        else:
            text += f" · retesteo de {ref_name} {ref:.2f}"
            if self.cfg.require_recovery_close and self.cfg.entry_trigger == "close":
                text += f" con cierre de recuperación {trigger.close:.2f}"
            elif self.cfg.require_recovery_close:
                text += (
                    " con recuperación confirmada; referencia de entrada en el "
                    "cierre del toque"
                )
            else:
                text += " sin exigir cierre de recuperación (rechazo dentro de tolerancia)"
        return text

    def _signal_type(self, use_smt: bool, use_retest: bool) -> str:
        parts = ["ORB"]
        if use_smt:
            parts.append("SMT")
        if use_retest:
            parts.append("Retest")
        return "+".join(parts)
