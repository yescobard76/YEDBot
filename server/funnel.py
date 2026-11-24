"""Embudo de decisión persistente para el backtest.

El módulo observa los ``Assess`` que el motor ya calcula y produce un registro
por sesión. No evalúa la estrategia por su cuenta, no decide y no altera el
resultado: es un canal de observación determinista.

Cada registro responde a las preguntas que antes exigían barridos manuales:

- hasta qué fase llegó la sesión (OR, ruptura, SMT, retesteo, señal, operación);
- por qué terminó sin operar (código estructurado, no texto de UI);
- cuánto se alejó el precio del 50 % del Opening Range (distancia al mid);
- qué excursión favorable y adversa hubo desde la confirmación de ruptura
  (MFE/MAE en puntos y ticks).

El registro viaja dentro de cada resultado de backtest (``result["funnel"]``),
de modo que los JSON de bloque ya lo conservan. ``write_csv`` y la CLI
``python -m server.funnel`` lo consolidan sin volver a ejecutar el motor.

Uso::

    python -m server.funnel --input reports/backtest/W1.json \\
        --out reports/backtest/funnel_W1.csv

    python -m server.funnel --input reports/backtest/W1.json \\
        --input reports/backtest/W2.json --out reports/backtest/funnel.csv \\
        --summary reports/backtest/funnel_summary.json
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Sequence

from .config import Settings
from .models import Bar

FUNNEL_SCHEMA = "funnel-v1"

STAGES: tuple[str, ...] = (
    "sin_datos",
    "or",
    "ruptura",
    "smt",
    "retesteo",
    "senal",
    "operado",
)

CSV_FIELDS: tuple[str, ...] = (
    "date",
    "stage",
    "terminal_reason",
    "or_valid",
    "or_reject",
    "direction",
    "breakout_ts",
    "breakout_confirm_ts",
    "breakout_close",
    "breakout_level",
    "event_id",
    "retest_distance_ticks",
    "direct_stop_ticks",
    "direct_stop_cap_binding",
    "entry_delay_min",
    "stop_cap_binding",
    "smt_status",
    "smt_seen",
    "smt_recovery_ts",
    "retest_seen",
    "retest_level",
    "retest_touch_ts",
    "signal_ts",
    "entry_price",
    "stop",
    "stop_ticks",
    "risk_ok",
    "risk_reason",
    "traded",
    "reject_code",
    "reject_detail",
    "setup_expires_ts",
    "bars_after_breakout",
    "mfe_pts",
    "mae_pts",
    "mfe_ticks",
    "mae_ticks",
    "distance_to_mid_at_breakout_pts",
    "closest_to_mid_pts",
    "closest_to_mid_ticks",
    "touched_mid",
)


def _max_stage(current: str, candidate: str) -> str:
    return candidate if STAGES.index(candidate) > STAGES.index(current) else current


def _new_record(day: str, smt_required: bool) -> dict[str, Any]:
    return {
        "date": day,
        "stage": "sin_datos",
        "terminal_reason": "sin_datos",
        "or_valid": None,
        "or_reject": None,
        "opening_range": None,
        "breakout": None,
        "wick": None,
        "false_breakout": False,
        "false_breakout_ts": None,
        # Métricas E-1 por evento. Se rellenan desde Assess.event_metrics; no
        # intervienen en ninguna decisión ni en el resultado del backtest.
        "event_id": None,
        "retest_distance_ticks": None,
        "direct_stop_ticks": None,
        "direct_stop_cap_binding": None,
        "entry_delay_min": None,
        "stop_cap_binding": False,
        "smt_required": smt_required,
        "smt_status": "no_evaluada",
        "smt_seen": False,
        "smt_expired_seen": False,
        "smt_recovery_pending_seen": False,
        "smt_matching_seen": False,
        "smt": None,
        "retest_seen": False,
        "retest": None,
        "signal": None,
        "risk": None,
        "traded": False,
        "reject_code": None,
        "reject_detail": None,
        "reject_ts": None,
        "setup_expires_ts": None,
        "bars_after_breakout": 0,
        "mfe_pts": None,
        "mae_pts": None,
        "mfe_ticks": None,
        "mae_ticks": None,
        "mfe_ts": None,
        "mae_ts": None,
        "distance_to_mid_at_breakout_pts": None,
        "closest_to_mid_pts": None,
        "closest_to_mid_ticks": None,
        "closest_to_mid_ts": None,
        "touched_mid": None,
        "session_last_ts": None,
    }


class FunnelRecorder:
    """Acumula el estado de cada sesión a partir de los ``Assess`` del motor."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.tick = float(settings.execution.tick_size)
        self.smt_required = bool(settings.strategy.use_smt and settings.smt.enabled)
        self._records: dict[str, dict[str, Any]] = {}
        self._order: list[str] = []

    # ------------------------------------------------------------------ helpers
    def _record(self, day: str) -> dict[str, Any]:
        record = self._records.get(day)
        if record is None:
            record = _new_record(day, self.smt_required)
            self._records[day] = record
            self._order.append(day)
        return record

    def skip(self, day: date) -> None:
        """Sesión evaluada por el calendario pero sin barras utilizables."""
        self._record(day.isoformat())

    # ------------------------------------------------------------------ observe
    def observe(self, day: date, assess: Any) -> None:
        record = self._record(day.isoformat())

        if assess.opening_range:
            record["opening_range"] = assess.opening_range
        if assess.reject_code in ("or_too_wide", "or_too_narrow"):
            record["or_valid"] = False
            record["or_reject"] = assess.reject
        elif (
            record["or_valid"] is None
            and assess.opening_range
            and assess.opening_range.get("complete")
        ):
            record["or_valid"] = True
        if assess.opening_range and assess.opening_range.get("complete"):
            record["stage"] = _max_stage(record["stage"], "or")

        breakout = assess.breakout
        if breakout:
            if breakout.get("rejected"):
                if record["wick"] is None:
                    record["wick"] = {
                        key: breakout.get(key)
                        for key in ("direction", "level", "close", "ts", "confirm_ts", "type")
                    }
            elif record["breakout"] is None:
                record["breakout"] = {
                    key: breakout.get(key)
                    for key in (
                        "direction",
                        "level",
                        "open",
                        "close",
                        "high",
                        "low",
                        "ts",
                        "confirm_ts",
                        "timeframe",
                        "type",
                    )
                }
                record["stage"] = _max_stage(record["stage"], "ruptura")
                record["setup_expires_ts"] = int(breakout["confirm_ts"]) + (
                    int(self.settings.strategy.setup_validity_minutes) * 60
                )
            if breakout.get("failed"):
                record["false_breakout"] = True
                record["false_breakout_ts"] = breakout.get("failed_ts")

        event_metrics = getattr(assess, "event_metrics", {}) or {}
        if event_metrics:
            record["event_id"] = event_metrics.get("event_id") or record["event_id"]
            for key in ("retest_distance_ticks", "direct_stop_ticks", "entry_delay_min"):
                value = event_metrics.get(key)
                if value is not None:
                    record[key] = value
            record["stop_cap_binding"] = bool(event_metrics.get("stop_cap_binding", False))
            if record["direct_stop_ticks"] is not None:
                record["direct_stop_cap_binding"] = (
                    record["direct_stop_ticks"] > self.settings.risk.max_sl_ticks
                )

        diagnostics = assess.smt_diagnostics or {}
        if diagnostics.get("enabled") is False:
            record["smt_status"] = "desactivada"
        elif assess.smt:
            record["smt_seen"] = True
            record["smt"] = assess.smt
            record["smt_status"] = "confirmada"
            record["stage"] = _max_stage(record["stage"], "smt")
        else:
            if diagnostics.get("expired_before_recovery"):
                record["smt_expired_seen"] = True
            if diagnostics.get("pending_recovery"):
                record["smt_recovery_pending_seen"] = True
            if diagnostics.get("matching"):
                record["smt_matching_seen"] = True
            if not record["smt_seen"] and diagnostics.get("enabled"):
                if record["smt_expired_seen"]:
                    record["smt_status"] = "caducada"
                elif record["smt_recovery_pending_seen"]:
                    record["smt_status"] = "esperando_recuperacion"
                elif record["smt_matching_seen"]:
                    record["smt_status"] = "sin_recuperacion"
                else:
                    record["smt_status"] = "sin_divergencia"

        if assess.retest:
            record["retest_seen"] = True
            record["retest"] = assess.retest
            record["stage"] = _max_stage(record["stage"], "retesteo")

        if assess.signal and record["signal"] is None:
            signal = assess.signal
            record["signal"] = {
                "id": signal.id,
                "ts": signal.ts,
                "direction": signal.direction,
                "entry_price": signal.entry_price,
                "stop": signal.stop,
                "target": signal.target,
                "stop_ticks": signal.meta.get("stop_ticks"),
                "signal_type": signal.signal_type,
                "breakout_ts": signal.meta.get("breakout_ts"),
                "retest_ts": signal.meta.get("retest_ts"),
                "direct_entry": signal.meta.get("direct_entry"),
                "event_id": signal.meta.get("event_id"),
                "retest_distance_ticks": signal.meta.get("retest_distance_ticks"),
                "direct_stop_ticks": signal.meta.get("direct_stop_ticks"),
                "entry_delay_min": signal.meta.get("entry_delay_min"),
            }
            record["stage"] = _max_stage(record["stage"], "senal")

        if assess.reject:
            record["reject_detail"] = assess.reject
            record["reject_code"] = assess.reject_code
            record["reject_ts"] = assess.reject_ts

    # ------------------------------------------------------------- risk / fills
    def reject_risk(self, day: date, decision: Any) -> None:
        record = self._record(day.isoformat())
        record["risk"] = {
            "ok": False,
            "reason": decision.reason,
            "qty": decision.qty,
            "stop_ticks": round(float(decision.stop_ticks), 1),
            "risk_amount": decision.risk_amount,
        }

    def arm(self, day: date, decision: Any) -> None:
        record = self._record(day.isoformat())
        record["risk"] = {
            "ok": True,
            "reason": "",
            "qty": decision.qty,
            "stop_ticks": round(float(decision.stop_ticks), 1),
            "risk_amount": decision.risk_amount,
        }
        record["traded"] = True
        record["stage"] = _max_stage(record["stage"], "operado")

    # ------------------------------------------------------------------- finish
    def finish(self, day: date, bars: Sequence[Bar]) -> None:
        """Cierra la sesión y calcula excursiones desde la confirmación."""
        record = self._record(day.isoformat())
        record["session_last_ts"] = bars[-1].ts if bars else None
        breakout = record["breakout"]
        if breakout:
            self._excursions(record, breakout, bars)
        record["terminal_reason"] = self._terminal(record)

    def _excursions(
        self,
        record: dict[str, Any],
        breakout: dict[str, Any],
        bars: Sequence[Bar],
    ) -> None:
        confirm_ts = int(breakout["confirm_ts"])
        after = [bar for bar in bars if bar.ts >= confirm_ts]
        record["bars_after_breakout"] = len(after)
        base = float(breakout["close"])
        direction = breakout["direction"]
        mid = (record["opening_range"] or {}).get("mid")
        if mid is not None:
            record["distance_to_mid_at_breakout_pts"] = round(
                (base - mid) if direction == "long" else (mid - base), 2
            )
        if not after:
            return

        high_bar = max(after, key=lambda bar: bar.high)
        low_bar = min(after, key=lambda bar: bar.low)
        if direction == "long":
            mfe = high_bar.high - base
            mae = base - low_bar.low
            closest = (low_bar.low - mid) if mid is not None else None
            mfe_ts, mae_ts, closest_ts = high_bar.ts, low_bar.ts, low_bar.ts
        else:
            mfe = base - low_bar.low
            mae = high_bar.high - base
            closest = (mid - high_bar.high) if mid is not None else None
            mfe_ts, mae_ts, closest_ts = low_bar.ts, high_bar.ts, high_bar.ts

        record["mfe_pts"] = round(max(mfe, 0.0), 2)
        record["mae_pts"] = round(max(mae, 0.0), 2)
        record["mfe_ticks"] = round(max(mfe, 0.0) / self.tick, 1)
        record["mae_ticks"] = round(max(mae, 0.0) / self.tick, 1)
        record["mfe_ts"] = mfe_ts
        record["mae_ts"] = mae_ts
        if closest is not None:
            record["closest_to_mid_pts"] = round(closest, 2)
            record["closest_to_mid_ticks"] = round(closest / self.tick, 1)
            record["closest_to_mid_ts"] = closest_ts
            record["touched_mid"] = bool(closest <= 0)

    def _terminal(self, record: dict[str, Any]) -> str:
        if record["stage"] == "sin_datos":
            return "sin_datos"
        if record["or_valid"] is False:
            return "or_invalido"
        opening_range = record["opening_range"] or {}
        if not opening_range.get("complete"):
            return "or_incompleto"
        if record["breakout"] is None:
            return "ruptura_sin_confirmacion" if record["wick"] else "sin_ruptura"
        if record["traded"]:
            return "operado"
        risk = record["risk"]
        if record["signal"] is not None and risk and not risk.get("ok"):
            return "riesgo_rechazado"

        code = record["reject_code"]
        if code == "false_breakout":
            return "falso_rompimiento"
        if code == "stop_cap":
            return "stop_cap"
        if code == "outside_window":
            return "fuera_ventana"
        if code == "no_stop":
            return "sin_stop"
        if code == "setup_expired":
            if record["retest_seen"]:
                return "setup_expirado_tras_retesteo"
            if record["smt_seen"]:
                return "setup_expirado_con_smt_sin_retesteo"
            if record["smt_expired_seen"]:
                return "setup_expirado_smt_caducada"
            if record["smt_recovery_pending_seen"]:
                return "setup_expirado_smt_sin_recuperacion"
            if record["smt_required"]:
                return "setup_expirado_sin_smt"
            return "setup_expirado_sin_retesteo"
        if record["signal"] is not None:
            return "senal_sin_ejecutar"
        if record["retest_seen"]:
            return "entrada_sin_confirmar"
        return "sin_retesteo_al_cierre"

    # ------------------------------------------------------------------ outputs
    def records(self) -> list[dict[str, Any]]:
        return [self._records[key] for key in self._order]

    def summary(self) -> dict[str, Any]:
        return summarize_funnel(self.records())


