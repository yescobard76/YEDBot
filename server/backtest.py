"""Motor de backtesting independiente del motor en vivo.

Reutiliza la misma clase de estrategia y el mismo ejecutor paper, de modo que
una diferencia entre backtest y paper solo puede venir de los datos, nunca de
una segunda implementación de las reglas.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import uuid
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Sequence

from .config import BASE_DIR, Settings, apply_settings, load_settings
from .execution import ExecutionEngine
from .experiments import assert_result_identity, build_identity
from .funnel import FUNNEL_SCHEMA, FunnelRecorder
from .market.csv_data import DATA_SCHEMA_VERSION, REQUIRED_SYMBOLS, CsvDataset
from .market.synthetic import build_session
from .models import Bar
from .risk import RiskManager
from .stats import compute_stats
from .strategy.strategy import ORBStrategy
from .timeutil import et_date, et_hm, et_minutes, hm_to_minutes, local_dt, next_weekday

VARIANTS: dict[str, tuple[str, dict]] = {
    "orb": ("ORB solo (entrada directa)", {"strategy": {"use_smt": False, "entry_reference": "none"}}),
    "orb_smt": ("ORB + SMT (entrada directa)", {"strategy": {"use_smt": True, "entry_reference": "none"}}),
    "orb_retest": ("ORB + retesteo 50%", {"strategy": {"use_smt": False, "entry_reference": "or_mid"}}),
    "full": ("ORB + SMT + retesteo (completa)", {"strategy": {"use_smt": True, "entry_reference": "or_mid"}}),
}

# Presets de investigación. Cada patch es parcial y se valida contra la
# configuración base; no se aplica nunca al motor en vivo. El baseline se
# ejecuta siempre para poder calcular deltas comparables sobre el mismo dataset.
PRESETS: dict[str, dict[str, Any]] = {
    "baseline": {
        "label": "Base actual (sin cambios)",
        "group": "base",
        "description": "Configuración activa; referencia para todos los deltas.",
        "patch": {},
    },
    "entry_breakout_direct": {
        "label": "Entrada directa en ruptura",
        "group": "frecuencia",
        "description": "Entra al confirmar la ruptura, sin esperar retroceso.",
        "patch": {"strategy": {"entry_reference": "none"}},
    },
    "entry_or_level": {
        "label": "Retesteo del nivel ORH/ORL",
        "group": "frecuencia",
        "description": "Espera el retesteo del nivel roto, no del 50% del rango.",
        "patch": {"strategy": {"entry_reference": "breakout_level"}},
    },
    "entry_retrace_30": {
        "label": "Retroceso 30% del OR",
        "group": "frecuencia",
        "description": "Retroceso superficial: ORH/ORL menos 30% del ancho del rango.",
        "patch": {"strategy": {"entry_reference": "or_retracement", "or_retracement_pct": 0.30}},
    },
    "entry_retrace_382": {
        "label": "Retroceso 38.2% del OR",
        "group": "frecuencia",
        "description": "Retroceso superficial: ORH/ORL menos 38.2% del ancho del rango.",
        "patch": {"strategy": {"entry_reference": "or_retracement", "or_retracement_pct": 0.382}},
    },
    "smt_window_90": {
        "label": "SMT ventana 90 min",
        "group": "frecuencia",
        "description": "Permite comparar pivotes separados hasta 90 minutos.",
        "patch": {"smt": {"window_minutes": 90}},
    },
    "smt_window_120": {
        "label": "SMT ventana 120 min",
        "group": "frecuencia",
        "description": "Permite comparar pivotes separados hasta 120 minutos.",
        "patch": {"smt": {"window_minutes": 120}},
    },
    "smt_tolerance_12": {
        "label": "SMT tolerancia 12 ticks",
        "group": "frecuencia",
        "description": "Absorbe 12 ticks de ruido en el extremo equivalente del ES.",
        "patch": {"smt": {"tolerance_ticks": 12}},
    },
    "smt_tolerance_16": {
        "label": "SMT tolerancia 16 ticks",
        "group": "frecuencia",
        "description": "Absorbe 16 ticks de ruido en el extremo equivalente del ES.",
        "patch": {"smt": {"tolerance_ticks": 16}},
    },
    "retest_tolerance_24": {
        "label": "Tolerancia retesteo 24 ticks",
        "group": "frecuencia",
        "description": (
            "Acepta el toque de la referencia hasta 24 ticks; más tolerancia "
            "produce más retesteos válidos, también más entradas tardías."
        ),
        "patch": {"strategy": {"retest_tolerance_ticks": 24}},
    },
    "retest_tolerance_40": {
        "label": "Tolerancia retesteo 40 ticks",
        "group": "frecuencia",
        "description": (
            "Acepta el toque de la referencia hasta 40 ticks; es el extremo "
            "más permisivo de esta comparación."
        ),
        "patch": {"strategy": {"retest_tolerance_ticks": 40}},
    },
    "setup_validity_180": {
        "label": "Validez setup 180 min",
        "group": "frecuencia",
        "description": "Da tres horas para completar SMT y retesteo.",
        "patch": {"strategy": {"setup_validity_minutes": 180}},
    },
    "setup_validity_240": {
        "label": "Validez setup 240 min",
        "group": "frecuencia",
        "description": "Da cuatro horas para completar SMT y retesteo.",
        "patch": {"strategy": {"setup_validity_minutes": 240}},
    },
    "sl_depth_5": {
        "label": "Swing estructural 5 velas",
        "group": "stop",
        "description": "Confirma el swing 15m con 5 velas para el SL.",
        "patch": {"strategy": {"structural_depth": 5}},
    },
    "sl_depth_6": {
        "label": "Swing estructural 6 velas",
        "group": "stop",
        "description": "Confirma el swing 15m con 6 velas para el SL.",
        "patch": {"strategy": {"structural_depth": 6}},
    },
    "sl_buffer_8": {
        "label": "Buffer SL 8 ticks",
        "group": "stop",
        "description": "Separa el SL de la estructura con 8 ticks.",
        "patch": {"strategy": {"sl_buffer_ticks": 8}},
    },
    "sl_buffer_12": {
        "label": "Buffer SL 12 ticks",
        "group": "stop",
        "description": "Separa el SL de la estructura con 12 ticks.",
        "patch": {"strategy": {"sl_buffer_ticks": 12}},
    },
    "recovery_off": {
        "label": "Sin cierre de recuperación",
        "group": "stop",
        "description": "Acepta el rechazo dentro de la tolerancia sin esperar vela de recuperación.",
        "patch": {"strategy": {"require_recovery_close": False}},
    },
    "sl_cap_600": {
        "label": "Tope SL 600 ticks (control)",
        "group": "riesgo",
        "description": (
            "Levanta solo max_sl_ticks a 600 y no cambia risk_per_trade_pct. "
            "Con el perfil por defecto (25k/1%), los stops de 501–600 ticks quedan en qty=0."
        ),
        "patch": {"risk": {"max_sl_ticks": 600}},
    },
    "rr_2": {
        "label": "Objetivo 2.0R",
        "group": "objetivo",
        "description": "TP a dos veces la distancia del SL.",
        "patch": {"strategy": {"tp_rr": 2.0}},
    },
    "rr_2_5": {
        "label": "Objetivo 2.5R",
        "group": "objetivo",
        "description": "TP a 2.5 veces la distancia del SL.",
        "patch": {"strategy": {"tp_rr": 2.5}},
    },
    "entry_or_level_sl_cap_600": {
        "label": "Nivel OR + tope SL 600",
        "group": "combinado",
        "description": (
            "Espera el retesteo de ORH/ORL y levanta solo max_sl_ticks a 600; "
            "conserva risk_per_trade_pct para separar el cap del presupuesto."
        ),
        "patch": {
            "strategy": {"entry_reference": "breakout_level"},
            "risk": {"max_sl_ticks": 600},
        },
    },
    "direct_sl_cap_600": {
        "label": "Entrada directa + tope SL 600",
        "group": "combinado",
        "description": (
            "Entrada directa sin retesteo con el tope de 600 ticks; separa el "
            "efecto de la entrada del de la financiación del stop."
        ),
        "patch": {
            "strategy": {"entry_reference": "none"},
            "risk": {"max_sl_ticks": 600},
        },
    },
    "deep_stop_sl_cap_600": {
        "label": "Stop profundo + tope SL 600",
        "group": "combinado",
        "description": (
            "Swing 6 y buffer 12 con el tope de 600 ticks; mide si el stop "
            "profundo es financiable sin cambiar el presupuesto de riesgo."
        ),
        "patch": {
            "strategy": {"structural_depth": 6, "sl_buffer_ticks": 12},
            "risk": {"max_sl_ticks": 600},
        },
    },
    "combo_requested": {
        "label": "Combinado solicitado (frecuencia + SL)",
        "group": "combinado",
        "description": (
            "Retroceso 38.2%, SMT 120 min/16 ticks, validez 240, swing 6, "
            "buffer 12, sin recuperación y 2.5R. Solo como candidato exploratorio."
        ),
        "patch": {
            "strategy": {
                "entry_reference": "or_retracement",
                "or_retracement_pct": 0.382,
                "setup_validity_minutes": 240,
                "structural_depth": 6,
                "sl_buffer_ticks": 12,
                "require_recovery_close": False,
                "tp_rr": 2.5,
            },
            "smt": {"window_minutes": 120, "tolerance_ticks": 16},
        },
    },
}

# Presets que se ejecutan cuando no se pide una selección explícita. La lista
# es explícita para que el conjunto por defecto sea visible y no dependa de
# banderas repartidas por el catálogo.
DEFAULT_PRESETS: tuple[str, ...] = (
    "baseline",
    "entry_breakout_direct",
    "entry_or_level",
    "entry_retrace_382",
    "smt_window_120",
    "smt_tolerance_16",
    "setup_validity_240",
    "sl_depth_6",
    "sl_buffer_12",
    "recovery_off",
    "rr_2_5",
)
# Reglas que ningún preset puede modificar: son la base estructural del setup.
PROTECTED_PRESET_PATHS: frozenset[tuple[str, ...]] = frozenset(
    {
        ("strategy", "confirm_tf"),
        ("strategy", "require_close_breakout"),
        ("strategy", "allow_reentry_after_false_breakout"),
        ("strategy", "min_range_ticks"),
        ("strategy", "use_smt"),
        ("smt", "enabled"),
        ("smt", "pivot_depth"),
        ("smt", "detect_tf"),
        ("smt", "require_recovery"),
        ("orb", "start"),
        ("orb", "end"),
    }
)

MIN_BACKTEST_DAYS = 3
MAX_BACKTEST_DAYS = 250


def _validate_days(days: int) -> int:
    """Valida el tamaño de la muestra sin recortarlo en silencio."""
    if not isinstance(days, int) or isinstance(days, bool):
        raise TypeError("days debe ser un entero")
    if not MIN_BACKTEST_DAYS <= days <= MAX_BACKTEST_DAYS:
        raise ValueError(
            f"days debe estar entre {MIN_BACKTEST_DAYS} y {MAX_BACKTEST_DAYS}; "
            f"recibido {days}"
        )
    return days


def _code_provenance() -> dict[str, Any]:
    """Identidad del árbol de código ejecutado, con el mismo algoritmo del preflight."""
    from .confirmatory import CODE_HASH_ALGORITHM, compute_code_hash

    roots = [path for path in (BASE_DIR / "server", BASE_DIR / "tests") if path.exists()]
    sha256, files = compute_code_hash(BASE_DIR, roots)
    return {
        "sha256": sha256,
        "algorithm": CODE_HASH_ALGORITHM,
        "roots": [path.name for path in roots],
        "files": files,
    }


def _session_range(sessions: list[tuple[date, dict[str, list[Bar]]]]) -> dict[str, Any]:
    """Rango temporal efectivo de las sesiones que realmente usa el backtest."""
    if not sessions:
        return {"first_ts": None, "last_ts": None, "first_et": None, "last_et": None}
    first = min(data[s][0].ts for _, data in sessions for s in data if data[s])
    last = max(data[s][-1].ts for _, data in sessions for s in data if data[s])
    return {
        "first_ts": first,
        "last_ts": last,
        "first_et": local_dt(first).strftime("%Y-%m-%d %H:%M"),
        "last_et": local_dt(last).strftime("%Y-%m-%d %H:%M"),
    }


def _hash_sessions(
    sessions: list[tuple[date, dict[str, list[Bar]]]],
    meta: dict[str, Any],
) -> str:
    """Hash canónico de las sesiones seleccionadas para una ejecución."""
    payload = {
        "schema_version": DATA_SCHEMA_VERSION,
        "meta": meta,
        "sessions": [
            {
                "date": day.isoformat(),
                "bars": {
                    symbol: [
                        {
                            "ts": bar.ts,
                            "open": bar.open,
                            "high": bar.high,
                            "low": bar.low,
                            "close": bar.close,
                            "volume": bar.volume,
                        }
                        for bar in bars
                    ]
                    for symbol, bars in sorted(data.items())
                },
            }
            for day, data in sessions
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def prepare_dataset(
    settings: Settings,
    days: int,
    start: date | None = None,
    *,
    allow_holdout: bool = False,
) -> tuple[list[tuple[date, dict[str, list[Bar]]]], str, dict[str, Any]]:
    """Devuelve sesiones, origen y un bloque de procedencia reproducible.

    En CSV, ``start`` se aplica como fecha mínima de sesión. Si queda fuera del
    rango del archivo, se rechaza explícitamente en vez de ignorarlo.
    ``allow_holdout`` queda reservado al comando confirmatorio: cualquier otra
    ruta rechaza el CSV completo si contiene sesiones desde 2026-07-01.
    """
    days = _validate_days(days)
    code = _code_provenance()
    if settings.feed.provider == "csv":
        path = Path(settings.feed.csv_path)
        if not path.is_absolute():
            path = BASE_DIR / path
        if not path.exists():
            raise FileNotFoundError(f"No existe el CSV de backtest: {path}")
        dataset = CsvDataset.load(
            path,
            REQUIRED_SYMBOLS,
            series_mode=settings.feed.series_mode,
            exclude_roll_sessions=settings.feed.exclude_roll_sessions,
            allow_holdout=allow_holdout,
        )
        by_day: dict[date, dict[str, list[Bar]]] = {}
        for tick in dataset.bars:
            day = et_date(tick["NQ"].ts)
            bucket = by_day.setdefault(day, {s: [] for s in REQUIRED_SYMBOLS})
            for symbol in REQUIRED_SYMBOLS:
                bucket[symbol].append(tick[symbol])
        all_sessions = [(day, data) for day, data in sorted(by_day.items()) if data["NQ"]]
        if not all_sessions:
            raise ValueError("El CSV no contiene sesiones utilizables")

        if start is not None:
            first_day, last_day = all_sessions[0][0], all_sessions[-1][0]
            if start < first_day or start > last_day:
                raise ValueError(
                    f"start_date {start.isoformat()} fuera del rango del CSV "
                    f"({first_day.isoformat()}..{last_day.isoformat()})"
                )
            selected = [(day, data) for day, data in all_sessions if day >= start]
            selection = "start_date"
        else:
            selected = all_sessions[-days:]
            selection = "last_n"
        sessions = selected[:days]
        manifest = dataset.manifest
        selected_contracts = {
            symbol: sorted(dataset.contracts.get(symbol, []))
            for symbol in REQUIRED_SYMBOLS
        }
        selected_range = _session_range(sessions)
        hash_meta = {
            "kind": "csv-selected",
            "contracts": selected_contracts,
        }
        # Los datasets antiguos sin contratos conservan su selected_id; la
        # identidad de serie solo se añade cuando aporta información nueva.
        if (
            manifest["contracts_declared"]
            or dataset.series_mode != "adjusted"
            or manifest.get("roll_sessions")
            or manifest.get("excluded_sessions")
        ):
            hash_meta.update(
                {
                    "series_id": dataset.series_id,
                    "series_mode": dataset.series_mode,
                    "roll_sessions": manifest.get("roll_sessions") or [],
                    "excluded_sessions": manifest.get("excluded_sessions") or [],
                }
            )
        selected_id = _hash_sessions(sessions, hash_meta)
        provenance = {
            "code": code,
            "id": manifest["dataset_id"],
            "series_id": dataset.series_id,
            "selected_id": selected_id,
            "kind": "csv",
            "source": "csv",
            "schema_version": manifest["schema_version"],
            "series_mode": dataset.series_mode,
            "path": manifest["path"],
            "file_name": manifest["file_name"],
            "file_hash": manifest["file_hash"],
            "row_count": manifest["row_count"],
            "common_bars": manifest["common_bars"],
            "contracts": manifest["contracts"],
            "contract_column": manifest["contract_column"],
            "contracts_declared": manifest["contracts_declared"],
            "expiry_column": manifest["expiry_column"],
            "contract_expiries": manifest["contract_expiries"],
            "contracts_by_session": manifest["contracts_by_session"],
            "expiry_by_session": manifest["expiry_by_session"],
            "rolls": manifest["rolls"],
            "roll_sessions": manifest["roll_sessions"],
            "excluded_sessions": manifest["excluded_sessions"],
            "all_sessions": manifest["all_sessions"],
            "range": manifest["range"],
            "selected_range": selected_range,
            "requested_start": start.isoformat() if start else None,
            "selection": selection,
            "sessions": {
                "count": len(sessions),
                "available": len(manifest["all_sessions"]),
                "excluded": len(manifest["excluded_sessions"]),
                "dates": [day.isoformat() for day, _ in sessions],
            },
            "aligned": manifest["aligned"],
            "gaps": manifest["gaps"],
            "warnings": manifest["warnings"],
            "manifest": manifest,
        }
        return sessions, "csv", provenance

    requested_start = start
    if start is None:
        start = et_date(int(time.time()))
    sessions = []
    day = start
    while len(sessions) < days:
        if day.weekday() < 5:
            sessions.append((day, build_session(day, settings)))
        day = next_weekday(day)
    selected_range = _session_range(sessions)
    selected_id = _hash_sessions(
        sessions,
        {"kind": "synthetic", "generator": "build_session", "generator_version": "1"},
    )
    provenance = {
        "code": code,
        "id": selected_id,
        "series_id": selected_id,
        "selected_id": selected_id,
        "kind": "synthetic",
        "source": "synthetic",
        "schema_version": "synthetic-v1",
        "generator": "build_session",
        "generator_version": "1",
        "range": selected_range,
        "selected_range": selected_range,
        "requested_start": requested_start.isoformat() if requested_start else None,
        "selection": "start_date" if requested_start else "default",
        "sessions": {
            "count": len(sessions),
            "available": len(sessions),
            "excluded": 0,
            "dates": [day.isoformat() for day, _ in sessions],
        },
        "contracts": {},
        "contract_column": False,
        "contracts_declared": False,
        "expiry_column": False,
        "contract_expiries": {},
        "contracts_by_session": {},
        "expiry_by_session": {},
        "rolls": [],
        "roll_sessions": [],
        "excluded_sessions": [],
        "all_sessions": [day.isoformat() for day, _ in sessions],
        "series_mode": "raw",
        "row_count": sum(len(bars) for _, data in sessions for bars in data.values()),
        "common_bars": sum(len(data.get("NQ", [])) for _, data in sessions),
        "aligned": True,
        "gaps": {"count": 0, "max_gap_seconds": 0},
        "warnings": [],
    }
    return sessions, "synthetic", provenance


def _price_offsets(settings: Settings, dataset: dict[str, Any]) -> dict[str, float]:
    """Offset acumulado de NQ por sesion en la serie adjusted.

    La estrategia calcula niveles en NQ y ejecuta en MNQ; ambos comparten el
    offset aplicado. Se usa NQ como referencia de redondeo porque es la serie
    sobre la que se construyen los niveles.
    """
    if settings.feed.series_mode != "adjusted":
        return {}
    manifest = dataset.get("manifest") or {}
    rolls = manifest.get("rolls") or []
    contracts_by_session = dataset.get("contracts_by_session") or {}
    if not rolls or not contracts_by_session:
        return {}
    cumulative = 0.0
    by_contract: dict[str, float] = {}
    for event in reversed(rolls):
        applied = event.get("applied_offsets") or {}
        offset = applied.get("NQ", applied.get("MNQ"))
        from_code = (event.get("from") or {}).get("NQ")
        if offset is None or not from_code:
            return {}
        cumulative += float(offset)
        by_contract[from_code] = cumulative
    return {
        day: by_contract[contracts["NQ"]]
        for day, contracts in contracts_by_session.items()
        if contracts.get("NQ") in by_contract
    }


def _simulate(
    settings: Settings,
    sessions: list[tuple[date, dict[str, list[Bar]]]],
    source: str,
    label: str,
    dataset: dict[str, Any],
) -> dict[str, Any]:
    execution = ExecutionEngine(settings, emit=lambda *a, **k: None, mode="backtest")
    risk = RiskManager(settings)
    strategy = ORBStrategy(settings, price_offsets=_price_offsets(settings, dataset))
    funnel = FunnelRecorder(settings)
    equity = settings.risk.initial_capital
    trades: list[dict] = []
    recorded: set[str] = set()
    equity_points: list[dict] = []
    day_records: list[dict] = []
    stop_cap_days: set[str] = set()
    no_stop_days: set[str] = set()
    qty_zero_days: set[str] = set()

    def collect(day_pnl: list[float], day_trades: list[int]) -> None:
        nonlocal equity
        for trade in execution.closed_trades:
            if trade.id in recorded:
                continue
            recorded.add(trade.id)
            trade_dict = trade.as_dict()
            if source == "csv":
                active = (dataset.get("contracts_by_session") or {}).get(
                    et_date(trade.entry_ts).isoformat(), {}
                )
                contract = active.get("MNQ")
                if contract:
                    trade_dict["contract"] = contract
                    trade_dict["expiry"] = (dataset.get("expiry_by_session") or {}).get(
                        et_date(trade.entry_ts).isoformat(), {}
                    ).get("MNQ")
                    trade_dict.setdefault("meta", {})["contract"] = contract
                    trade_dict["meta"]["expiry"] = trade_dict["expiry"]
            trades.append(trade_dict)
            equity += trade.pnl
            day_pnl[0] += trade.pnl
            day_trades[0] += 1
            equity_points.append({"ts": trade.exit_ts, "equity": round(equity, 2)})

    for day, data in sessions:
        nq_all = [b for b in data["NQ"] if et_date(b.ts) == day]
        mnq_all = [b for b in data["MNQ"] if et_date(b.ts) == day]
        es_all = [b for b in data["ES"] if et_date(b.ts) == day]
        if not nq_all or len(mnq_all) != len(nq_all) or len(es_all) != len(nq_all):
            funnel.skip(day)
            continue
        day_start_equity = equity
        day_pnl = [0.0]
        day_trades = [0]
        losses = [0]
        last_exit: int | None = None
        rejected: set[str] = set()
        seen: set[str] = set()

        for i, nq_bar in enumerate(nq_all):
            mnq_bar, es_bar = mnq_all[i], es_all[i]
            before = len(execution.closed_trades)
            execution.on_bar(mnq_bar)
            collect(day_pnl, day_trades)
            if len(execution.closed_trades) > before:
                last_exit = execution.closed_trades[-1].exit_ts
                losses[0] = losses[0] + 1 if execution.closed_trades[-1].pnl < 0 else 0

            if (
                settings.risk.close_at_session_end
                and execution.position
                and et_hm(nq_bar.ts, settings.orb.timezone) >= settings.risk.session_close_time
            ):
                execution.close(mnq_bar.close, nq_bar.ts + 60, "session_close")
                collect(day_pnl, day_trades)

            if execution.position or execution.pending_entry:
                continue
            if day_trades[0] >= settings.risk.max_trades_per_day:
                continue
            ts = nq_bar.ts + 60
            minute = et_minutes(ts, settings.orb.timezone)
            if minute < hm_to_minutes(settings.orb.end) or minute > hm_to_minutes(settings.risk.trade_window_end):
                continue
            if i + 1 >= len(nq_all):
                continue
            assess = strategy.evaluate(nq_all[:i + 1], es_all[:i + 1], True)
            funnel.observe(day, assess)
            if assess.reject_code == "stop_cap":
                stop_cap_days.add(day.isoformat())
            elif assess.reject_code == "no_stop":
                no_stop_days.add(day.isoformat())
            signal = assess.signal
            if signal is None or signal.id in rejected or signal.id in seen:
                continue
            decision = risk.evaluate(
                signal,
                equity=equity,
                open_positions=0,
                day_pnl=day_pnl[0],
                day_start_equity=day_start_equity,
                trades_today=day_trades[0],
                now_ts=ts,
                last_exit_ts=last_exit,
                consecutive_losses=losses[0],
                has_pending_entry=False,
            )
            if not decision.ok:
                funnel.reject_risk(day, decision)
                # El único rechazo que llega con stop_ticks > 0 es el sizing sin
                # contrato; los topes previos devuelven stop_ticks=0.
                if decision.qty < 1 and decision.stop_ticks > 0:
                    qty_zero_days.add(day.isoformat())
                rejected.add(signal.id)
                continue
            signal.qty = decision.qty
            signal.risk_amount = decision.risk_amount
            active = (dataset.get("contracts_by_session") or {}).get(
                et_date(nq_bar.ts).isoformat(), {}
            )
            if active.get("MNQ"):
                signal.meta["contract"] = active["MNQ"]
                signal.meta["expiry"] = (dataset.get("expiry_by_session") or {}).get(
                    et_date(nq_bar.ts).isoformat(), {}
                ).get("MNQ")
            execution.arm(signal)
            funnel.arm(day, decision)
            seen.add(signal.id)

        if execution.position:
            execution.close(nq_all[-1].close, nq_all[-1].ts + 60, "session_close")
            collect(day_pnl, day_trades)

        funnel.finish(day, nq_all)
        day_records.append(
            {
                "date": day.isoformat(),
                "pnl": round(day_pnl[0], 2),
                "trades": day_trades[0],
                "equity": round(equity, 2),
            }
        )

    funnel_summary = funnel.summary()
    metrics = compute_stats(
        trades,
        settings.risk.initial_capital,
        sessions=[day for day, _ in sessions],
    )
    exit_counts = Counter(str(t.get("exit_reason") or "unknown") for t in trades)
    stop_losses = exit_counts.get("stop_loss", 0)
    take_profits = exit_counts.get("take_profit", 0)
    stop_ticks = [
        abs(float(t["entry_price"]) - float(t["stop"])) / settings.execution.tick_size
        for t in trades
    ]
    metrics["exit_reasons"] = dict(sorted(exit_counts.items()))
    metrics["stop_losses"] = stop_losses
    metrics["take_profits"] = take_profits
    metrics["session_closes"] = exit_counts.get("session_close", 0)
    metrics["stop_loss_rate"] = round(stop_losses / len(trades) * 100, 2) if trades else 0.0
    metrics["take_profit_rate"] = round(take_profits / len(trades) * 100, 2) if trades else 0.0
    metrics["avg_stop_ticks"] = round(sum(stop_ticks) / len(stop_ticks), 1) if stop_ticks else 0.0
    metrics["signals"] = funnel_summary.get("signals", 0)
    metrics["retests"] = funnel_summary.get("retests", 0)
    metrics["breakouts"] = funnel_summary.get("breakouts", 0)
    # E-1: distribución por evento de las métricas de geometría de entrada y
    # stop directo. Es solo observabilidad; no participa en sizing ni fills.
    metrics["event_metrics"] = funnel_summary.get("event_metrics", {})
    metrics["stop_cap_sessions"] = len(stop_cap_days)
    metrics["no_stop_sessions"] = len(no_stop_days)
    metrics["qty_zero_sessions"] = len(qty_zero_days)
    ambiguity = execution.ambiguous_report()
    diagnostics = {
        "intrabar_model": {
            "stop_gap": "open_mas_slippage_adverso",
            "target_slippage": "slippage_adverso",
            "max_slippage_ticks": settings.execution.max_slippage_ticks,
            "ambiguous_bar": "stop_loss_first",
        },
        "ambiguous_bars": ambiguity,
    }
    metrics["ambiguous_bars"] = ambiguity["count"]
    metrics["days_traded"] = len(day_records)
    metrics["winning_days"] = sum(1 for d in day_records if d["pnl"] > 0)
    metrics["losing_days"] = sum(1 for d in day_records if d["pnl"] < 0)
    result = {
        "id": uuid.uuid4().hex[:16],
        "created_ts": int(time.time() * 1000),
        "label": label,
        "data_source": source,
        "data_quality": "historical" if source == "csv" else "simulated",
        "dataset_id": dataset.get("id"),
        "dataset": dataset,
        "data_range": dataset.get("selected_range"),
        "config": {
            "strategy": settings.strategy.model_dump(),
            "risk": settings.risk.model_dump(),
            "smt": settings.smt.model_dump(),
            "orb": settings.orb.model_dump(),
            "execution": settings.execution.model_dump(),
            "feed": settings.feed.model_dump(),
            "mode": settings.mode,
            "instrument": settings.instrument,
            "confirm_tf": settings.strategy.confirm_tf,
            "days": len(sessions),
        },
        "metrics": metrics,
        "diagnostics": diagnostics,
        "trades": trades,
        "equity": metrics["equity_curve"],
        "days_detail": day_records,
        "funnel": {
            "schema": FUNNEL_SCHEMA,
            "sessions": funnel.records(),
            "summary": funnel_summary,
        },
    }
    result["experiment"] = build_identity(settings, dataset).as_dict()
    # El assert se ejecuta en toda simulación (run_backtest, variantes y
    # presets): si los hashes no se recomputan desde el resultado, no se
    # devuelve una identidad que después paper podría aceptar por error.
    assert_result_identity(result, settings=settings)
    return result


def run_backtest(
    settings: Settings,
    days: int = 30,
    overrides: dict | None = None,
    label: str | None = None,
    start: date | None = None,
    *,
    allow_holdout: bool = False,
) -> dict[str, Any]:
    cfg = apply_settings(settings, overrides or {})
    sessions, source, dataset = prepare_dataset(
        cfg, days, start, allow_holdout=allow_holdout
    )
    result = _simulate(cfg, sessions, source, label or f"Backtest {len(sessions)} sesiones", dataset)
    result["overrides"] = overrides or {}
    result["is_synthetic"] = source != "csv"
    return result


def run_variants(
    settings: Settings,
    days: int = 20,
    overrides: dict | None = None,
    start: date | None = None,
    *,
    allow_holdout: bool = False,
) -> list[dict[str, Any]]:
    """Ejecuta las cuatro variantes sobre el MISMO dataset."""
    base = apply_settings(settings, overrides or {})
    sessions, source, dataset = prepare_dataset(
        base, days, start, allow_holdout=allow_holdout
    )
    results = []
    for key, (label, patch) in VARIANTS.items():
        cfg = apply_settings(base, patch)
        result = _simulate(cfg, sessions, source, label, dataset)
        result["variant"] = key
        result["is_synthetic"] = source != "csv"
        results.append(result)
    return results


def resolve_presets(keys: Sequence[str] | None = None) -> list[str]:
    """Valida claves y garantiza un baseline al inicio de la comparación."""
    requested = list(keys or DEFAULT_PRESETS)
    unknown = [key for key in requested if key != "all" and key not in PRESETS]
    if unknown:
        raise ValueError(f"Presets desconocidos: {', '.join(unknown)}")
    if "all" in requested:
        requested = list(PRESETS)
    ordered = ["baseline", *[key for key in requested if key != "baseline"]]
    return list(dict.fromkeys(ordered))


def preset_catalog() -> list[dict[str, Any]]:
    """Catálogo de presets para API/CLI, sin ejecutar el motor."""
    return [
        {
            "key": key,
            "label": preset["label"],
            "group": preset["group"],
            "description": preset["description"],
            "default": key in DEFAULT_PRESETS,
            "patch": preset["patch"],
        }
        for key, preset in PRESETS.items()
    ]


def _delta(value: float | int | None, base: float | int | None) -> float | None:
    if value is None or base is None:
        return None
    return round(float(value) - float(base), 2)


def _preset_row(result: dict[str, Any]) -> dict[str, Any]:
    metrics = result["metrics"]
    config = result["config"]
    strategy = config.get("strategy") or {}
    smt = config.get("smt") or {}
    risk = config.get("risk") or {}
    curve = result.get("equity") or []
    final_equity = curve[-1]["equity"] if curve else None
    return {
        "result_id": result["id"],
        "preset": result["preset"],
        "label": result["preset_label"],
        "group": result["preset_group"],
        "description": result["preset_description"],
        "is_synthetic": result.get("is_synthetic", False),
        "trades": metrics["trades"],
        "signals": metrics.get("signals", 0),
        "breakouts": metrics.get("breakouts", 0),
        "retests": metrics.get("retests", 0),
        "days_traded": metrics.get("days_traded", 0),
        "win_rate": metrics["win_rate"],
        "profit_factor": metrics["profit_factor"],
        "expectancy": metrics["expectancy"],
        "net_profit": metrics["net_profit"],
        "max_drawdown": metrics["max_drawdown"],
        "max_drawdown_pct": metrics["max_drawdown_pct"],
        "avg_r": metrics["avg_r"],
        "total_r": metrics["total_r"],
        "sharpe": metrics["sharpe"],
        "sortino": metrics["sortino"],
        "stop_losses": metrics.get("stop_losses", 0),
        "take_profits": metrics.get("take_profits", 0),
        "session_closes": metrics.get("session_closes", 0),
        "stop_loss_rate": metrics.get("stop_loss_rate", 0.0),
        "take_profit_rate": metrics.get("take_profit_rate", 0.0),
        "avg_stop_ticks": metrics.get("avg_stop_ticks", 0.0),
        "stop_cap_sessions": metrics.get("stop_cap_sessions", 0),
        "qty_zero_sessions": metrics.get("qty_zero_sessions", 0),
        "final_equity": final_equity,
        "config": {
            "entry_reference": strategy.get("entry_reference"),
            "or_retracement_pct": strategy.get("or_retracement_pct"),
            "retest_tolerance_ticks": strategy.get("retest_tolerance_ticks"),
            "setup_validity_minutes": strategy.get("setup_validity_minutes"),
            "require_recovery_close": strategy.get("require_recovery_close"),
            "entry_trigger": strategy.get("entry_trigger"),
            "structural_depth": strategy.get("structural_depth"),
            "sl_buffer_ticks": strategy.get("sl_buffer_ticks"),
            "max_sl_ticks": risk.get("max_sl_ticks"),
            "risk_per_trade_pct": risk.get("risk_per_trade_pct"),
            "max_contracts": risk.get("max_contracts"),
            "tp_rr": strategy.get("tp_rr"),
            "smt_window_minutes": smt.get("window_minutes"),
            "smt_tolerance_ticks": smt.get("tolerance_ticks"),
        },
        "equity": curve,
    }


def preset_comparison(results: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Tabla compacta con deltas frente al baseline (siempre incluido)."""
    rows = [_preset_row(result) for result in results]
    base = next((row for row in rows if row["preset"] == "baseline"), rows[0] if rows else None)
    if base is None:
        return rows
    keys = (
        "trades",
        "signals",
        "retests",
        "win_rate",
        "profit_factor",
        "expectancy",
        "net_profit",
        "max_drawdown",
        "avg_r",
        "stop_losses",
        "avg_stop_ticks",
        "stop_cap_sessions",
        "qty_zero_sessions",
    )
    for row in rows:
        row["delta"] = (
            {}
            if row["preset"] == "baseline"
            else {key: _delta(row.get(key), base.get(key)) for key in keys}
        )
    return rows


