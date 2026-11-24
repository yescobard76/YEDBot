"""Sensibilidad del walk-forward a la regla de selección.

Variantes sobre W1-W6, sin holdout ni backtests nuevos:

- expansiva con mínimo de 5 operaciones (regla original);
- expansiva con mínimo de 3;
- rodante de 2 bloques con mínimo de 5.

Solo cambia la regla de selección; los P&L de test son los mismos bloques ya
ejecutados. No modifica configuración, protocolo ni lock.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from walk_forward_presets import build_payload

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "reports/backtest/presets_default_dev.json"
EXISTING = ROOT / "reports/backtest/walk_forward_presets.json"
OUT_JSON = ROOT / "reports/backtest/walk_forward_sensitivity.json"
OUT_MD = ROOT / "reports/backtest/WALK_FORWARD_SENSITIVITY.md"

VARIANTS: tuple[tuple[str, int, int | None], ...] = (
    ("expanding_min5", 5, None),
    ("expanding_min3", 3, None),
    ("rolling2_min5", 5, 2),
)


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "n/d"
    if isinstance(value, str):
        return value
    return f"{float(value):,.{digits}f}".replace(",", ".")


def _selection_text(payload: dict[str, Any]) -> str:
    return " → ".join(
        f"{fold['test_window']}:{fold['selected']}" for fold in payload["folds"]
    )


def main() -> int:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    if source.get("holdout_executed"):
        raise SystemExit("La fuente declara holdout ejecutado")
    existing = json.loads(EXISTING.read_text(encoding="utf-8"))

    variants: dict[str, dict[str, Any]] = {}
    for name, min_trades, window in VARIANTS:
        payload = build_payload(
            source,
            min_train_trades=min_trades,
            train_window=window,
        )
        variants[name] = {
            "min_train_trades": min_trades,
            "train_window_blocks": window,
            "folds": payload["folds"],
            "summary": payload["summary"],
        }

    # La variante original debe reproducir el artefacto ya publicado.
    original = variants["expanding_min5"]
    assert [fold["selected"] for fold in original["folds"]] == [
        fold["selected"] for fold in existing["folds"]
    ], "La variante original cambió sus selecciones"
    assert original["summary"] == existing["summary"], "La variante original cambió su resumen"

    result = {
        "schema": "preset-walk-forward-sensitivity-v1",
        "source": "reports/backtest/presets_default_dev.json",
        "holdout_executed": False,
        "scope": "W1-W6 development blocks; selection-rule sensitivity",
        "variants": variants,
    }
    OUT_JSON.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )

    lines: list[str] = []
    lines.append("# Sensibilidad del walk-forward a la regla de selección")
    lines.append("")
    lines.append(
        "Variantes deterministas sobre los P&L de W1–W6 ya ejecutados. "
        "No se abrió el holdout, no se ejecutaron backtests nuevos y no se "
        "modificó la configuración activa."
    )
    lines.append("")
    lines.append("## Variantes")
    lines.append("")
    lines.append("| Variante | Entrenamiento | Mínimo ops | Selecciones |")
    lines.append("|---|---|---:|---|")
    for name, min_trades, window in VARIANTS:
        train = (
            "expansivo W1..Wt"
            if window is None
            else f"rodante últimos {window} bloques"
        )
        lines.append(
            f"| `{name}` | {train} | {min_trades} | "
            f"{_selection_text(variants[name])} |"
        )
    lines.append("")
    lines.append("## Resultado")
    lines.append("")
    lines.append(
        f"`Δ vs baseline` es la diferencia de neto de los "
        f"{len(original['folds'])} tests. `Retorno compuesto` usa los P&L de "
        "bloque con capital inicial 25.000 USD; no es una curva intradía."
    )
    lines.append("")
    lines.append(
        "| Variante | Tests+ | Ops | Neto $ | PF | Peor DD $ | Δ vs baseline $ | Compuesto % |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for name, _, _ in VARIANTS:
        selected = variants[name]["summary"]["selected"]
        lines.append(
            f"| `{name}` | {selected['positive_tests']}/{selected['tests']} | "
            f"{selected['trades']} | {_fmt(selected['net_profit'])} | "
            f"{_fmt(selected['profit_factor'], 3)} | "
            f"{_fmt(selected['worst_test_dd'])} | "
            f"{_fmt(selected['delta_net_vs_baseline'])} | "
            f"{_fmt(selected['compounded_return_pct'], 3)} |"
        )
    lines.append("")
    lines.append("## Lectura")
    lines.append("")

    original_summary = original["summary"]
    original_selected = original_summary["selected"]
    baseline_net = original_summary["baseline"]["net_profit"]
    best_name = max(
        variants,
        key=lambda name: variants[name]["summary"]["selected"]["net_profit"],
    )
    best = variants[best_name]["summary"]["selected"]
    lines.append(
        f"- Baseline: **{_fmt(baseline_net)} USD**. La regla original "
        f"(`expanding_min5`) obtiene **{_fmt(original_selected['net_profit'])} USD**, "
        f"**{_fmt(original_selected['delta_net_vs_baseline'])} USD** frente a baseline, "
        f"y **{_fmt(original_selected['compounded_return_pct'], 3)} %** compuesto."
    )
    if float(best["delta_net_vs_baseline"]) < 0:
        lines.append(
            f"- **Ninguna variante supera a baseline.** La mejor es `{best_name}`, "
            f"con **{_fmt(best['net_profit'])} USD**, todavía "
            f"**{_fmt(best['delta_net_vs_baseline'])} USD** por debajo de baseline."
        )
    else:
        lines.append(
            f"- La mejor variante es `{best_name}`, con "
            f"**{_fmt(best['net_profit'])} USD** y "
            f"**{_fmt(best['delta_net_vs_baseline'])} USD** frente a baseline. "
            "Sigue siendo exploratoria."
        )
    min3 = variants["expanding_min3"]["summary"]["selected"]
    lines.append(
        f"- Bajar el mínimo a 3 operaciones empeora el resultado: "
        f"**{_fmt(min3['net_profit'])} USD** y "
        f"**{_fmt(min3['delta_net_vs_baseline'])} USD** frente a baseline."
    )
    lines.append(
        "- Las variantes de sensibilidad no se eligen por su resultado: la "
        "regla original sigue siendo la pre-registrada. Ninguna mejora en esta "
        f"muestra sería evidencia suficiente: {len(original['folds'])} folds, "
        "un bloque de test por fold y sin intervalos de confianza."
    )
    lines.append("")
    lines.append("## Límites")
    lines.append("")
    lines.append(
        "- No se remuestrean sesiones; se reutilizan los P&L de bloque. "
        "No sustituye al bootstrap ni al scorecard."
    )
    lines.append(
        "- El mínimo de operaciones bajo puede seleccionar presets de pocas "
        "operaciones; un resultado positivo no es evidencia de edge."
    )
    lines.append(
        "- El holdout sigue sellado; no hay promoción ni se abre el protocolo "
        "confirmatorio."
    )
    lines.append("")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print("variant,selections,net,pf,worst_dd,delta,compounded_pct")
    for name, _, _ in VARIANTS:
        summary = variants[name]["summary"]["selected"]
        print(
            f"{name},{_selection_text(variants[name]).replace(' → ', ' -> ')},"
            f"{summary['net_profit']:.2f},{summary['profit_factor']},"
            f"{summary['worst_test_dd']:.2f},"
            f"{summary['delta_net_vs_baseline']:.2f},"
            f"{summary['compounded_return_pct']:.3f}"
        )
    print(f"Escrito {OUT_JSON}")
    print(f"Escrito {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
