"""Calculo del desarrollo W1-W6 contra las puertas del protocolo v1.2.

Solo desarrollo: no carga ni inspecciona el holdout. Genera los artefactos de
reports/backtest/ a partir de los JSON crudos de cada bloque.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.confirmatory import compute_code_hash, settings_sha256, sha256_file
from server.config import Settings
from server.stats import compute_stats
from server.timeutil import et_date

OUT = ROOT / "reports/backtest"
LOCK = json.loads((ROOT / "docs/protocolo_backtest.lock.json").read_text(encoding="utf-8"))
ACC = LOCK["acceptance"]
SETTINGS = Settings.model_validate(LOCK["settings"])
BOOTSTRAP_SEED = int(LOCK["bootstrap"]["seed"])
BOOTSTRAP_RUNS = int(LOCK["bootstrap"]["resamples"])


def full(result: list[dict]) -> dict:
    return next(r for r in result if r["variant"] == "full")


def pf(trades: list[dict]) -> float | None:
    """Profit factor; None sin operaciones, inf si no hay perdidas."""
    gross_profit = sum(float(t["pnl"]) for t in trades if float(t["pnl"]) > 0)
    gross_loss = -sum(float(t["pnl"]) for t in trades if float(t["pnl"]) < 0)
    if gross_loss:
        return gross_profit / gross_loss
    return float("inf") if gross_profit else None


def exp_r(trades: list[dict]) -> float | None:
    return sum(float(t["r_multiple"]) for t in trades) / len(trades) if trades else None


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q / 100
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def pf_json(value: float | None):
    """Representacion JSON estable para PF: null, numero o 'inf'."""
    if value is None:
        return None
    if isinstance(value, float) and math.isinf(value):
        return "inf" if value > 0 else "-inf"
    return value


def rounded(value: float | None, digits: int = 4):
    if value is None:
        return None
    if isinstance(value, float) and math.isinf(value):
        return pf_json(value)
    return round(value, digits)


def fmt_pf(value: float | None) -> str:
    if value is None:
        return "n/d"
    if isinstance(value, float) and math.isinf(value):
        return "inf" if value > 0 else "-inf"
    return f"{value:.2f}"


def fmt_r(value: float | None) -> str:
    return "n/d" if value is None else f"{value:+.2f}"


def gate(gid: str, ok: bool | None, value, threshold: str, detail: str) -> dict:
    return {
        "id": gid,
        "pass": None if ok is None else bool(ok),
        "value": value,
        "threshold": threshold,
        "detail": detail,
    }


def parse_ts(value: str) -> int | None:
    """Acepta epoch o ISO-8601 con zona; None si no es interpretable."""
    if value.isdigit():
        return int(value)
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return int(dt.timestamp())


# ------------------------------------------------------------------ bloques
blocks: list[dict] = []
block_trades: dict[str, list[dict]] = {}
for window in LOCK["windows"]:
    data = full(json.loads((OUT / f"{window['id']}.json").read_text(encoding="utf-8")))
    trades = data["trades"]
    block_trades[window["id"]] = trades
    blocks.append(
        {
            "id": window["id"],
            "start": window["start"],
            "end": window["end"],
            "sessions_expected": window["sessions"],
            "sessions": data["dataset"]["sessions"]["count"],
            "first_et": data["dataset"]["selected_range"]["first_et"],
            "last_et": data["dataset"]["selected_range"]["last_et"],
            "trades": data["metrics"]["trades"],
            "profit_factor": data["metrics"]["profit_factor"],
            "expectancy_r": data["metrics"]["avg_r"],
            "net_profit": data["metrics"]["net_profit"],
            "max_drawdown": data["metrics"]["max_drawdown"],
            "worst_loss_streak": data["metrics"]["worst_loss_streak"],
            "by_direction": data["metrics"]["by_direction"],
        }
    )

block_pfs = {b["id"]: pf(block_trades[b["id"]]) for b in blocks}
for block in blocks:
    block["profit_factor"] = pf_json(block_pfs[block["id"]])
all_trades = [t for window in LOCK["windows"] for t in block_trades[window["id"]]]
agg_stats = compute_stats(all_trades, SETTINGS.risk.initial_capital)
n = len(all_trades)
pnls = [float(t["pnl"]) for t in all_trades]
rs = [float(t["r_multiple"]) for t in all_trades]
gross_profit = sum(p for p in pnls if p > 0)
gross_loss = -sum(p for p in pnls if p < 0)
net = sum(pnls)
agg_pf = pf(all_trades)
agg_r = sum(rs) / n if n else None
top5 = sorted(pnls, reverse=True)[:5]
drop_best = net - sum(top5)

monthly: dict[str, float] = defaultdict(float)
for trade in all_trades:
    monthly[et_date(int(trade["exit_ts"])).strftime("%Y-%m")] += float(trade["pnl"])
best_month = max(monthly.values()) if monthly else 0.0
top5_share = sum(top5) / gross_profit * 100 if gross_profit else None
best_month_share = best_month / net * 100 if net > 0 else None

longs = [t for t in all_trades if t["direction"] == "long"]
shorts = [t for t in all_trades if t["direction"] == "short"]
ambiguous = [t for t in all_trades if (t.get("meta") or {}).get("ambiguous_bar")]
ids = [t["id"] for t in all_trades]
signal_ids = [(t.get("meta") or {}).get("signal_id") for t in all_trades]
incomplete = [
    t["id"]
    for t in all_trades
    if not (
        (t.get("meta") or {}).get("signal_id")
        and t.get("contract")
        and t.get("expiry")
        and t.get("exit_ts")
        and t.get("exit_reason")
    )
]

if n:
    rng = random.Random(BOOTSTRAP_SEED)
    bootstrap = [
        sum(rs[rng.randrange(n)] for _ in range(n)) / n
        for _ in range(BOOTSTRAP_RUNS)
    ]
    boot = {
        "mean": sum(bootstrap) / len(bootstrap),
        "p2_5": percentile(bootstrap, 2.5),
        "p10": percentile(bootstrap, 10),
        "p90": percentile(bootstrap, 90),
        "p97_5": percentile(bootstrap, 97.5),
        "n": BOOTSTRAP_RUNS,
        "seed": BOOTSTRAP_SEED,
    }
else:
    boot = {
        "mean": None,
        "p2_5": None,
        "p10": None,
        "p90": None,
        "p97_5": None,
        "n": 0,
        "seed": BOOTSTRAP_SEED,
    }

aggregate = {
    "trades": n,
    "profit_factor": rounded(agg_pf, 4),
    "expectancy_r": rounded(agg_r, 6),
    "net_profit": round(net, 2),
    "gross_profit": round(gross_profit, 2),
    "gross_loss": round(gross_loss, 2),
    "max_drawdown": agg_stats["max_drawdown"],
    "max_drawdown_pct": agg_stats["max_drawdown_pct"],
    "worst_loss_streak": agg_stats["worst_loss_streak"],
    "long": len(longs),
    "short": len(shorts),
    "days_traded": len({et_date(int(t["exit_ts"])) for t in all_trades}),
    "total_r": round(sum(rs), 4) if rs else 0.0,
    "sharpe": agg_stats["sharpe"],
    "sortino": agg_stats["sortino"],
    "by_direction": agg_stats["by_direction"],
}

# ------------------------------------------------------------------ dataset
validator = json.loads((OUT / "validator.json").read_text(encoding="utf-8-sig"))
manifest = validator["manifest"]
with (ROOT / "data/real/bars_mnq_nq_es_1m.csv").open(
    newline="", encoding="utf-8"
) as handle:
    rows = list(csv.DictReader(handle))

grouped: dict[tuple[str, str], list[int]] = defaultdict(list)
tz_ok = True
for row in rows:
    raw_ts = row["timestamp"]
    if not raw_ts.isdigit() and "." in raw_ts:
        tz_ok = False
    ts = parse_ts(raw_ts)
    if ts is None:
        tz_ok = False
        continue
    grouped[(et_date(ts).isoformat(), row["symbol"])].append(ts)

intra_gaps = 0
for values in grouped.values():
    values.sort()
    intra_gaps += sum(1 for a, b in zip(values, values[1:]) if b - a != 60)

roll_ok = True
contracts_map = manifest.get("all_contracts_by_session") or manifest["contracts_by_session"]
for event in manifest["rolls"]:
    for symbol in ("MNQ", "NQ", "ES"):
        if symbol not in event["from"] or symbol not in event["to"]:
            roll_ok = False
            continue
        before = contracts_map.get(event["date"], {}).get(symbol)
        after = contracts_map.get(event["switch_date"], {}).get(symbol)
        if before != event["from"][symbol] or after != event["to"][symbol]:
            roll_ok = False

fills_path = ROOT / "data/real/bars_mnq_nq_es_1m_fills.csv"
fills = 0
if fills_path.exists():
    with fills_path.open(newline="", encoding="utf-8") as handle:
        fills = sum(1 for _ in csv.DictReader(handle))

series_mode = manifest.get("series_mode") or validator.get("series_mode")
evaluated_sessions = validator["session_count"]
calendar_sessions = len(manifest["all_sessions"])
expected_evaluated = sum(window["sessions"] for window in LOCK["windows"])
block_sessions = sum(block["sessions"] for block in blocks)
blocks_ok = (
    len(blocks) == len(LOCK["windows"])
    and block_sessions == expected_evaluated
    and all(block["sessions"] == block["sessions_expected"] for block in blocks)
)

g1_ok = (
    validator["ok"]
    and manifest["aligned"]
    and evaluated_sessions == 362
    and calendar_sessions == 368
    and evaluated_sessions == expected_evaluated
    and blocks_ok
    and validator["session_validation"]["invalid_sessions"] == 0
    and validator["session_validation"]["missing_session_count"] == 0
    and intra_gaps == 0
    and tz_ok
    and fills == 0
    and len(manifest["contract_expiries"]) == 21
    and len(manifest["rolls"]) == 6
    and len(manifest["roll_sessions"]) == 6
    and roll_ok
    and manifest["contracts_declared"]
    and series_mode == "raw"
)

# ------------------------------------------------------------------ G2 / G3
w1 = full(json.loads((OUT / "W1.json").read_text(encoding="utf-8")))
w1_repeat = full(json.loads((OUT / "W1_repeat.json").read_text(encoding="utf-8")))
w1_adjusted = full(json.loads((OUT / "W1_adjusted.json").read_text(encoding="utf-8")))


def operation(trade: dict) -> tuple:
    meta = trade.get("meta") or {}
    return (
        meta.get("signal_id"),
        trade["entry_ts"],
        trade["exit_ts"],
        trade["direction"],
        trade["qty"],
        trade.get("exit_reason"),
    )


def deterministic_signature(trade: dict) -> tuple:
    return operation(trade) + (
        round(float(trade["pnl"]), 2),
        round(float(trade["r_multiple"]), 6),
    )


deterministic = (
    len(w1["trades"]) == len(w1_repeat["trades"])
    and [deterministic_signature(t) for t in w1["trades"]]
    == [deterministic_signature(t) for t in w1_repeat["trades"]]
    and w1["dataset"]["selected_id"] == w1_repeat["dataset"]["selected_id"]
    and w1["dataset"]["code"]["sha256"] == w1_repeat["dataset"]["code"]["sha256"]
)

operation_fields = ("entry_ts", "exit_ts", "direction", "qty", "exit_reason")
operation_differences = [
    {
        "signal_id": (raw_trade.get("meta") or {}).get("signal_id"),
        "fields": [
            field
            for field in operation_fields
            if raw_trade[field] != adj_trade[field]
        ],
        "raw": {field: raw_trade[field] for field in operation_fields},
        "adjusted": {field: adj_trade[field] for field in operation_fields},
    }
    for raw_trade, adj_trade in zip(w1["trades"], w1_adjusted["trades"])
    if any(raw_trade[field] != adj_trade[field] for field in operation_fields)
]
same_operations = (
    len(w1["trades"]) == len(w1_adjusted["trades"])
    and not operation_differences
)
pnl_differences = [
    {
        "signal_id": (raw_trade.get("meta") or {}).get("signal_id"),
        "raw_pnl": raw_trade["pnl"],
        "adjusted_pnl": adj_trade["pnl"],
        "raw_entry": raw_trade["entry_price"],
        "adjusted_entry": adj_trade["entry_price"],
        "raw_stop": raw_trade["stop"],
        "adjusted_stop": adj_trade["stop"],
        "raw_r": raw_trade["r_multiple"],
        "adjusted_r": adj_trade["r_multiple"],
        "raw_qty": raw_trade["qty"],
        "adjusted_qty": adj_trade["qty"],
    }
    for raw_trade, adj_trade in zip(w1["trades"], w1_adjusted["trades"])
    if round(raw_trade["pnl"], 2) != round(adj_trade["pnl"], 2)
]
qty_differences = [
    {
        "signal_id": (raw_trade.get("meta") or {}).get("signal_id"),
        "raw_qty": raw_trade["qty"],
        "adjusted_qty": adj_trade["qty"],
    }
    for raw_trade, adj_trade in zip(w1["trades"], w1_adjusted["trades"])
    if raw_trade["qty"] != adj_trade["qty"]
]

adjusted_rolls = (w1_adjusted["dataset"].get("manifest") or {}).get("rolls") or []
cumulative_offsets = {
    symbol: round(
        sum(event["offsets"].get(symbol, 0.0) for event in manifest["rolls"]), 4
    )
    for symbol in ("MNQ", "NQ", "ES")
}
applied_cumulative_offsets = {
    symbol: round(
        sum(
            (event.get("applied_offsets") or {}).get(symbol, 0.0)
            for event in adjusted_rolls
        ),
        4,
    )
    for symbol in ("MNQ", "NQ", "ES")
}
basis_residual_cumulative = {
    symbol: round(cumulative_offsets[symbol] - applied_cumulative_offsets[symbol], 4)
    for symbol in ("MNQ", "NQ", "ES")
}
identical_trades = same_operations and not pnl_differences and not qty_differences

(OUT / "determinism_w1.json").write_text(
    json.dumps(
        {
            "runs": ["W1.json", "W1_repeat.json"],
            "trades": len(w1["trades"]),
            "identical": deterministic,
            "trades_sha256": hashlib.sha256(
                json.dumps(w1["trades"], sort_keys=True, ensure_ascii=False).encode(
                    "utf-8"
                )
            ).hexdigest(),
            "deterministic_sha256": hashlib.sha256(
                json.dumps(
                    [deterministic_signature(t) for t in w1["trades"]],
                    sort_keys=True,
                    ensure_ascii=False,
                ).encode("utf-8")
            ).hexdigest(),
        },
        indent=2,
        ensure_ascii=False,
    ),
    encoding="utf-8",
)
(OUT / "raw_vs_adjusted_w1.json").write_text(
    json.dumps(
        {
            "raw_file": "W1.json",
            "adjusted_file": "W1_adjusted.json",
            "raw_trades": len(w1["trades"]),
            "adjusted_trades": len(w1_adjusted["trades"]),
            "same_operations": same_operations,
            "operation_differences": operation_differences,
            "identical_pnl": not pnl_differences,
            "identical_trades": identical_trades,
            "pnl_differences": pnl_differences,
            "qty_differences": qty_differences,
            "cumulative_roll_offsets": cumulative_offsets,
            "applied_cumulative_offsets": applied_cumulative_offsets,
            "basis_residual_cumulative": basis_residual_cumulative,
            "adjusted_offset_policy": {
                "pair": ["NQ", "MNQ"],
                "basis_symbol": "MNQ",
                "es": "own_offset",
                "rounding": "raw_base_then_translate",
            },
            "cause": (
                "Corregido: NQ y MNQ comparten el offset de ejecucion de MNQ en cada roll; "
                "ES conserva su propio offset y el SMT compara pivotes dentro de cada "
                "instrumento. El redondeo de niveles se ancla a la base raw antes de "
                "trasladarlos a adjusted. W1 produce las mismas operaciones y el mismo P&L."
                if identical_trades
                else (
                    "La estrategia calcula ORB, entrada y stop con barras de NQ y ejecuta en MNQ. "
                    "En adjusted cada raiz recibe su propio desplazamiento acumulado; MNQ y NQ "
                    "dejan de compartir la misma base y los niveles NQ aplicados a MNQ cambian."
                )
            ),
        },
        indent=2,
        ensure_ascii=False,
    ),
    encoding="utf-8",
)

# ------------------------------------------------------------------ puertas
min_per_direction = ACC["dev_min_trades_per_direction"]
g4_ok = (
    n >= ACC["dev_min_trades"]
    and len(longs) >= min_per_direction
    and len(shorts) >= min_per_direction
)
g5_ok = (
    agg_pf is not None
    and agg_pf >= ACC["dev_min_profit_factor"]
    and agg_r is not None
    and agg_r >= ACC["dev_min_expectancy_r"]
)
g7_above = sum(1 for value in block_pfs.values() if value is not None and value > 1)
g7_bad = [
    block
    for block in blocks
    if block["trades"] >= ACC["dev_block_min_trades"]
    and block_pfs[block["id"]] is not None
    and block_pfs[block["id"]] < ACC["dev_block_fail_profit_factor"]
]

gates = [
    gate(
        "G1",
        g1_ok,
        {
            "sessions": calendar_sessions,
            "evaluated": evaluated_sessions,
            "block_sessions": block_sessions,
            "intra_session_gaps": intra_gaps,
            "fills": fills,
            "contracts": len(manifest["contract_expiries"]),
            "rolls": len(manifest["rolls"]),
            "series_mode": series_mode,
        },
        "368/368 calendario, 362 evaluadas, 362/362 sesiones en bloques; 0 huecos; rolls MNQ/NQ/ES",
        (
            f"D1-D8 en desarrollo. Los {calendar_sessions - 1} huecos del validador "
            "son cierres overnight, no minutos ausentes. El lock 24/21/7 aplica al "
            "dataset completo con holdout."
        )
        if g1_ok
        else (
            "Falla de integridad: revisar sesiones, huecos internos, rolls, fills o "
            "cobertura W1-W6."
        ),
    ),
    gate(
        "G2",
        deterministic,
        {
            "trades": len(w1["trades"]),
            "runs": 2,
            "code": w1["dataset"]["code"]["sha256"][:12],
        },
        "operaciones identicas",
        (
            f"W1 ejecutado dos veces con el mismo codigo; {len(w1['trades'])} "
            "operaciones, mismo P&L y mismo selected_id."
            if deterministic
            else "Falla: las dos ejecuciones de W1 no son identicas."
        ),
    ),
    gate(
        "G3",
        identical_trades,
        {
            "trades_raw": len(w1["trades"]),
            "trades_adjusted": len(w1_adjusted["trades"]),
            "same_operations": same_operations,
            "operation_differences": len(operation_differences),
            "pnl_differences": len(pnl_differences),
            "qty_differences": len(qty_differences),
            "cumulative_roll_offsets": cumulative_offsets,
            "applied_cumulative_offsets": applied_cumulative_offsets,
            "basis_residual_cumulative": basis_residual_cumulative,
        },
        "mismas operaciones en W1 con ambos modos",
        (
            f"Pass: {len(w1['trades'])}/{len(w1['trades'])} operaciones identicas, mismo "
            f"P&L y mismo PF. NQ/MNQ comparten el offset de MNQ; residuo acumulado NQ "
            f"{basis_residual_cumulative['NQ']:+.2f} pts. ES conserva su offset y el "
            "redondeo se ancla a la base raw."
            if identical_trades
            else (
                f"Falla: {len(pnl_differences)}/{len(w1['trades'])} P&L difieren y "
                f"{len(operation_differences)} operaciones cambian de salida. Causa: niveles "
                "calculados en NQ y ejecucion en MNQ con bases distintas en adjusted."
            )
        ),
    ),
    gate(
        "G4",
        g4_ok,
        {"trades": n, "long": len(longs), "short": len(shorts)},
        f">= {ACC['dev_min_trades']} operaciones y >= {min_per_direction} por direccion",
        (
            f"Muestra suficiente: {n} operaciones, {len(longs)} largos y {len(shorts)} cortos."
            if g4_ok
            else (
                f"Muestra insuficiente: {n} operaciones, {len(longs)} largos y "
                f"{len(shorts)} cortos."
            )
        ),
    ),
    gate(
        "G5",
        g5_ok,
        {"profit_factor": rounded(agg_pf, 4), "expectancy_r": rounded(agg_r, 4)},
        f">= {ACC['dev_min_profit_factor']} PF y >= {ACC['dev_min_expectancy_r']:+.2f} R",
        (
            f"PF {fmt_pf(agg_pf)}; esperanza {fmt_r(agg_r)} R."
            + (" Pasa." if g5_ok else " No alcanza el umbral.")
        ),
    ),
    gate(
        "G6",
        agg_stats["max_drawdown"] <= ACC["dev_max_drawdown_usd"]
        and agg_stats["worst_loss_streak"] <= ACC["dev_max_losing_streak"],
        {
            "max_drawdown_usd": agg_stats["max_drawdown"],
            "worst_loss_streak": agg_stats["worst_loss_streak"],
        },
        f"<= {ACC['dev_max_drawdown_usd']:.0f} USD y <= {ACC['dev_max_losing_streak']} perdidas seguidas",
        (
            f"Drawdown {agg_stats['max_drawdown']:.2f} USD; peor racha "
            f"{agg_stats['worst_loss_streak']} (max {ACC['dev_max_losing_streak']})."
        ),
    ),
    gate(
        "G7",
        g7_above >= ACC["dev_min_blocks_with_pf_above_1"] and not g7_bad,
        {
            "blocks_pf_above_1": g7_above,
            "blocks": [
                {
                    "id": block["id"],
                    "trades": block["trades"],
                    "pf": pf_json(block_pfs[block["id"]]),
                }
                for block in blocks
            ],
        },
        f">= {ACC['dev_min_blocks_with_pf_above_1']}/{len(blocks)} bloques con PF>1 y ningun bloque >= {ACC['dev_block_min_trades']} ops con PF<{ACC['dev_block_fail_profit_factor']:.2f}",
        (
            f"{g7_above}/{len(blocks)} bloques con PF>1; "
            + (
                "ningun bloque grande por debajo del minimo."
                if not g7_bad
                else f"bloques problematicos: {', '.join(b['id'] for b in g7_bad)}."
            )
        ),
    ),
]

stress_path = OUT / "stress_costs.json"
if stress_path.exists():
    stress = json.loads(stress_path.read_text(encoding="utf-8"))
    stress_pf = stress["aggregate"]["profit_factor"]
    stress_ok = (
        None
        if stress_pf is None
        else stress_pf >= ACC["stress_min_profit_factor"]
    )
    gates.append(
        gate(
            "G8",
            stress_ok,
            {
                "profit_factor": pf_json(stress_pf),
                "commission_per_side": stress["overrides"]["execution"][
                    "commission_per_contract_side"
                ],
                "slippage_ticks": stress["overrides"]["execution"]["slippage_ticks"],
                "trades": stress["aggregate"]["trades"],
            },
            f">= {ACC['stress_min_profit_factor']} PF con comision {ACC['stress_commission_per_side']}/lado y slippage {ACC['stress_slippage_ticks']} ticks",
            (
                "Pendiente: stress sin profit_factor."
                if stress_pf is None
                else (
                    f"PF {fmt_pf(stress_pf)} con costes dobles sobre "
                    f"{stress['aggregate']['trades']} operaciones."
                    + ("" if stress_ok else " No alcanza el umbral.")
                )
            ),
        )
    )
else:
    gates.append(
        gate(
            "G8",
            None,
            {"status": "pending"},
            f">= {ACC['stress_min_profit_factor']} PF con costes dobles",
            "Pendiente de stress.",
        )
    )

ambiguous_share = len(ambiguous) / n * 100 if n else None
duplicate_ids = len(ids) - len(set(ids))
duplicate_signal_ids = len(signal_ids) - len(set(signal_ids))
g14_ok = not incomplete and duplicate_ids == 0 and duplicate_signal_ids == 0
short_pf = pf(shorts)
short_exp = exp_r(shorts)
gates.extend(
    [
        gate(
            "G9",
            drop_best > 0,
            {
                "net_profit": round(net, 2),
                "top5_pnl": round(sum(top5), 2),
                "net_drop_best5": round(drop_best, 2),
            },
            "> 0 tras quitar las 5 mejores",
            (
                f"Neto {net:.2f}; top-5 {sum(top5):.2f}; tras quitarlas "
                f"{drop_best:.2f}."
            ),
        ),
        gate(
            "G10",
            top5_share is not None
            and top5_share <= ACC["max_top5_share_of_gross_profit_pct"]
            and best_month_share is not None
            and best_month_share <= ACC["max_best_month_share_of_net_pct"],
            {
                "top5_share_gross_profit_pct": rounded(top5_share, 2),
                "best_month_share_net_pct": rounded(best_month_share, 2),
            },
            f"<= {ACC['max_top5_share_of_gross_profit_pct']}% y <= {ACC['max_best_month_share_of_net_pct']}%",
            (
                f"Top-5 {fmt_pf(top5_share)}% del bruto; mejor mes "
                f"{fmt_pf(best_month_share)}% del neto."
            ),
        ),
        gate(
            "G11",
            boot["p10"] is not None and boot["p10"] > 0,
            boot,
            "limite inferior del IC bootstrap al 80% > 0",
            (
                f"Bootstrap {BOOTSTRAP_RUNS} remuestreos (semilla {BOOTSTRAP_SEED}); "
                f"p10 {fmt_r(boot['p10'])} R; IC95% "
                f"[{fmt_r(boot['p2_5'])}, {fmt_r(boot['p97_5'])}]."
            ),
        ),
        gate(
            "G12",
            len(shorts) >= min_per_direction
            and short_pf is not None
            and short_pf >= ACC["short_min_profit_factor"]
            and short_exp is not None
            and short_exp >= ACC["short_min_expectancy_r"],
            {
                "trades": len(shorts),
                "pf": rounded(short_pf, 4),
                "expectancy_r": rounded(short_exp, 4),
            },
            f">= {min_per_direction} cortos, PF >= {ACC['short_min_profit_factor']} y expR >= {ACC['short_min_expectancy_r']:+.2f}",
            (
                f"{len(shorts)} cortos (min {min_per_direction}); PF {fmt_pf(short_pf)}; "
                f"expR {fmt_r(short_exp)}."
            ),
        ),
        gate(
            "G13",
            ambiguous_share is not None
            and ambiguous_share <= ACC["max_ambiguous_share_pct"],
            {
                "ambiguous_trades": len(ambiguous),
                "share_pct": rounded(ambiguous_share, 2),
            },
            f"<= {ACC['max_ambiguous_share_pct']}%",
            (
                "Sin operaciones: no evaluable."
                if n == 0
                else f"{len(ambiguous)} operaciones ambiguas ({ambiguous_share:.2f}%)."
            ),
        ),
        gate(
            "G14",
            g14_ok,
            {
                "incomplete": len(incomplete),
                "duplicate_ids": duplicate_ids,
                "duplicate_signal_ids": duplicate_signal_ids,
            },
            "campos completos, sin duplicados ni huerfanas",
            (
                "Todas las operaciones tienen signal_id, contrato y expiry; sin duplicados."
                if g14_ok
                else (
                    f"{len(incomplete)} incompletas; {duplicate_ids} IDs duplicados; "
                    f"{duplicate_signal_ids} signal_id duplicados."
                )
            ),
        ),
    ]
)

failed = [g["id"] for g in gates if g["pass"] is False]
pending = [g["id"] for g in gates if g["pass"] is None]
if pending:
    decision = (
        f"PENDIENTE: {', '.join(pending)} sin evaluar. "
        f"Fallan: {', '.join(failed) or 'ninguna'}. Holdout no ejecutado."
    )
elif failed:
    if "G4" in failed:
        decision = (
            f"INCONCLUSO: G4 no alcanza la muestra minima ({n} operaciones, "
            f"{len(shorts)} cortos). Fallan: {', '.join(failed)}. "
            "Holdout no ejecutado."
        )
    else:
        decision = (
            f"RECHAZADO: fallan {', '.join(failed)}. Holdout no ejecutado."
        )
else:
    decision = "APTO DESARROLLO: todas las puertas PASS. Holdout pendiente."

report = {
    "protocol_version": LOCK["protocol_version"],
    "scope": "development",
    "holdout": "sealed",
    "aggregate": aggregate,
    "blocks": blocks,
    "bootstrap": boot,
    "drop_best5_net": round(drop_best, 2),
    "top5_share_gross_profit_pct": rounded(top5_share, 2),
    "best_month_share_net_pct": rounded(best_month_share, 2),
    "gates": gates,
    "failed": failed,
    "pending": pending,
    "decision": decision,
}
(OUT / "gates.json").write_text(
    json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8"
)

# ------------------------------------------------------------------ manifiesto
protocol_path = ROOT / "docs/PROTOCOLO_BACKTEST.md"
lock_path = ROOT / "docs/protocolo_backtest.lock.json"
code_sha, code_files = compute_code_hash(ROOT, [ROOT / "server", ROOT / "tests"])
windows = []
for window in LOCK["windows"]:
    calendar = [
        day
        for day in manifest["all_sessions"]
        if window["start"] <= day <= window["end"]
    ]
    excluded = [day for day in manifest["excluded_sessions"] if day in calendar]
    windows.append(
        {
            "id": window["id"],
            "start": window["start"],
            "end": window["end"],
            "calendar_sessions": len(calendar),
            "evaluated_sessions": len(calendar) - len(excluded),
            "expected_evaluated": window["sessions"],
        }
    )
dev_manifest = {
    "schema_version": "development-only",
    "scope": "development",
    "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    "holdout": {"status": "sealed", "inspected": False},
    "protocol": {
        "path": "docs/PROTOCOLO_BACKTEST.md",
        "sha256": sha256_file(protocol_path),
        "version": LOCK["protocol_version"],
    },
    "lock": {
        "path": "docs/protocolo_backtest.lock.json",
        "sha256": sha256_file(lock_path),
        "config_sha256": settings_sha256(LOCK["settings"]),
    },
    "code": {"sha256": code_sha, "roots": ["server", "tests"], "files": code_files},
    "dataset": {
        "path": "data/real/bars_mnq_nq_es_1m.csv",
        "file_sha256": sha256_file(ROOT / "data/real/bars_mnq_nq_es_1m.csv"),
        "dataset_id": manifest["dataset_id"],
        "series_id": manifest["series_id"],
        "series_mode": series_mode,
        "all_sessions": len(manifest["all_sessions"]),
        "evaluated_sessions": validator["session_count"],
        "rows": manifest["row_count"],
        "common_bars": validator["common_bars"],
        "all_common_bars": validator["all_common_bars"],
        "contracts": manifest["contracts"],
        "contract_expiries": manifest["contract_expiries"],
        "roll_events": len(manifest["rolls"]),
        "roll_sessions": manifest["roll_sessions"],
        "fills": fills,
        "windows": windows,
    },
    "note": (
        "Manifiesto de desarrollo: el dataset_manifest.json oficial del protocolo exige "
        "454 sesiones y 24 contratos, que solo existen al incorporar el holdout sellado. "
        "Este archivo acredita la procedencia de la fase de desarrollo."
    ),
}
(OUT / "dataset_manifest_dev.json").write_text(
    json.dumps(dev_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
)


def state(value: bool | None) -> str:
    return "PASS" if value is True else "FAIL" if value is False else "PENDING"


print("GATES", [(g["id"], state(g["pass"])) for g in gates])
print("failed", failed, "pending", pending)
print("agg", aggregate)
print("bootstrap", boot)
print(
    "drop-best",
    round(drop_best, 2),
    "top5%",
    fmt_pf(top5_share),
    "best month%",
    fmt_pf(best_month_share),
)
print("shorts pf", fmt_pf(short_pf), "expR", fmt_r(short_exp))
