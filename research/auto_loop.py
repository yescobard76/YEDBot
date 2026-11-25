"""Bucle autónomo de investigación de YEDBot (para dejar la laptop AFK).

Qué hace
--------
Evalúa variantes de estrategia, una palanca cada vez, sobre las ventanas
W1-W6 (2025-01-10 .. 2026-06-30) con el mismo CSV `adjusted` que usa el 8765.
Después combina las mejores y deja un ranking en
`reports/autoloop/resumen_bucle.md`. El informe consolidado de la misión vive
en `reports/autoloop/resumen.md` y este bucle no lo sobrescribe.

Qué NO hace
-----------
- No toca `data/config.json` ni `profiles/*/config.json`.
- No escribe en la base SQLite ni reinicia el proceso del 8765.
- No lee el holdout (2026-07-01 en adelante).
- No adopta nada: solo mide y ordena; la adopción exige forward y decisión humana.

Control
-------
- `reports/autoloop/STOP`   -> termina el bucle en el siguiente punto seguro.
- `reports/autoloop/PAUSA`  -> espera sin lanzar simulaciones.
- `reports/autoloop/estado.json` -> latido con fase, variante y ventana.
- `reports/autoloop/runner.log`  -> registro.

El proceso se pone a prioridad IDLE y se autolimita si la RAM libre baja de
900 MB, para no competir con la interfaz.
"""

from __future__ import annotations

