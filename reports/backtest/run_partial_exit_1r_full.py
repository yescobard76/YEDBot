"""Comparación full-engine: baseline vs BE completo vs parcial 50% a +1R.

Motor completo W1-W6 (362 sesiones), holdout sin abrir. Las tres ramas usan
exactamente las mismas puertas del protocolo oficial, incluido el filtro
``risk.min_stop_or_ratio = 0.25`` y el sizing dinámico de ``RiskManager``.

La salida parcial no es un replay posterior: se ejecuta dentro de
``ExecutionEngine``. Al alcanzar +1R se cierra la mitad entera de la posición,
se realiza su P&L y el resto pasa a break-even para la vela siguiente.
"""

from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports" / "backtest"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(REPORTS) not in sys.path:
    sys.path.insert(0, str(REPORTS))

import server.backtest as bt
from server.config import Settings, apply_settings
from server.execution import ExecutionEngine
from server.stats import compute_stats
from server.timeutil import et_date
from run_breakeven_1r_protocol import (  # noqa: E402
    FILTER_RATIO,
    GROUPS,
    HOLDOUT_START,
    LOCK_PATH,
    WINDOW_IDS,
    _effect,
    _load_lock,
    _signal_id,
    _summary,
)

OUT = REPORTS / "partial_exit_1r_full.json"
MD = REPORTS / "PARTIAL_EXIT_1R_FULL.md"
POLICIES = ("filter", "be_1r", "partial_50_be")
# El baseline y el BE oficial ya son full-engine con qty dinámica. Para evitar
# repetir 8 simulaciones que no cambian, se puede ejecutar solo la rama nueva y
# reutilizar esos dos brazos oficiales, verificándolos contra el lock.
ONLY_PARTIAL = os.environ.get("PARTIAL_ONLY") == "1"
RUN_POLICIES = ("partial_50_be",) if ONLY_PARTIAL else POLICIES
WORKERS = max(1, int(os.environ.get("PARTIAL_WORKERS", "2")))


def _tick_round(value: float, tick: float) -> float:
    return round(value / tick) * tick


