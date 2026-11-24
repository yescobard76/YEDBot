"""Módulo de riesgo independiente del motor y de la interfaz."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .config import Settings
from .models import Signal
from .timeutil import et_minutes, hm_to_minutes


@dataclass
class RiskDecision:
    ok: bool
    reason: str
    qty: int = 0
    risk_amount: float = 0.0
    stop_ticks: float = 0.0


class RiskManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.emergency = False
        self.emergency_reason = ""
        self.emergency_ts: int | None = None

    # ---------------------------------------------------------------- emergency
    def trigger_emergency(self, reason: str, ts: int) -> None:
        self.emergency = True
        self.emergency_reason = reason
        self.emergency_ts = ts

    def clear_emergency(self) -> None:
        self.emergency = False
        self.emergency_reason = ""
        self.emergency_ts = None

    # ------------------------------------------------------------------ limits
    def daily_loss_limit(self) -> float:
        return self.settings.risk.initial_capital * self.settings.risk.max_daily_loss_pct / 100

    def daily_profit_limit(self) -> float | None:
        pct = self.settings.risk.max_daily_profit_pct
        if pct <= 0:
            return None
        return self.settings.risk.initial_capital * pct / 100

    def size(self, equity: float, stop_ticks: float) -> tuple[int, float, str]:
        rcfg = self.settings.risk
        ecfg = self.settings.execution
        risk_budget = max(equity, 0.0) * rcfg.risk_per_trade_pct / 100
        per_contract = max(stop_ticks, 1.0) * ecfg.tick_value
        if per_contract <= 0:
            return 0, 0.0, "Valor de tick inválido"
        qty = math.floor(risk_budget / per_contract)
        qty = min(qty, rcfg.max_contracts)
        if qty < 1:
            return 0, 0.0, (
                f"Capital/riesgo insuficiente: {risk_budget:.2f} USD para {per_contract:.2f} USD por contrato"
            )
        risk_amount = round(qty * per_contract, 2)
        return qty, risk_amount, ""

    def _min_stop_or_reason(self, signal: Signal, stop_ticks: float) -> str:
        """Motivo de rechazo si el stop es demasiado estrecho frente al ORB.

        La regla solo se evalúa cuando está activada. Si falta el ancho del ORB
        o no es válido, la señal se rechaza: no se puede validar la geometría y
        dejarla pasar convertiría el filtro en un no-op silencioso.
        """
        ratio = self.settings.risk.min_stop_or_ratio
        if ratio <= 0:
            return ""
        meta = signal.meta if isinstance(signal.meta, dict) else {}
        try:
            orb_high = float(meta["orb_high"])
            orb_low = float(meta["orb_low"])
        except (KeyError, TypeError, ValueError):
            return "Sin datos de ORB para validar la relación stop/ORB"
        width_ticks = (orb_high - orb_low) / self.settings.execution.tick_size
        if not math.isfinite(width_ticks) or width_ticks <= 0:
            return "Ancho de ORB inválido para validar la relación stop/ORB"
        stop_or = stop_ticks / width_ticks
        if not math.isfinite(stop_or):
            return "Relación stop/ORB inválida"
        if stop_or < ratio:
            return (
                f"Relación stop/ORB {stop_or:.3f} por debajo del mínimo "
                f"({ratio:.2f})"
            )
        return ""

    # ------------------------------------------------------------------ checks
    def evaluate(
        self,
        signal: Signal,
        *,
        equity: float,
        open_positions: int,
        day_pnl: float,
        day_start_equity: float,
        trades_today: int,
        now_ts: int,
        last_exit_ts: int | None,
        consecutive_losses: int,
        has_pending_entry: bool,
    ) -> RiskDecision:
        rcfg = self.settings.risk
        tick = self.settings.execution.tick_size
        stop_ticks = abs(signal.entry_price - signal.stop) / tick

        if self.emergency:
            return RiskDecision(False, f"Parada de emergencia activa: {self.emergency_reason}")
        if has_pending_entry:
            return RiskDecision(False, "Ya existe una orden de entrada pendiente")
        if open_positions >= rcfg.max_concurrent_positions:
            return RiskDecision(False, "Máximo de posiciones simultáneas alcanzado")
        if trades_today >= rcfg.max_trades_per_day:
            return RiskDecision(False, f"Máximo de operaciones diarias alcanzado ({rcfg.max_trades_per_day})")
        # Segunda defensa: el tope se comprueba antes de calcular qty. No es
        # un límite de sizing; una señal que lo supera se rechaza.
        if stop_ticks > rcfg.max_sl_ticks:
            return RiskDecision(False, f"Stop de {stop_ticks:.0f} ticks excede el máximo ({rcfg.max_sl_ticks})")

        minute = et_minutes(now_ts, self.settings.orb.timezone)
        start_min = hm_to_minutes(rcfg.trade_window_start)
        end_min = hm_to_minutes(rcfg.trade_window_end)
        if not (start_min <= minute <= end_min):
            return RiskDecision(False, f"Fuera de la ventana de operación ({rcfg.trade_window_start}–{rcfg.trade_window_end} ET)")

        if rcfg.entry_exclusion_start and rcfg.entry_exclusion_end:
            exclusion_start = hm_to_minutes(rcfg.entry_exclusion_start)
            exclusion_end = hm_to_minutes(rcfg.entry_exclusion_end)
            # Rango semiabierto [inicio, fin): bloquea 11:00:00–12:59:59 y
            # permite reanudar exactamente a las 13:00:00.
            if exclusion_start <= minute < exclusion_end:
                return RiskDecision(
                    False,
                    "Ventana de exclusión de entradas activa "
                    f"({rcfg.entry_exclusion_start}–{rcfg.entry_exclusion_end} ET)",
                )

        stop_or_reason = self._min_stop_or_reason(signal, stop_ticks)
        if stop_or_reason:
            return RiskDecision(False, stop_or_reason)

        loss_limit = -day_start_equity * rcfg.max_daily_loss_pct / 100
        if day_pnl <= loss_limit:
            return RiskDecision(False, f"Límite de pérdida diaria alcanzado ({day_pnl:.2f} USD)")
        profit_limit = self.daily_profit_limit()
        if profit_limit and day_pnl >= profit_limit:
            return RiskDecision(False, f"Objetivo de beneficio diario alcanzado ({day_pnl:.2f} USD)")
        if rcfg.no_trade_after_consecutive_losses and consecutive_losses >= rcfg.no_trade_after_consecutive_losses:
            return RiskDecision(False, f"{consecutive_losses} pérdidas consecutivas: entradas bloqueadas")
        if last_exit_ts and rcfg.cooldown_minutes:
            elapsed = (now_ts - last_exit_ts) / 60
            if elapsed < rcfg.cooldown_minutes:
                return RiskDecision(False, f"Cooldown activo ({rcfg.cooldown_minutes - elapsed:.1f} min restantes)")

        qty, risk_amount, err = self.size(equity, stop_ticks)
        if qty < 1:
            return RiskDecision(False, err, 0, 0.0, stop_ticks)
        return RiskDecision(True, "", qty, risk_amount, stop_ticks)

    # ------------------------------------------------------------------- stats
    def open_risk_pct(self, risk_amount: float, equity: float) -> float:
        if equity <= 0:
            return 0.0
        return round(risk_amount / equity * 100, 2)