import ctypes
import json
import sys
import time
import traceback
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "autoloop"
BT = ROOT / "reports" / "backtest"
for p in (ROOT, BT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from _windows import WINDOWS  # noqa: E402

from server.backtest import _simulate, prepare_dataset  # noqa: E402
from server.config import Settings, apply_settings  # noqa: E402
from server.stats import compute_stats  # noqa: E402

INITIAL_CAPITAL = 25_000.0
MIN_FREE_RAM_MB = 900
SLEEP_BETWEEN = 3


# --------------------------------------------------------------------------
# Cola de variantes: una palanca por entrada, con una razón económica.
# --------------------------------------------------------------------------
def default_queue() -> list[dict]:
    return [
        {"id": "manual_base", "patch": {}, "why": "control: configuración viva 10/300/210/24"},
        {"id": "sl_200", "patch": {"risk": {"max_sl_ticks": 200}},
         "why": "recorta la cola de stops profundos; ya medido como P2 en W1-W6"},
        {"id": "sl_250", "patch": {"risk": {"max_sl_ticks": 250}},
         "why": "término medio entre el 300 vivo y el 200 histórico"},
        {"id": "rr_2_5", "patch": {"strategy": {"tp_rr": 2.5}},
         "why": "objetivo más cercano: sube el acierto y reduce el tiempo en mercado"},
        {"id": "rr_3_5", "patch": {"strategy": {"tp_rr": 3.5}},
         "why": "objetivo más lejano: menos aciertos, más R por ganador"},
        {"id": "tol_18", "patch": {"strategy": {"retest_tolerance_ticks": 18}},
         "why": "zona de retesteo intermedia: más entradas que 12, menos que 24"},
        {"id": "validity_180", "patch": {"strategy": {"setup_validity_minutes": 180}},
         "why": "caduca el setup antes; evita entradas tardías de la sesión"},
        {"id": "contracts_7", "patch": {"risk": {"max_contracts": 7}},
         "why": "menos apalancamiento que 10, manteniendo el 1 % de riesgo"},
        {"id": "sl_buffer_8", "patch": {"strategy": {"sl_buffer_ticks": 8}},
         "why": "más holgura al stop estructural; menos stops por ruido"},
        {"id": "excl_1130_1330", "patch": {"risk": {"entry_exclusion_start": "11:30",
                                                   "entry_exclusion_end": "13:30"}},
         "why": "evita la pausa del mediodía, donde el ORB pierde tracción"},
        {"id": "daily_loss_2", "patch": {"risk": {"max_daily_loss_pct": 2.0}},
         "why": "corta antes un día malo; menos DD, posible coste en neto"},
        {"id": "range_min_15", "patch": {"strategy": {"min_range_ticks": 15}},
         "why": "descarta rangos estrechos, que generan señales de baja calidad"},
    ]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(msg: str) -> None:
    line = f"{now()} {msg}"
    print(line, flush=True)
    with (OUT / "runner.log").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def idle_priority() -> None:
    try:
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        ctypes.windll.kernel32.SetPriorityClass(handle, 0x00000040)  # IDLE
    except Exception:
        pass


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def free_ram_mb() -> int:
    try:
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return int(stat.ullAvailPhys // (1024 * 1024))
    except Exception:
        return 10_000


def stop_requested() -> bool:
    return (OUT / "STOP").exists()


def paused() -> bool:
    return (OUT / "PAUSA").exists()


def wait_while_paused_and_loaded() -> None:
    while not stop_requested() and (paused() or free_ram_mb() < MIN_FREE_RAM_MB):
        write_state(phase="espera", detail={"ram_mb": free_ram_mb(),
                                            "pausa": paused()})
        time.sleep(45)


def write_state(*, phase: str, detail: dict | None = None) -> None:
    payload = {
        "ts": now(),
        "pid": __import__("os").getpid(),
        "phase": phase,
        "free_ram_mb": free_ram_mb(),
        **(detail or {}),
    }
    (OUT / "estado.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def queue() -> list[dict]:
    path = OUT / "queue.json"
    if not path.exists():
        path.write_text(json.dumps(default_queue(), ensure_ascii=False, indent=2),
                        encoding="utf-8")
    items = load_json(path, [])
    return [i for i in items if i.get("id")]


def variant_settings(base: Settings, item: dict) -> Settings:
    return apply_settings(base, item.get("patch") or {})


def evaluate(base: Settings, items: list[dict], progress: dict) -> None:
    """Corre las variantes pendientes, ventana a ventana."""
    results_path = OUT / "resultados.jsonl"
    for key, start, end, days in WINDOWS:
        pending = [
            it for it in items
            if key not in progress.get(it["id"], {}).get("windows", {})
        ]
        if not pending:
            continue
        wait_while_paused_and_loaded()
        if stop_requested():
            return
        write_state(phase="preparando", detail={"window": key})
        sessions, source, dataset = prepare_dataset(
            base, days=days, start=date.fromisoformat(start)
        )
        log(f"[{key}] {len(sessions)} sesiones; variantes pendientes: {len(pending)}")
        for item in pending:
            wait_while_paused_and_loaded()
            if stop_requested():
                return
            vid = item["id"]
            write_state(phase="simulando", detail={"window": key, "variant": vid})
            cfg = variant_settings(base, item)
            started = time.perf_counter()
            result = _simulate(cfg, sessions, source, f"{vid}-{key}", dataset)
            metrics = result["metrics"]
            entry = progress.setdefault(vid, {"windows": {}, "trades": []})
            entry["windows"][key] = {
                "sessions": len(sessions),
                "net": metrics.get("net_profit"),
                "trades": metrics.get("trades"),
                "pf": metrics.get("profit_factor"),
                "dd": metrics.get("max_drawdown"),
            }
            # Se guarda el trade completo: compute_stats necesita exit_ts,
            # direction, r_multiple y el resto para ordenar y agregar.
            entry["trades"].extend(result["trades"])
            save_progress(progress)
            log(f"  {vid} {key}: {metrics.get('trades')} ops, "
                f"net {metrics.get('net_profit'):.2f}, "
                f"pf {metrics.get('profit_factor')}, "
                f"dd {metrics.get('max_drawdown'):.2f} "
                f"({time.perf_counter() - started:.0f}s)")
    # Cierra las variantes completas.
    for item in items:
        vid = item["id"]
        entry = progress.get(vid)
        if not entry or len(entry["windows"]) != len(WINDOWS):
            continue
        if entry.get("closed"):
            continue
        stats = compute_stats(entry["trades"], INITIAL_CAPITAL)
        record = {
            "ts": now(),
            "id": vid,
            "patch": item.get("patch") or {},
            "why": item.get("why", ""),
            "trades": stats.get("trades"),
            "net": stats.get("net_profit"),
            "pf": stats.get("profit_factor"),
            "dd": stats.get("max_drawdown"),
            "dd_pct": stats.get("max_drawdown_pct"),
            "avg_r": stats.get("avg_r"),
            "win_rate": stats.get("win_rate"),
            "rdd": round(float(stats.get("net_profit") or 0.0)
                         / max(float(stats.get("max_drawdown") or 0.0), 1.0), 4),
            "windows": entry["windows"],
        }
        with results_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        entry["closed"] = True
        save_progress(progress)
        log(f"= {vid}: {record['trades']} ops, net {record['net']:.2f}, "
            f"pf {record['pf']}, dd {record['dd']:.2f}, rdd {record['rdd']}")
    write_summary()


def save_progress(progress: dict) -> None:
    (OUT / "progreso.json").write_text(
        json.dumps(progress, ensure_ascii=False), encoding="utf-8"
    )


def load_results() -> list[dict]:
    rows = []
    path = OUT / "resultados.jsonl"
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def _flat(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flat(v, key))
        else:
            out[key] = v
    return out


def build_combos(results: list[dict], limit: int = 3) -> list[dict]:
    """Combina la mejor variante con las siguientes, sin pisar la misma palanca."""
    ranked = [
        r for r in results
        if r.get("id") != "manual_base" and float(r.get("net") or 0) > 0
    ]
    ranked.sort(key=lambda r: float(r.get("rdd") or 0), reverse=True)
    if not ranked:
        return []
    top = ranked[0]
    top_keys = set(_flat(top.get("patch") or {}))
    combos, seen = [], set()
    for other in ranked[1:]:
        other_patch = other.get("patch") or {}
        if top_keys & set(_flat(other_patch)):
            continue
        merged = json.loads(json.dumps(top.get("patch") or {}))
        for k, v in other_patch.items():
            if isinstance(v, dict):
                merged.setdefault(k, {}).update(v)
            else:
                merged[k] = v
        key = json.dumps(merged, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        combos.append({
            "id": f"{top['id']}+{other['id']}",
            "patch": merged,
            "why": f"combinación adaptativa: {top['id']} + {other['id']}",
        })
        if len(combos) >= limit:
            break
    return combos


def write_summary() -> None:
    rows = load_results()
    if not rows:
        return
    rows.sort(key=lambda r: (float(r.get("rdd") or 0), float(r.get("net") or 0)),
              reverse=True)
    lines = [
        "# Ranking autónomo (W1-W6, in-sample)",
        "",
        f"Generado: {now()}",
        "",
        "Exploratorio: el holdout no se ha leído y nada de esto se aplica al 8765.",
        "",
        "| # | Variante | Ops | Neto USD | PF | DD USD | RDD | Cambio |",
        "|---:|---|---:|---:|---:|---:|---:|---|",
    ]
    for i, r in enumerate(rows, 1):
        patch = json.dumps(r.get("patch") or {}, ensure_ascii=False)
        lines.append(
            f"| {i} | {r['id']} | {r['trades']} | {float(r['net']):,.2f} | "
            f"{r['pf']} | {float(r['dd']):,.2f} | {r['rdd']} | `{patch}` |"
        )
    lines += ["", "## Notas", "",
              "- RDD = neto / drawdown máximo; premia retorno por unidad de dolor.",
              "- Es una muestra única y elegida in-sample: sirve para priorizar, "
              "no para promocionar.", ""]
    (OUT / "resumen_bucle.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    global OUT, WINDOWS
    smoke = "--smoke" in sys.argv
    if smoke:
        OUT = ROOT / "reports" / "autoloop_smoke"
        WINDOWS = (("W1", "2025-01-10", "2025-01-24", 10),)
    OUT.mkdir(parents=True, exist_ok=True)
    idle_priority()
    base = Settings.model_validate_json(
        (ROOT / "data" / "config.json").read_text(encoding="utf-8")
    )
    items = ([{"id": "smoke_base", "patch": {}, "why": "prueba de humo"}]
             if smoke else queue())
    progress = load_json(OUT / "progreso.json", {})
    log(f"inicio: {len(items)} variantes; ram libre {free_ram_mb()} MB")
    try:
        evaluate(base, items, progress)
        write_summary()
        if not smoke:
            combos = build_combos(load_results())
            if combos:
                log("fase 2: " + ", ".join(c["id"] for c in combos))
                (OUT / "queue.json").write_text(
                    json.dumps(items + combos, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                evaluate(base, combos, progress)
                write_summary()
        if smoke:
            log("smoke ok; salida")
            return 0
        write_state(phase="vigilando")
        while not stop_requested():
            time.sleep(60)
            write_state(phase="vigilando")
        log("STOP detectado; salida limpia")
    except Exception:
        log("ERROR\n" + traceback.format_exc())
        write_state(phase="error")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