SAMPLE_MIN_SESSIONS = 3


def preset_sample(
    comparison: Sequence[dict[str, Any]],
    sessions: int,
    days_requested: int,
) -> dict[str, Any]:
    """Clasifica la muestra para no leer ceros como evidencia.

    - ``insufficient``: la ventana no reúne el mínimo de sesiones evaluadas.
    - ``no_trades``: hay muestra suficiente pero ningún preset operó.
    - ``activity``: al menos un preset registró operaciones.
    """
    total = len(comparison)
    active = sum(1 for row in comparison if int(row.get("trades") or 0) > 0)
    if total == 0 or sessions < SAMPLE_MIN_SESSIONS:
        status = "insufficient"
        detail = (
            f"Solo se evaluaron {sessions} de {SAMPLE_MIN_SESSIONS} sesiones mínimas. "
            "Los deltas no permiten comparar presets; amplía la ventana o cambia la fecha."
        )
    elif active == 0:
        status = "no_trades"
        detail = (
            f"Ninguno de los {total} presets operó en {sessions} sesiones. "
            "Los ceros no distinguen variantes; amplía la ventana o cambia la fecha."
        )
    else:
        status = "activity"
        detail = (
            f"{active} de {total} presets operan en {sessions} sesiones. "
            "Los deltas comparan variantes sobre el mismo dataset."
        )
    return {
        "status": status,
        "active_presets": active,
        "total_presets": total,
        "sessions": sessions,
        "days_requested": days_requested,
        "min_sessions": SAMPLE_MIN_SESSIONS,
        "detail": detail,
    }


