"""Diseño de validación por bloques para una hipótesis pre-registrada.

Este módulo es **solo diseño y utilidades puras**. No lee barras, no ejecuta
backtests, no abre el holdout y no se importa desde el motor, la API, los
presets ni la configuración viva.

El diseño fija cuatro bloques consecutivos con un mínimo de 20 operaciones por
bloque (80 en total), dos miradas secuenciales (tras los bloques 2 y 4),
bootstrap pareado por bloque, gasto alfa O'Brien-Fleming conservador y un
placebo de entradas aleatorias en la misma sesión y dirección.

Uso previsto, una vez exista un lock nuevo con la muestra concreta::

    from research.validacion_bloques import (
        BlockSample,
        SequentialAlphaSpending,
        evaluate_validation,
        generate_placebo_entries,
    )

    outcome = evaluate_validation(blocks, look=2)
    print(outcome.status)

Los tests de este módulo usan bloques sintéticos. No son una validación de la
estrategia ni sustituyen la muestra externa.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from statistics import NormalDist
from typing import Any, Literal

DESIGN_SCHEMA = "validacion-bloques-v1"
DESIGN_STATUS = "design_only_not_executed"

# El diseño es deliberadamente fijo: cuatro bloques trimestrales, dos miradas.
DEFAULT_BLOCK_COUNT = 4
DEFAULT_MIN_TRADES_PER_BLOCK = 20
DEFAULT_TARGET_EFFECT_R = 0.10
DEFAULT_TOTAL_ALPHA = 0.05
DEFAULT_INFORMATION_FRACTIONS = (0.5, 1.0)
DEFAULT_LOOK_BLOCKS = (2, 4)
DEFAULT_BOOTSTRAP_RESAMPLES = 10_000
DEFAULT_BOOTSTRAP_SEED = 20261121
DEFAULT_PLACEBO_SEED = 20261121
DEFAULT_CONFIDENCE = 0.95
PLACEBO_METHOD = "same_session_same_direction_uniform_entry_minute"

Direction = Literal["long", "short"]
ControlKind = Literal["baseline", "placebo"]
OutcomeStatus = Literal[
    "pass",
    "fail",
    "inconclusive",
    "inconclusive_placebo",
    "continue",
]


class BlockValidationError(ValueError):
    """El diseño o los datos sintéticos no cumplen el contrato."""


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _percentile(ordered: Sequence[float], quantile: float) -> float:
    """Percentil con interpolación lineal; ``ordered`` debe estar ordenado."""
    if not ordered:
        raise BlockValidationError("No se puede calcular un percentil vacío")
    position = (len(ordered) - 1) * quantile
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    fraction = position - low
    return ordered[low] + (ordered[high] - ordered[low]) * fraction


def _as_date(value: date | str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise BlockValidationError(f"Fecha inválida: {value!r}") from exc


@dataclass(frozen=True, slots=True)
class BlockSample:
    """Resultados R de un bloque, separados por brazo.

    ``candidate_r`` y ``baseline_r`` son los R por operación. ``placebo_r`` es
    opcional; si está presente debe tener una entrada por cada operación del
    candidato, porque el placebo se genera emparejado uno a uno.
    """

    block_id: str
    candidate_r: tuple[float, ...]
    baseline_r: tuple[float, ...]
    placebo_r: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        block_id = self.block_id.strip()
        if not block_id:
            raise BlockValidationError("block_id no puede estar vacío")
        object.__setattr__(self, "block_id", block_id)

        for name in ("candidate_r", "baseline_r", "placebo_r"):
            raw = getattr(self, name)
            try:
                values = tuple(float(value) for value in raw)
            except (TypeError, ValueError) as exc:
                raise BlockValidationError(
                    f"{name} debe contener números"
                ) from exc
            if any(not math.isfinite(value) for value in values):
                raise BlockValidationError(f"{name} contiene valores no finitos")
            object.__setattr__(self, name, values)

        if self.placebo_r and len(self.placebo_r) != len(self.candidate_r):
            raise BlockValidationError(
                "placebo_r debe tener el mismo número de operaciones que candidate_r"
            )

    @property
    def candidate_mean(self) -> float | None:
        return _mean(self.candidate_r) if self.candidate_r else None

    @property
    def baseline_mean(self) -> float | None:
        return _mean(self.baseline_r) if self.baseline_r else None

    @property
    def placebo_mean(self) -> float | None:
        return _mean(self.placebo_r) if self.placebo_r else None

    @property
    def has_placebo(self) -> bool:
        return bool(self.placebo_r)

    @property
    def candidate_trades(self) -> int:
        return len(self.candidate_r)

    @property
    def baseline_trades(self) -> int:
        return len(self.baseline_r)

    @property
    def placebo_trades(self) -> int:
        return len(self.placebo_r)


@dataclass(frozen=True, slots=True)
class BlockValidation:
    """Preflight de mínimos por bloque."""

    status: Literal["ready", "insufficient"]
    min_trades_per_block: int
    blockers: tuple[str, ...]
    candidate_trades: int
    baseline_trades: int
    placebo_trades: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "min_trades_per_block": self.min_trades_per_block,
            "blockers": list(self.blockers),
            "candidate_trades": self.candidate_trades,
            "baseline_trades": self.baseline_trades,
            "placebo_trades": self.placebo_trades,
        }


def validate_blocks(
    blocks: Sequence[BlockSample],
    *,
    min_trades_per_block: int = DEFAULT_MIN_TRADES_PER_BLOCK,
    require_placebo: bool = True,
) -> BlockValidation:
    """Comprueba que cada bloque tenga muestra suficiente en cada brazo.

    Un bloque por debajo del mínimo no se compensa con otro bloque: el
    resultado global es ``insufficient``. Esto evita que un trimestre con dos
    operaciones quede diluido en el agregado.
    """
    if min_trades_per_block <= 0:
        raise BlockValidationError("min_trades_per_block debe ser positivo")
    if not blocks:
        raise BlockValidationError("Se necesita al menos un bloque")

    seen: set[str] = set()
    blockers: list[str] = []
    candidate_trades = 0
    baseline_trades = 0
    placebo_trades = 0

    for block in blocks:
        if block.block_id in seen:
            raise BlockValidationError(f"block_id duplicado: {block.block_id}")
        seen.add(block.block_id)
        candidate_trades += block.candidate_trades
        baseline_trades += block.baseline_trades
        placebo_trades += block.placebo_trades

        if block.candidate_trades < min_trades_per_block:
            blockers.append(
                f"{block.block_id}: candidato {block.candidate_trades} "
                f"< {min_trades_per_block}"
            )
        if block.baseline_trades < min_trades_per_block:
            blockers.append(
                f"{block.block_id}: baseline {block.baseline_trades} "
                f"< {min_trades_per_block}"
            )
        if require_placebo and not block.has_placebo:
            blockers.append(f"{block.block_id}: placebo ausente")

    return BlockValidation(
        status="ready" if not blockers else "insufficient",
        min_trades_per_block=min_trades_per_block,
        blockers=tuple(blockers),
        candidate_trades=candidate_trades,
        baseline_trades=baseline_trades,
        placebo_trades=placebo_trades,
    )


@dataclass(frozen=True, slots=True)
class PairedBootstrapResult:
    """Resultado del bootstrap pareado de diferencias por bloque."""

    control: ControlKind
    observed_diff: float
    ci_low: float
    ci_high: float
    p_value_one_sided: float
    resamples: int
    seed: int
    confidence: float
    block_ids: tuple[str, ...]
    block_differences: tuple[float, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "control": self.control,
            "observed_diff": self.observed_diff,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "p_value_one_sided": self.p_value_one_sided,
            "resamples": self.resamples,
            "seed": self.seed,
            "confidence": self.confidence,
            "block_ids": list(self.block_ids),
            "block_differences": list(self.block_differences),
        }


def paired_block_bootstrap(
    blocks: Sequence[BlockSample],
    *,
    control: ControlKind = "baseline",
    resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
    confidence: float = DEFAULT_CONFIDENCE,
) -> PairedBootstrapResult:
    """Bootstrap pareado con el bloque como unidad.

    Para cada bloque se calcula ``d_b = media(candidato_b) - media(control_b)``.
    Después se remuestrean los bloques con reemplazo y se calcula la media de
    los ``d_b`` seleccionados. El candidato y el control usan **los mismos
    índices de bloque** en cada réplica; por eso el bootstrap es pareado.

    El p-valor es unilateral para ``H0: diferencia <= 0``. Se usa la
    corrección ``+1`` para no devolver p=0 con un bootstrap finito. El IC es
    percentil bilateral; no se usa como frontera secuencial.
    """
    if control not in ("baseline", "placebo"):
        raise BlockValidationError("control debe ser 'baseline' o 'placebo'")
    if len(blocks) < 2:
        raise BlockValidationError("El bootstrap pareado necesita al menos 2 bloques")
    if resamples < 100:
        raise BlockValidationError("resamples debe ser >= 100")
    if not 0.0 < confidence < 1.0:
        raise BlockValidationError("confidence debe estar entre 0 y 1")

    block_ids = tuple(block.block_id for block in blocks)
    if len(set(block_ids)) != len(block_ids):
        raise BlockValidationError("Los block_id deben ser únicos")

    differences: list[float] = []
    for block in blocks:
        candidate = block.candidate_mean
        reference = (
            block.baseline_mean if control == "baseline" else block.placebo_mean
        )
        if candidate is None:
            raise BlockValidationError(
                f"{block.block_id}: no hay operaciones del candidato"
            )
        if reference is None:
            raise BlockValidationError(
                f"{block.block_id}: no hay operaciones del control {control}"
            )
        differences.append(candidate - reference)

    observed = _mean(differences)
    count = len(differences)
    rng = random.Random(seed)
    draws: list[float] = []
    for _ in range(resamples):
        indices = [rng.randrange(count) for _ in range(count)]
        draws.append(sum(differences[index] for index in indices) / count)
    draws.sort()

    tail = (1.0 - confidence) / 2.0
    ci_low = _percentile(draws, tail)
    ci_high = _percentile(draws, 1.0 - tail)
    at_or_below = sum(1 for value in draws if value <= 0.0)
    p_value = (at_or_below + 1.0) / (resamples + 1.0)

    return PairedBootstrapResult(
        control=control,
        observed_diff=observed,
        ci_low=ci_low,
        ci_high=ci_high,
        p_value_one_sided=p_value,
        resamples=resamples,
        seed=seed,
        confidence=confidence,
        block_ids=block_ids,
        block_differences=tuple(differences),
    )


@dataclass(frozen=True, slots=True)
class SequentialDecision:
    """Decisión en una mirada secuencial concreta."""

    look: int
    p_value: float
    nominal_alpha: float
    z_boundary: float
    status: Literal["efficacy", "continue", "no_efficacy"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "look": self.look,
            "p_value": self.p_value,
            "nominal_alpha": self.nominal_alpha,
            "z_boundary": self.z_boundary,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class SequentialAlphaSpending:
    """Gasto alfa O'Brien-Fleming con niveles nominales incrementales.

    La curva de gasto se evalúa en las fracciones de información. El alfa
    nominal de cada mirada es el incremento de gasto acumulado; se usa como
    nivel de cada contraste. Es una implementación **conservadora**, porque no
    explota la correlación entre miradas: por unión de eventos, el error tipo I
    global no supera ``total_alpha``. No pretende reproducir los límites
    conjuntos exactos de un grupo secuencial multivariante.
    """

    total_alpha: float = DEFAULT_TOTAL_ALPHA
    information_fractions: tuple[float, ...] = DEFAULT_INFORMATION_FRACTIONS
    sides: int = 1
    method: str = "obf"

    def __post_init__(self) -> None:
        if not 0.0 < float(self.total_alpha) < 1.0:
            raise BlockValidationError("total_alpha debe estar entre 0 y 1")
        fractions = tuple(float(value) for value in self.information_fractions)
        if not fractions:
            raise BlockValidationError("information_fractions no puede estar vacío")
        if any(not 0.0 < value <= 1.0 for value in fractions):
            raise BlockValidationError(
                "Las fracciones de información deben estar en (0, 1]"
            )
        for previous, current in zip(fractions, fractions[1:]):
            if current <= previous:
                raise BlockValidationError(
                    "Las fracciones de información deben ser estrictamente crecientes"
                )
        if not math.isclose(fractions[-1], 1.0, rel_tol=0.0, abs_tol=1e-12):
            raise BlockValidationError("La última fracción debe ser 1.0")
        if self.sides not in (1, 2):
            raise BlockValidationError("sides debe ser 1 o 2")
        if self.method != "obf":
            raise BlockValidationError("method debe ser 'obf'")
        object.__setattr__(self, "information_fractions", fractions)

    def _spend(self, fraction: float) -> float:
        z = NormalDist().inv_cdf(1.0 - self.total_alpha / self.sides)
        return self.sides * (1.0 - NormalDist().cdf(z / math.sqrt(fraction)))

    @property
    def cumulative_alpha(self) -> tuple[float, ...]:
        return tuple(self._spend(fraction) for fraction in self.information_fractions)

    @property
    def nominal_alphas(self) -> tuple[float, ...]:
        cumulative = self.cumulative_alpha
        previous = 0.0
        result: list[float] = []
        for value in cumulative:
            result.append(value - previous)
            previous = value
        return tuple(result)

    @property
    def z_boundaries(self) -> tuple[float, ...]:
        return tuple(
            NormalDist().inv_cdf(1.0 - alpha / self.sides)
            for alpha in self.nominal_alphas
        )

    @property
    def looks(self) -> int:
        return len(self.information_fractions)

    def nominal_alpha(self, look: int) -> float:
        if not 1 <= look <= self.looks:
            raise BlockValidationError(
                f"look debe estar entre 1 y {self.looks}"
            )
        return self.nominal_alphas[look - 1]

    def z_boundary(self, look: int) -> float:
        if not 1 <= look <= self.looks:
            raise BlockValidationError(
                f"look debe estar entre 1 y {self.looks}"
            )
        return self.z_boundaries[look - 1]

    def decide(self, p_value: float, look: int) -> SequentialDecision:
        if not 0.0 <= p_value <= 1.0:
            raise BlockValidationError("p_value debe estar entre 0 y 1")
        nominal = self.nominal_alpha(look)
        if p_value <= nominal + 1e-15:
            status: Literal["efficacy", "continue", "no_efficacy"] = "efficacy"
        elif look == self.looks:
            status = "no_efficacy"
        else:
            status = "continue"
        return SequentialDecision(
            look=look,
            p_value=p_value,
            nominal_alpha=nominal,
            z_boundary=self.z_boundary(look),
            status=status,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "sides": self.sides,
            "total_alpha": self.total_alpha,
            "information_fractions": list(self.information_fractions),
            "cumulative_alpha": list(self.cumulative_alpha),
            "nominal_alphas": list(self.nominal_alphas),
            "z_boundaries": list(self.z_boundaries),
        }


@dataclass(frozen=True, slots=True)
class PlaceboCandidate:
    """Entrada real que sirve de base para una entrada placebo."""

    session: date
    direction: Direction
    entry_ts: int

    def __post_init__(self) -> None:
        if not isinstance(self.session, date):
            raise BlockValidationError("session debe ser una fecha")
        if self.direction not in ("long", "short"):
            raise BlockValidationError("direction debe ser 'long' o 'short'")
        if not isinstance(self.entry_ts, int) or self.entry_ts < 0:
            raise BlockValidationError("entry_ts debe ser un entero no negativo")


@dataclass(frozen=True, slots=True)
class PlaceboEntry:
    """Entrada aleatoria emparejada con una entrada real."""

    session: date
    direction: Direction
    entry_ts: int
    source_entry_ts: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "session": self.session.isoformat(),
            "direction": self.direction,
            "entry_ts": self.entry_ts,
            "source_entry_ts": self.source_entry_ts,
        }


@dataclass(frozen=True, slots=True)
class PlaceboPlan:
    """Plan de entradas placebo reproducible."""

    entries: tuple[PlaceboEntry, ...]
    seed: int
    method: str
    duplicate_entries: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "entries": [entry.as_dict() for entry in self.entries],
            "seed": self.seed,
            "method": self.method,
            "duplicate_entries": self.duplicate_entries,
            "count": len(self.entries),
        }


def generate_placebo_entries(
    candidates: Sequence[PlaceboCandidate],
    eligible_ts_by_session: Mapping[date | str, Sequence[int]],
    *,
    seed: int = DEFAULT_PLACEBO_SEED,
    method: str = PLACEBO_METHOD,
) -> PlaceboPlan:
    """Genera una entrada placebo por cada entrada real.

    El placebo conserva sesión y dirección, y elige uniformemente un minuto
    elegible de la misma sesión, excluyendo el minuto de la entrada real. El
    llamador debe entregar **solo** timestamps causales y permitidos por la
    regla (ventana de entrada, barras disponibles). El generador no calcula
    P&L ni ejecuta la estrategia.

    Se permiten repeticiones entre candidatos distintos; ``duplicate_entries``
    las cuenta para que el análisis las reporte. Si una sesión solo tiene el
    minuto real como elegible, no existe placebo válido y se lanza un error.
    """
    if method != PLACEBO_METHOD:
        raise BlockValidationError(f"method de placebo no soportado: {method!r}")

    eligible: dict[date, tuple[int, ...]] = {}
    for key, values in eligible_ts_by_session.items():
        day = _as_date(key)
        timestamps = tuple(sorted({int(value) for value in values}))
        if any(value < 0 for value in timestamps):
            raise BlockValidationError("Los timestamps elegibles deben ser >= 0")
        eligible[day] = timestamps

    rng = random.Random(seed)
    entries: list[PlaceboEntry] = []
    seen: set[tuple[date, int, str]] = set()
    duplicates = 0

    for candidate in candidates:
        pool = [
            timestamp
            for timestamp in eligible.get(candidate.session, ())
            if timestamp != candidate.entry_ts
        ]
        if not pool:
            raise BlockValidationError(
                "No hay timestamps elegibles distintos de la entrada real para "
                f"{candidate.session.isoformat()}"
            )
        chosen = rng.choice(pool)
        entry = PlaceboEntry(
            session=candidate.session,
            direction=candidate.direction,
            entry_ts=chosen,
            source_entry_ts=candidate.entry_ts,
        )
        key = (entry.session, entry.entry_ts, entry.direction)
        if key in seen:
            duplicates += 1
        seen.add(key)
        entries.append(entry)

    return PlaceboPlan(
        entries=tuple(entries),
        seed=seed,
        method=method,
        duplicate_entries=duplicates,
    )


@dataclass(frozen=True, slots=True)
class ValidationOutcome:
    """Resultado de una mirada del diseño, sin ejecutar la estrategia."""

    status: OutcomeStatus
    look: int
    blocks_observed: int
    validation: BlockValidation
    baseline: PairedBootstrapResult | None
    placebo: PairedBootstrapResult | None
    sequential: SequentialDecision | None
    target_met: bool
    placebo_met: bool
    blockers: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "look": self.look,
            "blocks_observed": self.blocks_observed,
            "validation": self.validation.as_dict(),
            "baseline": None if self.baseline is None else self.baseline.as_dict(),
            "placebo": None if self.placebo is None else self.placebo.as_dict(),
            "sequential": (
                None if self.sequential is None else self.sequential.as_dict()
            ),
            "target_met": self.target_met,
            "placebo_met": self.placebo_met,
            "blockers": list(self.blockers),
        }


def evaluate_validation(
    blocks: Sequence[BlockSample],
    *,
    look: int | None = None,
    min_trades_per_block: int = DEFAULT_MIN_TRADES_PER_BLOCK,
    target_effect: float = DEFAULT_TARGET_EFFECT_R,
    alpha: SequentialAlphaSpending | None = None,
    resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
    require_placebo: bool = True,
) -> ValidationOutcome:
    """Evalúa una mirada del diseño con bloques ya calculados.

    No ejecuta nada: recibe los R por operación de cada bloque. La mirada 1
    usa los bloques 1-2; la mirada 2 (final) usa los bloques 1-4. La muestra
    debe tener exactamente cuatro bloques.

    Regla de decisión:

    - ``inconclusive`` si algún bloque no alcanza el mínimo o falta placebo.
    - ``pass`` si el bootstrap supera el alfa nominal, la diferencia observada
      alcanza ``target_effect`` y el placebo tiene IC95 inferior > 0.
    - ``continue`` en una mirada intermedia si aún no se puede parar.
    - ``fail`` en la mirada final si no hay eficacia o no se alcanza el
      objetivo práctico.
    - ``inconclusive_placebo`` en la mirada final si el candidato supera al
      baseline pero no al placebo.
    """
    if len(blocks) != DEFAULT_BLOCK_COUNT:
        raise BlockValidationError(
            f"El diseño fija {DEFAULT_BLOCK_COUNT} bloques; hay {len(blocks)}"
        )
    if not math.isfinite(target_effect) or target_effect < 0.0:
        raise BlockValidationError("target_effect debe ser finito y >= 0")
    alpha = alpha or SequentialAlphaSpending()
    if alpha.sides != 1:
        raise BlockValidationError("La evaluación usa un contraste unilateral")
    if alpha.looks != len(DEFAULT_LOOK_BLOCKS):
        raise BlockValidationError(
            f"El diseño fija {len(DEFAULT_LOOK_BLOCKS)} miradas; "
            f"el gasto alfa tiene {alpha.looks}"
        )

    if look is None:
        look = len(DEFAULT_LOOK_BLOCKS)
    if not 1 <= look <= len(DEFAULT_LOOK_BLOCKS):
        raise BlockValidationError(
            f"look debe estar entre 1 y {len(DEFAULT_LOOK_BLOCKS)}"
        )

    blocks_observed = DEFAULT_LOOK_BLOCKS[look - 1]
    observed = blocks[:blocks_observed]
    validation = validate_blocks(
        observed,
        min_trades_per_block=min_trades_per_block,
        require_placebo=require_placebo,
    )
    if validation.status != "ready":
        return ValidationOutcome(
            status="inconclusive",
            look=look,
            blocks_observed=blocks_observed,
            validation=validation,
            baseline=None,
            placebo=None,
            sequential=None,
            target_met=False,
            placebo_met=False,
            blockers=validation.blockers,
        )

    baseline = paired_block_bootstrap(
        observed,
        control="baseline",
        resamples=resamples,
        seed=seed,
    )
    placebo = (
        paired_block_bootstrap(
            observed,
            control="placebo",
            resamples=resamples,
            seed=seed,
        )
        if require_placebo
        else None
    )
    sequential = alpha.decide(baseline.p_value_one_sided, look)
    target_met = baseline.observed_diff + 1e-12 >= target_effect
    placebo_met = (
        True
        if placebo is None
        else placebo.observed_diff > 0.0 and placebo.ci_low > 0.0
    )

    if sequential.status == "efficacy":
        if not target_met:
            if look == len(DEFAULT_LOOK_BLOCKS):
                return ValidationOutcome(
                    status="fail",
                    look=look,
                    blocks_observed=blocks_observed,
                    validation=validation,
                    baseline=baseline,
                    placebo=placebo,
                    sequential=sequential,
                    target_met=False,
                    placebo_met=placebo_met,
                    blockers=("target_effect_not_met",),
                )
            return ValidationOutcome(
                status="continue",
                look=look,
                blocks_observed=blocks_observed,
                validation=validation,
                baseline=baseline,
                placebo=placebo,
                sequential=sequential,
                target_met=False,
                placebo_met=placebo_met,
                blockers=("target_effect_not_met",),
            )
        if not placebo_met:
            if look == len(DEFAULT_LOOK_BLOCKS):
                return ValidationOutcome(
                    status="inconclusive_placebo",
                    look=look,
                    blocks_observed=blocks_observed,
                    validation=validation,
                    baseline=baseline,
                    placebo=placebo,
                    sequential=sequential,
                    target_met=True,
                    placebo_met=False,
                    blockers=("placebo_ci_not_above_zero",),
                )
            return ValidationOutcome(
                status="continue",
                look=look,
                blocks_observed=blocks_observed,
                validation=validation,
                baseline=baseline,
                placebo=placebo,
                sequential=sequential,
                target_met=True,
                placebo_met=False,
                blockers=("placebo_not_met_at_interim",),
            )
        return ValidationOutcome(
            status="pass",
            look=look,
            blocks_observed=blocks_observed,
            validation=validation,
            baseline=baseline,
            placebo=placebo,
            sequential=sequential,
            target_met=True,
            placebo_met=True,
            blockers=(),
        )

    if sequential.status == "continue":
        return ValidationOutcome(
            status="continue",
            look=look,
            blocks_observed=blocks_observed,
            validation=validation,
            baseline=baseline,
            placebo=placebo,
            sequential=sequential,
            target_met=target_met,
            placebo_met=placebo_met,
            blockers=(),
        )

    return ValidationOutcome(
        status="fail",
        look=look,
        blocks_observed=blocks_observed,
        validation=validation,
        baseline=baseline,
        placebo=placebo,
        sequential=sequential,
        target_met=target_met,
        placebo_met=placebo_met,
        blockers=("final_p_value_above_nominal_alpha",),
    )


def design_spec() -> dict[str, Any]:
    """Especificación serializable del diseño, sin datos ni resultados."""
    alpha = SequentialAlphaSpending()
    return {
        "schema": DESIGN_SCHEMA,
        "status": DESIGN_STATUS,
        "blocks": {
            "count": DEFAULT_BLOCK_COUNT,
            "looks_after_blocks": list(DEFAULT_LOOK_BLOCKS),
            "min_trades_per_block": DEFAULT_MIN_TRADES_PER_BLOCK,
            "min_total_candidate_trades": (
                DEFAULT_BLOCK_COUNT * DEFAULT_MIN_TRADES_PER_BLOCK
            ),
            "min_total_baseline_trades": (
                DEFAULT_BLOCK_COUNT * DEFAULT_MIN_TRADES_PER_BLOCK
            ),
        },
        "endpoint": {
            "name": "paired_block_mean_r_difference",
            "direction": "candidate_minus_baseline",
            "unit": "R per trade",
            "target_effect_r": DEFAULT_TARGET_EFFECT_R,
            "null": "delta <= 0",
            "alternative": "delta > 0",
            "sides": 1,
        },
        "alpha_spending": alpha.as_dict(),
        "bootstrap": {
            "paired": True,
            "unit": "block",
            "resamples": DEFAULT_BOOTSTRAP_RESAMPLES,
            "seed": DEFAULT_BOOTSTRAP_SEED,
            "confidence": DEFAULT_CONFIDENCE,
            "interval": "percentile",
        },
        "placebo": {
            "method": PLACEBO_METHOD,
            "seed": DEFAULT_PLACEBO_SEED,
            "same_session": True,
            "same_direction": True,
            "exclude_real_entry": True,
            "gate": "ci95_low_above_zero",
        },
        "decision": {
            "pass": [
                "all_blocks_meet_minimum",
                "sequential_efficacy",
                "observed_diff_at_least_target",
                "placebo_ci95_low_above_zero",
            ],
            "fail": [
                "final_no_efficacy",
                "target_effect_not_met_at_final",
            ],
            "inconclusive": [
                "block_below_minimum",
                "placebo_missing",
            ],
            "inconclusive_placebo": [
                "candidate_beats_baseline_but_not_placebo",
            ],
            "continue": [
                "interim_and_stopping_conditions_not_met",
            ],
        },
        "execution": {
            "design_only": True,
            "validation_executed": False,
            "backtests_run": 0,
            "holdout_opened": False,
            "config_modified": False,
        },
    }