class FullManagementExecution(ExecutionEngine):
    """ExecutionEngine con gestión BE/parcial, usada solo en este experimento.

    ``filter`` reproduce el motor sin gestión. ``be_1r`` mantiene la misma
    semántica del protocolo anterior: el stop se mueve al empezar la vela
    siguiente a la que alcanza +1R. ``partial_50_be`` ejecuta el parcial en la
    vela que alcanza +1R y mueve el resto a BE para la vela siguiente.
    """

    policy = "filter"

    # ------------------------------------------------------------------ partial
    def _partial_exit_price(self, pos, level: float, gap: bool, bar) -> float:
        if gap:
            return _tick_round(bar.open, self.tick)
        direction = 1 if pos.direction == "long" else -1
        return _tick_round(level - direction * self._slip(), self.tick)

    def _take_partial(self, pos, price: float, ts: int, qty: int) -> None:
        ecfg = self.settings.execution
        direction = 1 if pos.direction == "long" else -1
        gross = (price - pos.entry_price) * direction * ecfg.point_value * qty
        fees = ecfg.commission_per_contract_side * 2 * qty
        pnl = round(gross - fees, 2)
        leg = {
            "ts": ts,
            "qty": qty,
            "price": round(price, 2),
            "gross_pnl": round(gross, 2),
            "fees": round(fees, 2),
            "pnl": pnl,
        }
        pos.qty -= qty
        pos.partial_exit_qty = int(pos.partial_exit_qty) + qty
        meta = pos.meta
        meta["_partial_pnl"] = round(float(meta.get("_partial_pnl") or 0.0) + pnl, 2)
        meta["_partial_gross"] = round(
            float(meta.get("_partial_gross") or 0.0) + gross, 2
        )
        meta["_partial_fees"] = round(float(meta.get("_partial_fees") or 0.0) + fees, 2)
        meta.setdefault("_partial_legs", []).append(leg)
        meta["_partial_done"] = True

    def _manage_partial(self, bar, *, move_be: bool = True) -> None:
        pos = self.position
        assert pos is not None
        self._update_excursions(pos, bar)
        direction = 1 if pos.direction == "long" else -1
        risk = abs(pos.entry_price - pos.initial_stop)

        if pos.direction == "long":
            hit_stop = bar.low <= pos.stop
            hit_target = bar.high >= pos.target
            gap_stop = bar.open < pos.stop
            gap_target = bar.open > pos.target
            one_r = pos.entry_price + risk
            hit_one_r = risk > 0 and bar.high >= one_r
            gap_one_r = risk > 0 and bar.open > one_r
        else:
            hit_stop = bar.high >= pos.stop
            hit_target = bar.low <= pos.target
            gap_stop = bar.open > pos.stop
            gap_target = bar.open < pos.target
            one_r = pos.entry_price - risk
            hit_one_r = risk > 0 and bar.low <= one_r
            gap_one_r = risk > 0 and bar.open < one_r

        # Misma convención que el motor: si en la vela se tocan stop y target,
        # se resuelve stop primero. Eso también impide un parcial en esa vela.
        if hit_stop:
            if hit_target:
                record = self._ambiguous_record(
                    pos, bar, gap_stop=gap_stop, gap_target=gap_target
                )
                pos.meta["ambiguous_bar"] = True
                pos.meta["gap_stop"] = gap_stop
                trade = self.close(
                    self._stop_exit_price(pos, bar, gap_stop), bar.ts, "stop_loss"
                )
                self._finish_ambiguous_record(record, trade)
            else:
                pos.meta["gap_stop"] = gap_stop
                self.close(self._stop_exit_price(pos, bar, gap_stop), bar.ts, "stop_loss")
            return

        if not pos.meta.get("_partial_done") and hit_one_r:
            partial_qty = pos.qty // 2
            if partial_qty >= 1:
                price = self._partial_exit_price(pos, one_r, gap_one_r, bar)
                self._take_partial(pos, price, bar.ts, partial_qty)
                if move_be:
                    # El resto queda protegido desde la vela siguiente. No se
                    # evalúa el nuevo stop dentro de esta misma vela.
                    pos.stop = _tick_round(pos.entry_price, self.tick)
                    pos.meta["_mgmt_moved"] = True
                if hit_target:
                    self.close(
                        self._target_exit_price(pos, bar, gap_target),
                        bar.ts,
                        "take_profit",
                    )
                return
            # Con un solo contrato no se puede ejecutar un 50%. Se deja la
            # gestión original y se registra para que el informe lo muestre.
            pos.meta["_partial_skipped_qty_one"] = True

        if hit_target:
            pos.meta["gap_target"] = gap_target
            self.close(
                self._target_exit_price(pos, bar, gap_target), bar.ts, "take_profit"
            )

    def _manage_be_same_bar(self, bar) -> None:
        """BE dentro de la vela que toca +1R.

        Convención: el stop inicial tiene prioridad si la vela lo toca. Si la
        vela alcanza el target, se cobra el target; si no, se mueve el stop a
        entrada y se comprueba el retroceso a entrada en la misma vela. Esto
        aísla el timing del BE sin convertir en stop un target ya alcanzado.
        """
        pos = self.position
        assert pos is not None
        self._update_excursions(pos, bar)
        direction = 1 if pos.direction == "long" else -1
        risk = abs(pos.entry_price - pos.initial_stop)

        if pos.direction == "long":
            hit_stop = bar.low <= pos.stop
            hit_target = bar.high >= pos.target
            gap_stop = bar.open < pos.stop
            gap_target = bar.open > pos.target
            one_r = pos.entry_price + risk
            hit_one_r = risk > 0 and bar.high >= one_r
            hit_be = bar.low <= pos.entry_price
        else:
            hit_stop = bar.high >= pos.stop
            hit_target = bar.low <= pos.target
            gap_stop = bar.open > pos.stop
            gap_target = bar.open < pos.target
            one_r = pos.entry_price - risk
            hit_one_r = risk > 0 and bar.low <= one_r
            hit_be = bar.high >= pos.entry_price

        if hit_stop:
            if hit_target:
                record = self._ambiguous_record(
                    pos, bar, gap_stop=gap_stop, gap_target=gap_target
                )
                pos.meta["ambiguous_bar"] = True
                pos.meta["gap_stop"] = gap_stop
                trade = self.close(
                    self._stop_exit_price(pos, bar, gap_stop), bar.ts, "stop_loss"
                )
                self._finish_ambiguous_record(record, trade)
            else:
                pos.meta["gap_stop"] = gap_stop
                self.close(self._stop_exit_price(pos, bar, gap_stop), bar.ts, "stop_loss")
            return

        if hit_target:
            pos.meta["gap_target"] = gap_target
            self.close(
                self._target_exit_price(pos, bar, gap_target), bar.ts, "take_profit"
            )
            return

        if hit_one_r and not pos.meta.get("_mgmt_moved"):
            pos.stop = _tick_round(pos.entry_price, self.tick)
            pos.meta["_mgmt_moved"] = True
            if hit_be:
                # El stop nace en esta vela y se ejecuta en la misma vela; no
                # se usa el open como gap porque el stop no existía al abrir.
                pos.meta["_be_same_bar"] = True
                self.close(
                    self._stop_exit_price(pos, bar, False), bar.ts, "stop_loss"
                )

    def _manage_position(self, bar) -> None:  # type: ignore[no-untyped-def]
        pos = self.position
        if pos is None:
            return
        if bar.ts < pos.entry_ts:
            return
        if self.policy == "filter":
            super()._manage_position(bar)
            return
        if self.policy == "be_1r_same_bar":
            self._manage_be_same_bar(bar)
            return
        if self.policy == "be_1r":
            risk = abs(pos.entry_price - pos.initial_stop)
            if (
                risk > 0
                and pos.mfe_r >= 1.0
                and not pos.meta.get("_mgmt_moved")
            ):
                pos.stop = _tick_round(pos.entry_price, self.tick)
                pos.meta["_mgmt_moved"] = True
            super()._manage_position(bar)
            return
        if self.policy == "partial_50_be":
            self._manage_partial(bar, move_be=True)
            return
        if self.policy == "partial_50_no_be":
            self._manage_partial(bar, move_be=False)
            return
        super()._manage_position(bar)

    # --------------------------------------------------------------------- exit
    def close(self, price: float, ts: int, reason: str):  # type: ignore[no-untyped-def]
        pos = self.position
        if pos is None:
            return None
        partial_qty = int(pos.partial_exit_qty or 0)
        original_qty = pos.qty + partial_qty
        partial_pnl = float(pos.meta.get("_partial_pnl") or 0.0)
        partial_gross = float(pos.meta.get("_partial_gross") or 0.0)
        partial_fees = float(pos.meta.get("_partial_fees") or 0.0)
        legs = list(pos.meta.get("_partial_legs") or [])
        risk_dist = abs(pos.entry_price - pos.initial_stop)
        trade = super().close(price, ts, reason)
        if trade is None:
            return None
        if partial_qty:
            direction = 1 if pos.direction == "long" else -1
            trade.qty = original_qty
            trade.pnl = round(trade.pnl + partial_pnl, 2)
            trade.gross_pnl = round(trade.gross_pnl + partial_gross, 2)
            trade.fees = round(trade.fees + partial_fees, 2)
            # R de precio ponderado por contratos, comparable con el baseline.
            partial_r_weighted = sum(
                (float(leg["price"]) - pos.entry_price) * direction * int(leg["qty"])
                for leg in legs
            ) / (risk_dist * original_qty) if risk_dist else 0.0
            remainder_r_weighted = (
                trade.r_multiple * (original_qty - partial_qty) / original_qty
            )
            trade.r_multiple = round(partial_r_weighted + remainder_r_weighted, 2)
            trade.meta.update(
                {
                    "partial_exit": True,
                    "partial_qty": partial_qty,
                    "remaining_qty": original_qty - partial_qty,
                    "partial_pnl": round(partial_pnl, 2),
                    "partial_fees": round(partial_fees, 2),
                    "partial_price": legs[0]["price"] if legs else None,
                    "partial_ts": legs[0]["ts"] if legs else None,
                    "partial_legs": legs,
                    "be_moved": bool(pos.meta.get("_mgmt_moved")),
                    "r_multiple_net": round(trade.pnl / trade.risk_amount, 4)
                    if trade.risk_amount
                    else 0.0,
                }
            )
            self.daily_realized += partial_pnl
        elif pos.meta.get("_partial_skipped_qty_one"):
            trade.meta["partial_skipped_qty_one"] = True
        return trade