def run_presets(
    settings: Settings,
    days: int = 20,
    presets: Sequence[str] | None = None,
    overrides: dict | None = None,
    start: date | None = None,
    *,
    allow_holdout: bool = False,
) -> dict[str, Any]:
    """Ejecuta presets aislados sobre el MISMO dataset y devuelve deltas.

    El baseline se añade siempre para que cada fila tenga una referencia
    comparable. ``allow_holdout`` queda reservado a la ruta confirmatoria; esta
    función no se usa para el holdout.
    """
    base = apply_settings(settings, overrides or {})
    keys = resolve_presets(presets)
    default_presets = not presets
    sessions, source, dataset = prepare_dataset(
        base, days, start, allow_holdout=allow_holdout
    )
    results: list[dict[str, Any]] = []
    for key in keys:
        preset = PRESETS[key]
        cfg = apply_settings(base, preset["patch"])
        result = _simulate(cfg, sessions, source, preset["label"], dataset)
        result["preset"] = key
        result["preset_label"] = preset["label"]
        result["preset_group"] = preset["group"]
        result["preset_description"] = preset["description"]
        result["preset_patch"] = preset["patch"]
        result["is_synthetic"] = source != "csv"
        results.append(result)
    comparison = preset_comparison(results)
    return {
        "created_ts": int(time.time() * 1000),
        "data_source": source,
        "is_synthetic": source != "csv",
        "dataset": dataset,
        "dataset_id": dataset.get("id"),
        "days_requested": days,
        "sessions": len(sessions),
        "overrides": overrides or {},
        "base_config": base.model_dump(),
        "default_presets": default_presets,
        "preset_keys": keys,
        "results": results,
        "comparison": comparison,
        "sample": preset_sample(comparison, len(sessions), days),
    }