# --------------------------------------------------------------------- summary
def _percentile(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _describe(values: Iterable[Any]) -> dict[str, Any]:
    clean = [float(value) for value in values if isinstance(value, (int, float))]
    if not clean:
        return {"count": 0, "median": None, "p90": None, "max": None}
    return {
        "count": len(clean),
        "median": round(statistics.median(clean), 2),
        "p90": round(_percentile(clean, 0.9), 2),
        "max": round(max(clean), 2),
    }


def summarize_funnel(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Resumen del embudo y de la cohorte de rupturas sin retesteo."""
    no_retest = [
        record for record in records if record.get("breakout") and not record.get("retest_seen")
    ]
    events = [record for record in records if record.get("event_id")]
    return {
        "schema": FUNNEL_SCHEMA,
        "sessions": len(records),
        "with_data": sum(1 for record in records if record["stage"] != "sin_datos"),
        "or_valid": sum(1 for record in records if record["or_valid"] is True),
        "breakouts": sum(1 for record in records if record["breakout"]),
        "smt_confirmed": sum(1 for record in records if record["smt_seen"]),
        "retests": sum(1 for record in records if record["retest_seen"]),
        "signals": sum(1 for record in records if record["signal"]),
        "traded": sum(1 for record in records if record["traded"]),
        "by_stage": dict(Counter(record["stage"] for record in records)),
        "by_terminal_reason": dict(Counter(record["terminal_reason"] for record in records)),
        "by_smt_status": dict(Counter(record["smt_status"] for record in records)),
        "breakouts_by_direction": dict(
            Counter(record["breakout"]["direction"] for record in records if record["breakout"])
        ),
        "event_metrics": {
            "events": len(events),
            "signals": sum(1 for record in events if record.get("signal")),
            "traded": sum(1 for record in events if record.get("traded")),
            "retest_distance_ticks": _describe(
                record.get("retest_distance_ticks") for record in events
            ),
            "direct_stop_ticks": _describe(
                record.get("direct_stop_ticks") for record in events
            ),
            "entry_delay_min": _describe(
                record.get("entry_delay_min") for record in events
            ),
            "direct_stop_cap_binding": sum(
                1 for record in events if record.get("direct_stop_cap_binding")
            ),
            "stop_cap_binding": sum(
                1 for record in events if record.get("stop_cap_binding")
            ),
        },
        "no_retest": {
            "count": len(no_retest),
            "with_smt": sum(1 for record in no_retest if record["smt_seen"]),
            "by_direction": dict(
                Counter(record["breakout"]["direction"] for record in no_retest)
            ),
            "by_terminal_reason": dict(
                Counter(record["terminal_reason"] for record in no_retest)
            ),
            "mfe_pts": _describe(record["mfe_pts"] for record in no_retest),
            "mae_pts": _describe(record["mae_pts"] for record in no_retest),
            "closest_to_mid_pts": _describe(
                record["closest_to_mid_pts"] for record in no_retest
            ),
            "mfe_ge_100_pts": sum(
                1 for record in no_retest if (record["mfe_pts"] or 0) >= 100
            ),
            "mfe_ge_100_and_mae_le_50_pts": sum(
                1
                for record in no_retest
                if (record["mfe_pts"] or 0) >= 100 and (record["mae_pts"] or 0) <= 50
            ),
            "mfe_ge_200_and_mae_le_50_pts": sum(
                1
                for record in no_retest
                if (record["mfe_pts"] or 0) >= 200 and (record["mae_pts"] or 0) <= 50
            ),
            "reached_mid": sum(1 for record in no_retest if record["touched_mid"]),
        },
    }


# ------------------------------------------------------------------------ csv
def _csv_row(record: dict[str, Any]) -> dict[str, Any]:
    breakout = record.get("breakout") or {}
    smt = record.get("smt") or {}
    retest = record.get("retest") or {}
    signal = record.get("signal") or {}
    risk = record.get("risk") or {}
    return {
        "date": record.get("date"),
        "stage": record.get("stage"),
        "terminal_reason": record.get("terminal_reason"),
        "or_valid": record.get("or_valid"),
        "or_reject": record.get("or_reject"),
        "direction": breakout.get("direction"),
        "breakout_ts": breakout.get("ts"),
        "breakout_confirm_ts": breakout.get("confirm_ts"),
        "breakout_close": breakout.get("close"),
        "breakout_level": breakout.get("level"),
        "event_id": record.get("event_id"),
        "retest_distance_ticks": record.get("retest_distance_ticks"),
        "direct_stop_ticks": record.get("direct_stop_ticks"),
        "direct_stop_cap_binding": record.get("direct_stop_cap_binding"),
        "entry_delay_min": record.get("entry_delay_min"),
        "stop_cap_binding": record.get("stop_cap_binding"),
        "smt_status": record.get("smt_status"),
        "smt_seen": record.get("smt_seen"),
        "smt_recovery_ts": smt.get("confirm_ts"),
        "retest_seen": record.get("retest_seen"),
        "retest_level": retest.get("level"),
        "retest_touch_ts": retest.get("touch_ts"),
        "signal_ts": signal.get("ts"),
        "entry_price": signal.get("entry_price"),
        "stop": signal.get("stop"),
        "stop_ticks": signal.get("stop_ticks"),
        "risk_ok": risk.get("ok"),
        "risk_reason": risk.get("reason"),
        "traded": record.get("traded"),
        "reject_code": record.get("reject_code"),
        "reject_detail": record.get("reject_detail"),
        "setup_expires_ts": record.get("setup_expires_ts"),
        "bars_after_breakout": record.get("bars_after_breakout"),
        "mfe_pts": record.get("mfe_pts"),
        "mae_pts": record.get("mae_pts"),
        "mfe_ticks": record.get("mfe_ticks"),
        "mae_ticks": record.get("mae_ticks"),
        "distance_to_mid_at_breakout_pts": record.get("distance_to_mid_at_breakout_pts"),
        "closest_to_mid_pts": record.get("closest_to_mid_pts"),
        "closest_to_mid_ticks": record.get("closest_to_mid_ticks"),
        "touched_mid": record.get("touched_mid"),
    }


def write_csv(records: Sequence[dict[str, Any]], path: str | Path) -> Path:
    """Escribe una fila por sesión; no recalcula nada."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow(_csv_row(record))
    return target


# ------------------------------------------------------------------------ cli
def _load_results(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, dict) and isinstance(payload.get("variants"), list):
        return list(payload["variants"])
    if isinstance(payload, list):
        return list(payload)
    if isinstance(payload, dict) and "funnel" in payload:
        return [payload]
    raise ValueError(f"{path} no contiene resultados de backtest con embudo")


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Consolida el embudo de backtest sin volver a ejecutar el motor."
    )
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        help="JSON de resultados (W1.json, holdout.json, ...). Se puede repetir.",
    )
    parser.add_argument(
        "--out",
        default="reports/backtest/funnel.csv",
        help="CSV de salida",
    )
    parser.add_argument(
        "--summary",
        default=None,
        help="JSON opcional con el resumen por variante",
    )
    args = parser.parse_args(argv)

    rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for raw in args.input:
        path = Path(raw)
        for result in _load_results(path):
            funnel = result.get("funnel")
            if not funnel:
                continue
            variant = result.get("variant") or "single"
            records = funnel.get("sessions") or []
            for record in records:
                rows.append({"variant": variant, "source": path.stem, **record})
            summaries.append(
                {
                    "source": path.stem,
                    "variant": variant,
                    "summary": funnel.get("summary") or summarize_funnel(records),
                }
            )

    if not rows:
        raise SystemExit("No se encontraron registros de embudo en las entradas")

    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    fields = ("variant", "source", *CSV_FIELDS)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(_csv_row(row) | {"variant": row["variant"], "source": row["source"]})

    if args.summary:
        summary_path = Path(args.summary)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(summaries, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    print(f"{len(rows)} sesiones -> {target}")
    for item in summaries:
        summary = item["summary"]
        print(
            f"  {item['source']}/{item['variant']}: "
            f"{summary['sessions']} sesiones, {summary['breakouts']} rupturas, "
            f"{summary['no_retest']['count']} sin retesteo"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