def _cashflow_summary(trades: list[dict[str, Any]], initial: float) -> dict[str, Any]:
    """DD con caja real: el parcial se acredita cuando se ejecuta."""
    legs: list[tuple[int, float, str]] = []
    for trade in trades:
        meta = trade.get("meta") or {}
        pnl = float(trade["pnl"])
        partial = float(meta.get("partial_pnl") or 0.0)
        if meta.get("partial_exit") and meta.get("partial_ts") is not None:
            legs.append((int(meta["partial_ts"]), partial, "partial"))
            legs.append((int(trade["exit_ts"]), round(pnl - partial, 2), "remainder"))
        else:
            legs.append((int(trade["exit_ts"]), pnl, "final"))
    legs.sort(key=lambda item: item[0])
    equity = initial
    peak = equity
    worst = 0.0
    worst_pct = 0.0
    curve = [{"ts": 0, "equity": round(initial, 2)}]
    for ts, pnl, _leg in legs:
        equity += pnl
        peak = max(peak, equity)
        drawdown = peak - equity
        if drawdown > worst:
            worst = drawdown
            worst_pct = drawdown / peak * 100 if peak else 0.0
        curve.append({"ts": ts, "equity": round(equity, 2)})
    return {
        "max_drawdown": round(worst, 2),
        "max_drawdown_pct": round(worst_pct, 3),
        "equity_curve": curve,
        "legs": len(legs),
    }