def _preset_cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compara presets de frecuencia/SL sobre el mismo dataset. "
            "No ejecuta el holdout ni cambia la configuración activa."
        )
    )
    parser.add_argument("--days", type=int, default=20, help="Sesiones a evaluar (3-250).")
    parser.add_argument("--start", default=None, help="Fecha mínima YYYY-MM-DD.")
    parser.add_argument(
        "--preset",
        action="append",
        default=[],
        help="Clave de preset; se puede repetir. Sin argumento usa los presets default.",
    )
    parser.add_argument("--all", action="store_true", help="Ejecuta todos los presets del catálogo.")
    parser.add_argument("--out", default=None, help="JSON de salida.")
    parser.add_argument("--full", action="store_true", help="Incluye trades, funnel y detalle completo.")
    args = parser.parse_args(argv)

    try:
        start = date.fromisoformat(args.start) if args.start else None
        keys = ["all"] if args.all else (args.preset or None)
        payload = run_presets(load_settings(), args.days, keys, start=start)
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}")
        return 2

    stamp = time.strftime("%Y%m%d_%H%M%S")
    target = Path(args.out) if args.out else BASE_DIR / "reports/backtest" / f"presets_{stamp}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if args.full:
        output = payload
    else:
        output = {
            key: payload[key]
            for key in (
                "created_ts",
                "data_source",
                "is_synthetic",
                "dataset",
                "dataset_id",
                "days_requested",
                "sessions",
                "overrides",
                "base_config",
                "default_presets",
                "preset_keys",
                "comparison",
                "sample",
            )
        }
    target.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print(
        f"{payload['sessions']} sesiones · {payload['data_source']} · "
        f"{len(payload['comparison'])} presets -> {target}"
    )
    print(
        f"{'preset':<24} {'ops':>4} {'señales':>7} {'WR%':>7} {'PF':>7} "
        f"{'exp$':>9} {'neto$':>9} {'DD$':>8} {'SL':>4} {'ST ticks':>8} {'caps':>5} {'qty0':>5}"
    )
    for row in payload["comparison"]:
        pf = "inf" if row["profit_factor"] is None else f"{row['profit_factor']:.2f}"
        print(
            f"{row['preset']:<24} {row['trades']:>4} {row['signals']:>7} "
            f"{row['win_rate']:>7.1f} {pf:>7} {row['expectancy']:>9.2f} "
            f"{row['net_profit']:>9.2f} {row['max_drawdown']:>8.2f} "
            f"{row['stop_losses']:>4} {row['avg_stop_ticks']:>8.1f} "
            f"{row['stop_cap_sessions']:>5} {row['qty_zero_sessions']:>5}"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_preset_cli())
