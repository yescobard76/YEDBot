"""Fase C — divergencias intermarket NQ/ES (SMT).

Diseño anti-repainting: un pivote de profundidad ``d`` solo existe cuando han
cerrado ``d`` velas a su derecha. ``find_pivots`` devuelve ``confirmed_index`` y
el detector solo considera pivotes ya confirmados. Nunca se lee un índice futuro.

La comparación es estructural: para cada nuevo pivote del NQ se toma el extremo
previo relevante (el mínimo más bajo / máximo más alto dentro de la ventana) y se
compara con el extremo equivalente del ES medido en la misma ventana de swing.
Esto evita que un pivote intermedio superficial oculte un barrido real.
"""

from __future__ import annotations

from ..config import SMTConfig
from ..models import Bar, Divergence, Pivot


def find_pivots(bars: list[Bar], depth: int, kind: str) -> list[Pivot]:
    out: list[Pivot] = []
    n = len(bars)
    for i in range(depth, n - depth):
        left = bars[i - depth:i]
        right = bars[i + 1:i + depth + 1]
        # Lado izquierdo estricto, derecho no estricto: los dobles suelos/techos
        # son pivotes válidos y la confirmación ocurre exactamente d velas después.
        if kind == "low":
            if all(bars[i].low < b.low for b in left) and all(bars[i].low <= b.low for b in right):
                out.append(Pivot(i, bars[i].ts, bars[i].low, "low", i + depth))
        else:
            if all(bars[i].high > b.high for b in left) and all(bars[i].high >= b.high for b in right):
                out.append(Pivot(i, bars[i].ts, bars[i].high, "high", i + depth))
    return out


def _swing_extreme(bars: list[Bar], ts: int, half_window: int, kind: str) -> float | None:
    """Extremo del instrumento de referencia en la ventana de swing del pivote."""
    window = [b for b in bars if abs(b.ts - ts) <= half_window]
    if not window:
        return None
    return min(b.low for b in window) if kind == "low" else max(b.high for b in window)


def detect_divergences(
    nq: list[Bar],
    es: list[Bar],
    cfg: SMTConfig,
    tick_size: float = 0.25,
) -> list[Divergence]:
    """Todas las divergencias confirmadas hasta la última vela recibida."""
    if not cfg.enabled or len(nq) < cfg.pivot_depth * 2 + 3 or len(es) < cfg.pivot_depth * 2 + 3:
        return []
    depth = cfg.pivot_depth
    window_bars = cfg.window_minutes
    half_window = depth * 60
    tolerance = cfg.tolerance_ticks * tick_size
    min_break = cfg.min_break_ticks * tick_size

    nq_lows = find_pivots(nq, depth, "low")
    nq_highs = find_pivots(nq, depth, "high")
    out: list[Divergence] = []

    # ---------------------------------------------------------------- alcista
    for p2 in nq_lows:
        priors = [
            p for p in nq_lows
            if p.index < p2.index and p2.index - p.index <= window_bars and p2.price < p.price - min_break
        ]
        if not priors:
            continue
        p1 = min(priors, key=lambda p: p.price)
        ref1 = _swing_extreme(es, p1.ts, half_window, "low")
        ref2 = _swing_extreme(es, p2.ts, half_window, "low")
        if ref1 is None or ref2 is None:
            continue
        # ES no consigue romper su mínimo equivalente (tolerancia configurable).
        if ref2 < ref1 - tolerance:
            continue
        confirm_ts = nq[p2.confirmed_index].ts
        out.append(
            Divergence(
                bias="bullish",
                level=round(p1.price, 4),
                primary_prev=round(p1.price, 4),
                primary_last=round(p2.price, 4),
                reference_prev=round(ref1, 4),
                reference_last=round(ref2, 4),
                confirm_ts=confirm_ts,
                expires_ts=confirm_ts + cfg.validity_minutes * 60,
                pivot_ts=p2.ts,
            )
        )

    # --------------------------------------------------------------- bajista
    for p2 in nq_highs:
        priors = [
            p for p in nq_highs
            if p.index < p2.index and p2.index - p.index <= window_bars and p2.price > p.price + min_break
        ]
        if not priors:
            continue
        p1 = max(priors, key=lambda p: p.price)
        ref1 = _swing_extreme(es, p1.ts, half_window, "high")
        ref2 = _swing_extreme(es, p2.ts, half_window, "high")
        if ref1 is None or ref2 is None:
            continue
        if ref2 > ref1 + tolerance:
            continue
        confirm_ts = nq[p2.confirmed_index].ts
        out.append(
            Divergence(
                bias="bearish",
                level=round(p1.price, 4),
                primary_prev=round(p1.price, 4),
                primary_last=round(p2.price, 4),
                reference_prev=round(ref1, 4),
                reference_last=round(ref2, 4),
                confirm_ts=confirm_ts,
                expires_ts=confirm_ts + cfg.validity_minutes * 60,
                pivot_ts=p2.ts,
            )
        )

    # Deduplicación por (sesgo, pivote) conservando la primera aparición.
    seen: set[tuple[str, int]] = set()
    unique: list[Divergence] = []
    for d in out:
        key = (d.bias, d.pivot_ts)
        if key in seen:
            continue
        seen.add(key)
        unique.append(d)
    unique.sort(key=lambda d: d.confirm_ts)
    return unique


def detect_divergence(
    nq: list[Bar],
    es: list[Bar],
    cfg: SMTConfig,
    tick_size: float = 0.25,
) -> Divergence | None:
    """Divergencia confirmada más reciente (atajo de conveniencia)."""
    found = detect_divergences(nq, es, cfg, tick_size)
    return found[-1] if found else None


def recovery_of(div: Divergence, bars: list[Bar], buffer: float = 0.0) -> tuple[bool, int | None]:
    """Confirma que el precio recuperó el nivel barrido después del pivote."""
    for bar in bars:
        if bar.ts <= div.confirm_ts:
            continue
        if div.bias == "bullish" and bar.close > div.level + buffer:
            return True, bar.ts
        if div.bias == "bearish" and bar.close < div.level - buffer:
            return True, bar.ts
    return False, None