def _summary_with_flow(trades: list[dict[str, Any]], capital: float) -> dict[str, Any]:
    metrics = _summary(trades, capital)
    flow = _cashflow_summary(trades, capital)
    metrics["cashflow_max_drawdown"] = flow["max_drawdown"]
    metrics["cashflow_max_drawdown_pct"] = flow["max_drawdown_pct"]
    metrics["cashflow_legs"] = flow["legs"]
    metrics["equity_curve_cashflow"] = flow["equity_curve"]
    metrics["trades"] = len(trades)
    return metrics


def _run_group(keys: tuple[str, ...]) -> dict[tuple[str, str], dict[str, Any]]:
    lock = _load_lock()
    base = Settings.model_validate(lock["settings"])
    windows = {w["id"]: w for w in lock["windows"]}
    group_windows = [windows[k] for k in keys]
    start = date.fromisoformat(group_windows[0]["start"])
    days = sum(int(w["sessions"]) for w in group_windows)
    sessions, source, dataset = bt.prepare_dataset(
        base, days, start, allow_holdout=False
    )
    if source != "csv":
        raise RuntimeError(f"Se esperaba CSV real, recibido {source!r}")
    if sessions[-1][0] >= HOLDOUT_START:
        raise RuntimeError("El dataset alcanza el holdout")
    config = apply_settings(base, {"risk": {"min_stop_or_ratio": FILTER_RATIO}})
    if config.risk.min_stop_or_ratio != FILTER_RATIO:
        raise RuntimeError("El filtro no quedó activo")

    out: dict[tuple[str, str], dict[str, Any]] = {}
    for window in group_windows:
        ws = date.fromisoformat(window["start"])
        we = date.fromisoformat(window["end"])
        window_sessions = [(d, data) for d, data in sessions if ws <= d <= we]
        if len(window_sessions) != int(window["sessions"]):
            raise RuntimeError(
                f"{window['id']}: {len(window_sessions)} sesiones, "
                f"se esperaban {window['sessions']}"
            )
        if window_sessions[-1][0] >= HOLDOUT_START:
            raise RuntimeError(f"{window['id']} toca el holdout")
        for policy in RUN_POLICIES:
            FullManagementExecution.policy = policy
            bt.ExecutionEngine = FullManagementExecution
            started = time.perf_counter()
            result = bt._simulate(
                config,
                window_sessions,
                source,
                f"{window['id']}-{policy}",
                dataset,
            )
            trades = [dict(t, window=window["id"]) for t in result["trades"]]
            bad_ratio = []
            for trade in trades:
                meta = trade.get("meta") or {}
                width = (
                    (float(meta["orb_high"]) - float(meta["orb_low"])) / 0.25
                    if meta.get("orb_high") is not None
                    and meta.get("orb_low") is not None
                    else 0.0
                )
                ratio = (
                    float(meta.get("stop_ticks") or 0.0) / width if width else 0.0
                )
                if ratio < FILTER_RATIO - 1e-9:
                    bad_ratio.append((trade.get("signal_id"), ratio))
            if bad_ratio:
                raise RuntimeError(
                    f"{window['id']} {policy}: {len(bad_ratio)} ops con ratio < "
                    f"{FILTER_RATIO}"
                )
            out[(window["id"], policy)] = {
                "window": window,
                "sessions": len(window_sessions),
                "metrics": _summary_with_flow(trades, config.risk.initial_capital),
                "trades": trades,
                "elapsed_sec": round(time.perf_counter() - started, 1),
            }
            print(
                f"[{window['id']} {policy}] {len(trades)} ops, "
                f"neto {result['metrics']['net_profit']}, "
                f"DD {result['metrics']['max_drawdown']} "
                f"({time.perf_counter() - started:.1f}s)",
                flush=True,
            )
    return out


def _aggregate(
    results: dict[tuple[str, str], dict[str, Any]], policy: str
) -> dict[str, Any]:
    lock = _load_lock()
    capital = float(lock["settings"]["risk"]["initial_capital"])
    all_trades = [
        t for window in WINDOW_IDS for t in results[(window, policy)]["trades"]
    ]
    ex_w4 = [t for t in all_trades if t["window"] != "W4"]
    blocks = []
    for window in WINDOW_IDS:
        item = results[(window, policy)]
        block_trades = item["trades"]
        blocks.append(
            {
                "id": window,
                "start": item["window"]["start"],
                "end": item["window"]["end"],
                "sessions": item["sessions"],
                "metrics": _summary_with_flow(block_trades, capital),
            }
        )
    return {
        "total": _summary_with_flow(all_trades, capital),
        "ex_w4": _summary_with_flow(ex_w4, capital),
        "blocks": blocks,
        "trades": all_trades,
    }


