"""Walk-forward de presets dentro de W1-W6, sin holdout.

Selecciona un preset usando solo las ventanas de entrenamiento y lo evalúa en
la ventana siguiente. La fuente es ``presets_default_dev.json``: cada bloque se
ejecutó con capital inicial de 25.000 USD, por lo que los P&L de bloque son
comparables y no dependen de la trayectoria de otro preset.

Regla pre-registrada:
- Entrenamiento expansivo: W1..Wt; test: W(t+1), para t=1..5.
- Elegible: >= 5 operaciones en entrenamiento y neto de entrenamiento > 0.
- Score: neto / max(peor DD de bloque, 1 USD).
- Desempate: mayor neto, menor peor DD, nombre.
- Si no hay elegible, cash (retorno 0).
- La ventana de test no participa en la selección.

No ejecuta backtests, no abre el holdout y no modifica la configuración activa.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "reports/backtest/presets_default_dev.json"
DEFAULT_JSON = ROOT / "reports/backtest/walk_forward_presets.json"
DEFAULT_CSV = ROOT / "reports/backtest/walk_forward_presets.csv"
SCHEMA = "preset-walk-forward-v1"
INITIAL_CAPITAL = 25_000.0
MIN_TRAIN_TRADES = 5
CASH = "cash"


def _num(value: float | None) -> float | str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isinf(value):
        return "inf" if value > 0 else "-inf"
    return round(float(value), 4)


def _profit_factor(rows: list[dict[str, Any]]) -> float | None:
    gross_profit = sum(float(row["gross_profit"]) for row in rows)
    gross_loss = -sum(float(row["gross_loss"]) for row in rows)
    if gross_loss > 0:
        return gross_profit / gross_loss
    if gross_profit > 0:
        return math.inf
    return None


def _compound(returns: list[float]) -> tuple[float, float]:
    """Retorno compuesto y DD de los puntos de bloque, no intradía."""
    equity = INITIAL_CAPITAL
    peak = INITIAL_CAPITAL
    worst_dd = 0.0
    for value in returns:
        equity *= 1.0 + value
        peak = max(peak, equity)
        worst_dd = max(worst_dd, peak - equity)
    return equity, worst_dd


def _summarise(
    rows: list[dict[str, Any]],
    label: str,
    returns: list[float] | None = None,
) -> dict[str, Any]:
    returns = returns if returns is not None else [
        float(row["net_profit"]) / INITIAL_CAPITAL for row in rows
    ]
    final_equity, boundary_dd = _compound(returns)
    return {
        "label": label,
        "tests": len(rows),
        "positive_tests": sum(1 for row in rows if float(row["net_profit"]) > 0),
        "trades": sum(int(row["trades"]) for row in rows),
        "net_profit": round(sum(float(row["net_profit"]) for row in rows), 2),
        "profit_factor": _num(_profit_factor(rows)),
        "worst_test_dd": round(max((float(row["max_drawdown"]) for row in rows), default=0.0), 2),
        "boundary_dd": round(boundary_dd, 2),
        "compounded_return_pct": round((final_equity / INITIAL_CAPITAL - 1.0) * 100, 3),
        "final_equity": round(final_equity, 2),
    }


def _select(
    train_rows: list[dict[str, Any]],
    min_train_trades: int = MIN_TRAIN_TRADES,
) -> dict[str, Any] | None:
    """Selecciona solo con las filas de entrenamiento."""
    candidates: list[dict[str, Any]] = []
    for preset, rows in _by_preset(train_rows).items():
        trades = sum(int(row["trades"]) for row in rows)
        net = sum(float(row["net_profit"]) for row in rows)
        worst_dd = max((float(row["max_drawdown"]) for row in rows), default=0.0)
        if trades < min_train_trades or net <= 0:
            continue
        candidates.append(
            {
                "preset": preset,
                "train_trades": trades,
                "train_net": round(net, 2),
                "train_worst_dd": round(worst_dd, 2),
                "score": net / max(worst_dd, 1.0),
                "train_pf": _num(_profit_factor(rows)),
            }
        )
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda item: (
            -item["score"],
            -item["train_net"],
            item["train_worst_dd"],
            item["preset"],
        ),
    )


def _by_preset(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        out.setdefault(str(row["preset"]), []).append(row)
    return out


def build_payload(
    source: dict[str, Any],
    *,
    min_train_trades: int = MIN_TRAIN_TRADES,
    train_window: int | None = None,
) -> dict[str, Any]:
    if source.get("holdout_executed"):
        raise ValueError("La fuente contiene holdout ejecutado; no se procesa")
    windows = source.get("per_window")
    if not windows or [window["window"] for window in windows] != ["W1", "W2", "W3", "W4", "W5", "W6"]:
        raise ValueError("Se esperaban las ventanas W1-W6")
    presets = list(source.get("presets") or [])
    if len(presets) != 11:
        raise ValueError(f"Se esperaban 11 presets, hay {len(presets)}")

    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for window in windows:
        rows = window["rows"]
        if [row["preset"] for row in rows] != presets:
            raise ValueError(f"{window['window']}: presets fuera de orden o incompletos")
        for row in rows:
            by_key[(str(window["window"]), str(row["preset"]))] = row

    folds: list[dict[str, Any]] = []
    selected_rows: list[dict[str, Any]] = []
    baseline_rows: list[dict[str, Any]] = []
    oracle_rows: list[dict[str, Any]] = []
    for index in range(1, len(windows)):
        test_window = str(windows[index]["window"])
        train_windows = [str(window["window"]) for window in windows[:index]]
        if train_window is not None:
            train_windows = train_windows[-train_window:]
        train_rows = [
            by_key[(window, preset)]
            for window in train_windows
            for preset in presets
        ]
        selected = _select(train_rows, min_train_trades)
        selected_name = selected["preset"] if selected else CASH
        test_row = by_key.get((test_window, selected_name))
        baseline = by_key[(test_window, "baseline")]
        oracle = max(
            (by_key[(test_window, preset)] for preset in presets),
            key=lambda row: float(row["net_profit"]),
        )
        if test_row is None:
            # Cash: no hay fila; se representa con cero y DD cero.
            test_row = {
                "preset": CASH,
                "trades": 0,
                "net_profit": 0.0,
                "gross_profit": 0.0,
                "gross_loss": 0.0,
                "max_drawdown": 0.0,
                "profit_factor": None,
            }
        selected_rows.append(test_row)
        baseline_rows.append(baseline)
        oracle_rows.append(oracle)
        folds.append(
            {
                "fold": index,
                "train_windows": train_windows,
                "test_window": test_window,
                "selected": selected_name,
                "selection": selected,
                "test": {
                    "trades": int(test_row["trades"]),
                    "net_profit": round(float(test_row["net_profit"]), 2),
                    "max_drawdown": round(float(test_row["max_drawdown"]), 2),
                    "profit_factor": _num(test_row["profit_factor"]),
                },
                "baseline": {
                    "trades": int(baseline["trades"]),
                    "net_profit": round(float(baseline["net_profit"]), 2),
                    "max_drawdown": round(float(baseline["max_drawdown"]), 2),
                    "profit_factor": _num(baseline["profit_factor"]),
                },
                "oracle": {
                    "preset": str(oracle["preset"]),
                    "net_profit": round(float(oracle["net_profit"]), 2),
                },
                "delta_vs_baseline": round(
                    float(test_row["net_profit"]) - float(baseline["net_profit"]), 2
                ),
            }
        )

    selected_summary = _summarise(selected_rows, "selected")
    baseline_summary = _summarise(baseline_rows, "baseline")
    oracle_summary = _summarise(oracle_rows, "oracle (hindsight)")
    selected_summary["delta_net_vs_baseline"] = round(
        selected_summary["net_profit"] - baseline_summary["net_profit"], 2
    )
    selected_summary["delta_compounded_pct_vs_baseline"] = round(
        selected_summary["compounded_return_pct"]
        - baseline_summary["compounded_return_pct"],
        3,
    )

    return {
        "schema": SCHEMA,
        "source": "reports/backtest/presets_default_dev.json",
        "holdout_executed": bool(source.get("holdout_executed")),
        "scope": "W1-W6 development blocks; no holdout",
        "initial_capital": INITIAL_CAPITAL,
        "selection_rule": {
            "type": (
                "expanding walk-forward"
                if train_window is None
                else f"rolling walk-forward ({train_window} blocks)"
            ),
            "train": "W1..Wt" if train_window is None else f"last {train_window} block(s)",
            "test": "W(t+1)",
            "folds": 5,
            "min_train_trades": min_train_trades,
            "score": "train_net / max(train_worst_block_dd, 1)",
            "require_positive_train_net": True,
            "fallback": CASH,
            "tie_break": "higher train_net, lower train_worst_dd, preset name",
            "test_used_for_selection": False,
        },
        "folds": folds,
        "summary": {
            "selected": selected_summary,
            "baseline": baseline_summary,
            "oracle": oracle_summary,
        },
    }


def _write_folds(path: Path, folds: list[dict[str, Any]]) -> None:
    rows = []
    for fold in folds:
        selection = fold["selection"] or {}
        rows.append(
            {
                "fold": fold["fold"],
                "train_windows": "|".join(fold["train_windows"]),
                "test_window": fold["test_window"],
                "selected": fold["selected"],
                "train_trades": selection.get("train_trades"),
                "train_net": selection.get("train_net"),
                "train_worst_dd": selection.get("train_worst_dd"),
                "train_score": round(selection["score"], 4) if selection else None,
                "test_trades": fold["test"]["trades"],
                "test_net": fold["test"]["net_profit"],
                "test_dd": fold["test"]["max_drawdown"],
                "test_pf": fold["test"]["profit_factor"],
                "baseline_net": fold["baseline"]["net_profit"],
                "baseline_dd": fold["baseline"]["max_drawdown"],
                "baseline_pf": fold["baseline"]["profit_factor"],
                "delta_vs_baseline": fold["delta_vs_baseline"],
                "oracle": fold["oracle"]["preset"],
                "oracle_net": fold["oracle"]["net_profit"],
            }
        )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--json-out", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--csv-out", type=Path, default=DEFAULT_CSV)
    args = parser.parse_args()

    source = json.loads(args.input.read_text(encoding="utf-8"))
    payload = build_payload(source)
    args.json_out.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    _write_folds(args.csv_out, payload["folds"])
    print("fold,train,test,selected,test_net,baseline_net,oracle_net,delta")
    for fold in payload["folds"]:
        print(
            f"{fold['fold']},{'+'.join(fold['train_windows'])},{fold['test_window']},"
            f"{fold['selected']},{fold['test']['net_profit']:.2f},"
            f"{fold['baseline']['net_profit']:.2f},{fold['oracle']['net_profit']:.2f},"
            f"{fold['delta_vs_baseline']:.2f}"
        )
    print("summary")
    for key, value in payload["summary"].items():
        print(key, value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