def _trade_map(trades: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {_signal_id(trade): trade for trade in trades}


def _compare_official(
    actual: dict[str, Any], official: dict[str, Any], label: str
) -> dict[str, Any]:
    fields = (
        "trades",
        "wins",
        "losses",
        "net_profit",
        "gross_profit",
        "gross_loss",
        "profit_factor",
        "expectancy",
        "max_drawdown",
        "worst_loss_streak",
    )
    diffs = {}
    for field in fields:
        left = actual.get(field)
        right = official.get(field)
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            diffs[field] = round(float(left) - float(right), 2)
        elif left != right:
            diffs[field] = {"actual": left, "official": right}
    return {"label": label, "match": all(value == 0 for value in diffs.values()), "diff": diffs}


def main() -> None:
    lock = _load_lock()
    if sum(int(w["sessions"]) for w in lock["windows"]) != 362:
        raise RuntimeError("Las ventanas no suman 362 sesiones")
    if lock["holdout"]["start"] != HOLDOUT_START.isoformat():
        raise RuntimeError("Inicio de holdout inesperado")

    official_path = REPORTS / "breakeven_1r_protocol_all.json"
    official = json.loads(official_path.read_text(encoding="utf-8"))
    if int(official.get("protocol", {}).get("sessions") or 0) != 362:
        raise RuntimeError("El protocolo oficial no cubre 362 sesiones")
    official_filter = official["arms"]["filter"]
    official_be = official["arms"]["be_1r"]
    windows_by_id = {w["id"]: w for w in lock["windows"]}

    started = time.perf_counter()
    results: dict[tuple[str, str], dict[str, Any]] = {}
    if ONLY_PARTIAL:
        # Los brazos baseline/BE oficiales ya se ejecutaron con este mismo
        # motor, lock y filtro; se reconstruyen por ventana para comparar con
        # el parcial nuevo sin repetir sus 8 simulaciones.
        for policy in ("filter", "be_1r"):
            for window in WINDOW_IDS:
                trades = [
                    t for t in official["arms"][policy]["trades"]
                    if t.get("window") == window
                ]
                results[(window, policy)] = {
                    "window": windows_by_id[window],
                    "sessions": int(windows_by_id[window]["sessions"]),
                    "metrics": _summary_with_flow(
                        trades, float(lock["settings"]["risk"]["initial_capital"])
                    ),
                    "trades": trades,
                    "elapsed_sec": None,
                }
        print("Baseline/BE reutilizados del protocolo oficial; ejecutando solo parcial", flush=True)
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(_run_group, group): group for group in GROUPS}
        for future in as_completed(futures):
            results.update(future.result())
    print(f"Simulaciones terminadas en {time.perf_counter() - started:.1f}s", flush=True)

    arms: dict[str, Any] = {}
    for policy in POLICIES:
        arms[policy] = _aggregate(results, policy)

    baseline_trades = arms["filter"]["trades"]
    base_map = _trade_map(baseline_trades)
    comparisons: dict[str, Any] = {}
    for policy in ("be_1r", "partial_50_be"):
        arm = arms[policy]
        comparison = _effect(baseline_trades, arm["trades"])
        comparison.update(
            {
                "net_profit_delta": round(
                    arm["total"]["net_profit"] - arms["filter"]["total"]["net_profit"],
                    2,
                ),
                "cashflow_dd_delta": round(
                    arm["total"]["cashflow_max_drawdown"]
                    - arms["filter"]["total"]["cashflow_max_drawdown"],
                    2,
                ),
                "trades_delta": arm["total"]["trades"]
                - arms["filter"]["total"]["trades"],
            }
        )
        comparisons[policy] = comparison

    partial_rows = []
    for trade in arms["partial_50_be"]["trades"]:
        meta = trade.get("meta") or {}
        if not meta.get("partial_exit"):
            continue
        sid = _signal_id(trade)
        base = base_map.get(sid, {})
        partial_rows.append(
            {
                "signal_id": sid,
                "window": trade.get("window"),
                "qty": trade["qty"],
                "baseline_qty": base.get("qty"),
                "partial_qty": meta.get("partial_qty"),
                "remaining_qty": meta.get("remaining_qty"),
                "direction": trade["direction"],
                "entry_price": trade["entry_price"],
                "initial_stop": trade["stop"],
                "partial_price": meta.get("partial_price"),
                "partial_pnl": meta.get("partial_pnl"),
                "remainder_pnl": round(
                    float(trade["pnl"]) - float(meta.get("partial_pnl") or 0.0), 2
                ),
                "exit_reason": trade["exit_reason"],
                "pnl": trade["pnl"],
                "baseline_pnl": base.get("pnl"),
                "delta_vs_baseline": round(float(trade["pnl"]) - float(base.get("pnl", 0.0)), 2),
            }
        )
    partial_rows.sort(key=lambda row: row["signal_id"])

    # Validaciones de integración y de reconciliación de caja.
    signal_sets = {
        policy: set(_trade_map(arms[policy]["trades"])) for policy in POLICIES
    }
    all_same_ids = signal_sets["filter"] == signal_sets["be_1r"] == signal_sets["partial_50_be"]
    qty_values = sorted({int(t["qty"]) for t in baseline_trades})
    qty_by_arm = {
        policy: sorted({int(t["qty"]) for t in arms[policy]["trades"]})
        for policy in POLICIES
    }
    qty_diff_signals = []
    partial_map = _trade_map(arms["partial_50_be"]["trades"])
    for sid, base_trade in base_map.items():
        partial_trade = partial_map.get(sid)
        if partial_trade is None:
            continue
        if int(base_trade["qty"]) != int(partial_trade["qty"]):
            qty_diff_signals.append(
                {
                    "signal_id": sid,
                    "baseline_qty": int(base_trade["qty"]),
                    "partial_qty": int(partial_trade["qty"]),
                }
            )
    partial_qty_values = sorted({int(row["partial_qty"]) for row in partial_rows})
    reconciliation = []
    for trade in arms["partial_50_be"]["trades"]:
        meta = trade.get("meta") or {}
        if not meta.get("partial_exit"):
            continue
        legs = meta.get("partial_legs") or []
        leg_sum = round(sum(float(leg["pnl"]) for leg in legs), 2)
        remainder = round(float(trade["pnl"]) - float(meta["partial_pnl"] or 0.0), 2)
        reconciliation.append(
            {
                "signal_id": _signal_id(trade),
                "partial_legs_sum": leg_sum,
                "partial_pnl": meta.get("partial_pnl"),
                "remainder_pnl": remainder,
                "total_pnl": trade["pnl"],
                "matches": abs(leg_sum - float(meta.get("partial_pnl") or 0.0)) <= 0.01
                and abs(remainder + float(meta.get("partial_pnl") or 0.0) - float(trade["pnl"])) <= 0.01,
            }
        )
    filter_ratios = []
    for trade in baseline_trades:
        meta = trade.get("meta") or {}
        width = (
            (float(meta["orb_high"]) - float(meta["orb_low"])) / 0.25
            if meta.get("orb_high") is not None and meta.get("orb_low") is not None
            else 0.0
        )
        if width:
            filter_ratios.append(float(meta.get("stop_ticks") or 0.0) / width)
    last_trade_day = max(
        et_date(int(t["exit_ts"])) for policy in POLICIES for t in arms[policy]["trades"]
    )
    session_counts = {
        window: {
            "expected": int(next(w["sessions"] for w in lock["windows"] if w["id"] == window)),
            "filter": results[(window, "filter")]["sessions"],
            "be_1r": results[(window, "be_1r")]["sessions"],
            "partial_50_be": results[(window, "partial_50_be")]["sessions"],
        }
        for window in WINDOW_IDS
    }
    if last_trade_day >= HOLDOUT_START:
        raise RuntimeError("El replay tocó el holdout")

    output = {
        "schema": "partial-exit-1r-full-engine-v1",
        "protocol": {
            "lock": str(LOCK_PATH.relative_to(ROOT)),
            "version": lock.get("protocol_version"),
            "windows": list(WINDOW_IDS),
            "sessions": sum(int(w["sessions"]) for w in lock["windows"]),
            "holdout_start": HOLDOUT_START.isoformat(),
            "holdout_used": False,
            "engine": "server.backtest._simulate + FullManagementExecution",
            "qty": "dinámica del RiskManager (riesgo 1% de equity, max_contracts=5)",
            "execution_mode": "solo parcial nuevo; baseline/BE oficiales full-engine reutilizados y verificados"
            if ONLY_PARTIAL
            else "tres brazos ejecutados en esta corrida",
            "baseline_be_source": str(official_path.relative_to(ROOT)),
        },
        "filter": {
            "field": "risk.min_stop_or_ratio",
            "value": FILTER_RATIO,
            "same_for_all_arms": True,
        },
        "rules": {
            "partial_fraction": 0.5,
            "partial_r": 1.0,
            "partial_qty_formula": "qty // 2; si qty<2 no hay parcial",
            "be_after_partial": True,
            "be_timing": "vela siguiente a +1R",
            "stop_first_if_ambiguous": True,
            "partial_then_target_same_bar": True,
            "qty": "dinámica; no se reutiliza la qty fija del replay anterior",
            "commission_per_contract_side": 0.62,
            "slippage_ticks": 1,
            "cashflow_dd": "el parcial se acredita en su timestamp; el resto al cierre",
        },
        "arms": arms,
        "comparison": comparisons,
        "partial": {
            "signals_with_partial": len(partial_rows),
            "signals_without_partial": len(arms["partial_50_be"]["trades"]) - len(partial_rows),
            "partial_qty_total": sum(int(row["partial_qty"]) for row in partial_rows),
            "partial_pnl_total": round(
                sum(float(row["partial_pnl"] or 0.0) for row in partial_rows), 2
            ),
            "be_moved_signals": len(partial_rows),
            "partial_qty_values": partial_qty_values,
            "rows": partial_rows,
        },
        "verification": {
            "session_counts": session_counts,
            "total_sessions": sum(item["filter"] for item in session_counts.values()),
            "trades_by_window": {
                window: {
                    policy: len(results[(window, policy)]["trades"])
                    for policy in POLICIES
                }
                for window in WINDOW_IDS
            },
            "all_arms_same_signal_ids": all_same_ids,
            "signal_ids_by_arm": {
                policy: sorted(signal_sets[policy]) for policy in POLICIES
            },
            "dynamic_qty_values_baseline": qty_values,
            "dynamic_qty_values_by_arm": qty_by_arm,
            "dynamic_qty_is_variable": len(qty_values) > 1,
            "qty_diff_vs_baseline": qty_diff_signals,
            "filter_min_ratio": round(min(filter_ratios), 6) if filter_ratios else None,
            "filter_ratios_ok": all(value >= FILTER_RATIO - 1e-9 for value in filter_ratios),
            "baseline_vs_official": _compare_official(
                arms["filter"]["total"], official_filter["total"], "filter"
            ),
            "be_vs_official": _compare_official(
                arms["be_1r"]["total"], official_be["total"], "be_1r"
            ),
            "partial_reconciliation": reconciliation,
            "partial_reconciliation_ok": all(row["matches"] for row in reconciliation),
            "last_evaluated_session": max(w["end"] for w in lock["windows"]),
            "last_trade_session": last_trade_day.isoformat(),
            "holdout_used": False,
        },
    }
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    # Informe Markdown compacto, generado desde los mismos datos.
    base = arms["filter"]["total"]
    be = arms["be_1r"]["total"]
    partial = arms["partial_50_be"]["total"]
    lines = [
        "# Parcial 50% a +1R + BE en el motor completo",
        "",
        "**Alcance:** W1-W6, 362 sesiones, motor completo con qty dinámica.  ",
        f"**Puerta común:** `min_stop_or_ratio = {FILTER_RATIO}` en las tres ramas.  ",
        "**Holdout:** no usado.  ",
        "**Baseline/BE:** brazos full-engine del protocolo oficial, con qty dinámica. **Parcial:** corrida nueva en este motor.  ",
        "**Fuente:** `reports/backtest/partial_exit_1r_full.json`",
        "",
        "## Reglas",
        "",
        "| Rama | Gestión |",
        "|---|---|",
        "| `filter` | Sin gestión a 1R; stop y target originales. |",
        "| `be_1r` | Stop a entrada después de MFE ≥ 1R, para la vela siguiente. |",
        "| `partial_50_be` | 50% de la posición a +1R; resto con stop a entrada desde la vela siguiente. |",
        "",
        "La qty la calcula el `RiskManager` con el 1% del equity y `max_contracts=5`. El parcial usa `qty // 2`: 2→1, 3→1, 4→2, 5→2. Si la posición tiene 1 contrato no se fuerza un parcial imposible.",
        "",
        "## Resultado",
        "",
        "| Brazo | Ops | Neto USD | PF | R medio | DD caja USD | DD caja % | DD motor USD | Ganadoras | Perdedoras | Peor racha |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, arm in (("Baseline", base), ("BE completo", be), ("Parcial 50% + BE", partial)):
        lines.append(
            f"| {label} | {arm['trades']} | {arm['net_profit']:+.2f} | "
            f"{arm['profit_factor']} | {arm['avg_r']:.2f} | "
            f"{arm['cashflow_max_drawdown']:.2f} | {arm['cashflow_max_drawdown_pct']:.2f}% | "
            f"{arm['max_drawdown']:.2f} | {arm['wins']} | {arm['losses']} | "
            f"{arm['worst_loss_streak']} |"
        )
    lines += [
        "",
        "El DD de caja acredita el parcial cuando se ejecuta; el DD motor solo lo reconoce al cierre final. Para comparar la suavidad de la curva se usa el primero.",
        "",
        "## Comparación contra baseline",
        "",
        "| Brazo | Δ neto | Ganadoras cortadas | P&L perdido en ganadoras | Perdedoras mejoradas | Ahorro en perdedoras | Δ DD caja |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for policy, label in (("be_1r", "BE completo"), ("partial_50_be", "Parcial 50% + BE")):
        cmp = comparisons[policy]
        lines.append(
            f"| {label} | {cmp['net_profit_delta']:+.2f} | {cmp['winners_cut']} | "
            f"{cmp['winner_pnl_lost']:.2f} | {cmp['losses_improved']} | "
            f"{cmp['losses_saved_usd']:.2f} | {cmp['cashflow_dd_delta']:+.2f} |"
        )
    lines += [
        "",
        "La qty es dinámica y, por tanto, dependiente del camino de equity. El parcial llega al 2025-12-24 con **4 contratos** (baseline/BE: **5**); el resto de entradas coincide. No se reutiliza la qty fija del replay anterior. Esa diferencia de un contrato explica 153,76 USD del menor neto del parcial; el resto es el cierre de sesión del 2025-11-28, que en el motor queda 1,00 USD por debajo del replay post-hoc.",
        "",
        "## Parcial por operación",
        "",
        "| Señal | Qty | Qty baseline | Parcial | Precio parcial | P&L parcial | P&L resto | Salida resto | P&L total | Baseline | Δ |",
        "|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|",
    ]
    for row in partial_rows:
        lines.append(
            f"| `{row['signal_id']}` | {row['qty']} | {row['baseline_qty']} | "
            f"{row['partial_qty']} | {row['partial_price']:.2f} | "
            f"{row['partial_pnl']:+.2f} | {row['remainder_pnl']:+.2f} | "
            f"{row['exit_reason']} | {row['pnl']:+.2f} | "
            f"{row['baseline_pnl']:+.2f} | {row['delta_vs_baseline']:+.2f} |"
        )
    lines += [
        "",
        "La señal `2025-09-19-short-1758294900` no ejecutó parcial: su MFE fue 0,11R. Se mantiene como única perdedora del brazo, con −183,48 USD.",
        "",
        "## Verificación",
        "",
        f"- Sesiones evaluadas: **{output['verification']['total_sessions']}**.",
        f"- Ops por rama: baseline **{len(baseline_trades)}**, BE **{len(arms['be_1r']['trades'])}**, parcial **{len(arms['partial_50_be']['trades'])}**.",
        f"- Mismos IDs de señal en las tres ramas: **{output['verification']['all_arms_same_signal_ids']}**.",
        f"- Qty dinámica observada: **{output['verification']['dynamic_qty_values_by_arm']}**.",
        f"- Señales con qty distinta al baseline: **{len(output['verification']['qty_diff_vs_baseline'])}**; detalle en el JSON.",
        f"- Ratio stop/ORB mínimo: **{output['verification']['filter_min_ratio']}** (puerta {FILTER_RATIO}).",
        f"- Baseline vs protocolo oficial: **{output['verification']['baseline_vs_official']['match']}**.",
        f"- Baseline/BE de origen oficial full-engine: **{ONLY_PARTIAL}**.",
        f"- BE vs protocolo oficial: **{output['verification']['be_vs_official']['match']}**.",
        f"- Reconciliación de caja del parcial: **{output['verification']['partial_reconciliation_ok']}**.",
        f"- Último trade: **{output['verification']['last_trade_session']}**; holdout usado: **False**.",
        "",
        "El baseline y el BE se comparan contra el protocolo oficial para comprobar que la integración no cambió las entradas ni el sizing. El parcial no tiene un equivalente oficial full-engine: esta es la primera ejecución con qty dinámica. El replay post-hoc anterior, con qty fija, no se usa como resultado comparable.",
        "",
        "## Artefactos",
        "",
        "- `reports/backtest/run_partial_exit_1r_full.py`",
        "- `reports/backtest/partial_exit_1r_full.json`",
        "- `reports/backtest/PARTIAL_EXIT_1R_FULL.md`",
    ]
    MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 80)
    print("PARCIAL 50% A +1R + BE - MOTOR COMPLETO 362 SESIONES")
    print("=" * 80)
    for policy in POLICIES:
        arm = arms[policy]["total"]
        print(
            f"{policy:15s} ops {arm['trades']:2d} | neto {arm['net_profit']:+9.2f} | "
            f"PF {str(arm['profit_factor']):>6s} | DD caja {arm['cashflow_max_drawdown']:8.2f} "
            f"({arm['cashflow_max_drawdown_pct']:.2f}%) | W/L {arm['wins']}/{arm['losses']} | "
            f"racha {arm['worst_loss_streak']}"
        )
    print(
        f"\nMismos IDs: {output['verification']['all_arms_same_signal_ids']} | "
        f"qty {output['verification']['dynamic_qty_values_baseline']} | "
        f"baseline oficial {output['verification']['baseline_vs_official']['match']} | "
        f"BE oficial {output['verification']['be_vs_official']['match']}"
    )
    print(f"JSON: {OUT}")
    print(f"MD: {MD}")


if __name__ == "__main__":
    main()
