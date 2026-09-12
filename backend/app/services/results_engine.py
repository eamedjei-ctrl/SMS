"""M7 -- The results engine.

Every number this module produces comes from configuration. There is no grade
band, weight, threshold, subject name or term name in this file. If you ever
find yourself writing ``if score >= 80`` here, the product is broken.

The top half is pure: it takes configuration and raw scores and returns
outcomes, with no database and no Flask. That is what the test suite hammers.
The bottom half loads configuration from the tenant's own rows and persists the
computed results.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal

ZERO = Decimal("0")


# ==========================================================================
# Pure computation
# ==========================================================================
@dataclass(frozen=True)
class ComponentConfig:
    id: str
    code: str
    name: str
    weight: Decimal
    max_score: Decimal
    sequence: int = 0


@dataclass(frozen=True)
class BandConfig:
    grade: str
    min_score: Decimal
    max_score: Decimal
    remark: str | None = None
    points: Decimal | None = None
    sequence: int = 0


@dataclass(frozen=True)
class EngineSettings:
    weight_interpretation: str = "percentage"
    rounding_mode: str = "half_up"
    rounding_decimals: int = 0
    missing_score_rule: str = "treat_as_zero"
    absent_rule: str = "treat_as_zero"
    position_basis: str = "total_score"
    position_scope: str = "class"
    tie_rule: str = "shared_position"
    aggregate_method: str = "mean_of_totals"
    best_n: int | None = None
    best_n_compulsory_subject_ids: tuple[str, ...] = ()
    pass_mark: Decimal = Decimal("40")


@dataclass(frozen=True)
class ScoreInput:
    component_id: str
    raw_score: Decimal | None = None
    is_absent: bool = False


@dataclass
class SubjectOutcome:
    total_score: Decimal | None = None
    grade: str | None = None
    remark: str | None = None
    points: Decimal | None = None
    is_ranked: bool = True
    is_blocked: bool = False
    breakdown: dict = field(default_factory=dict)

    @property
    def has_total(self) -> bool:
        return self.total_score is not None


def apply_rounding(value: Decimal, mode: str, decimals: int) -> Decimal:
    if mode == "none":
        return value
    quantum = Decimal(1).scaleb(-int(decimals))
    rounding = ROUND_HALF_EVEN if mode == "half_even" else ROUND_HALF_UP
    return value.quantize(quantum, rounding=rounding)


def compute_subject_total(
    scores: dict[str, ScoreInput],
    components: list[ComponentConfig],
    settings: EngineSettings,
) -> SubjectOutcome:
    """Normalise each component against its own maximum, weight it, and sum.

    ``(raw_score / max_score) x weight`` for every component the school defined
    for this subject -- two components or five, weights summing to 100 or to
    arbitrary points, it makes no difference to this code.
    """
    active = sorted(components, key=lambda c: (c.sequence, c.code))
    if not active:
        return SubjectOutcome(total_score=None, is_ranked=False)

    total_weight = sum((c.weight for c in active), ZERO)
    counted_weight = ZERO
    accumulated = ZERO
    is_ranked = True
    breakdown: dict = {}

    for component in active:
        entry = scores.get(str(component.id))
        raw = entry.raw_score if entry else None
        absent = bool(entry.is_absent) if entry else False

        contribution: Decimal | None
        state: str

        if absent:
            rule = settings.absent_rule
            if rule == "block_computation":
                return SubjectOutcome(
                    total_score=None,
                    is_ranked=False,
                    is_blocked=True,
                    breakdown={
                        "blocked_by": component.code,
                        "reason": "absent_handling=block_computation",
                    },
                )
            if rule == "ignore_and_reweight":
                contribution, state = None, "absent_reweighted"
            elif rule == "exclude_from_ranking":
                contribution, state = ZERO, "absent_unranked"
                is_ranked = False
            else:  # treat_as_zero
                contribution, state = ZERO, "absent_zero"
        elif raw is None:
            rule = settings.missing_score_rule
            if rule == "exclude_from_ranking":
                contribution, state = ZERO, "missing_unranked"
                is_ranked = False
            else:  # treat_as_zero
                contribution, state = ZERO, "missing_zero"
        else:
            contribution = (Decimal(raw) / component.max_score) * component.weight
            state = "scored"

        if contribution is not None:
            accumulated += contribution
            counted_weight += component.weight

        breakdown[component.code] = {
            "component_id": str(component.id),
            "name": component.name,
            "weight": float(component.weight),
            "max_score": float(component.max_score),
            "raw_score": float(raw) if raw is not None else None,
            "is_absent": absent,
            "state": state,
            "contribution": float(contribution) if contribution is not None else None,
        }

    if counted_weight == ZERO:
        # Every component was reweighted away -- there is nothing to compute.
        return SubjectOutcome(total_score=None, is_ranked=False, breakdown=breakdown)

    total = accumulated
    if counted_weight != total_weight and total_weight > ZERO:
        # ignore_and_reweight: the surviving components carry the full weight.
        total = accumulated * (total_weight / counted_weight)

    total = apply_rounding(total, settings.rounding_mode, settings.rounding_decimals)
    return SubjectOutcome(total_score=total, is_ranked=is_ranked, breakdown=breakdown)


def resolve_band(total: Decimal | None, bands: list[BandConfig]) -> BandConfig | None:
    """Find the band a total falls into.

    Bands are matched from the top down on ``min_score``. This matters because
    schools write their bands as whole numbers -- "70-79" then "80-100" -- and
    mean "70 up to but not including 80". A total of 79.6 sits in the gap
    between those two rows, and the school expects it to be the lower grade, not
    an ungraded blank on a report card.

    A total above the highest band's maximum returns nothing rather than being
    clamped: that is a misconfiguration the school should see, not one we hide.
    """
    if total is None or not bands:
        return None

    ordered = sorted(bands, key=lambda b: (b.min_score, -b.sequence), reverse=True)
    for index, band in enumerate(ordered):
        if total >= band.min_score:
            if index == 0 and total > band.max_score:
                return None
            return band
    return None


def grade_subject(
    scores: dict[str, ScoreInput],
    components: list[ComponentConfig],
    bands: list[BandConfig],
    settings: EngineSettings,
) -> SubjectOutcome:
    outcome = compute_subject_total(scores, components, settings)
    band = resolve_band(outcome.total_score, bands)
    if band is not None:
        outcome.grade = band.grade
        outcome.remark = band.remark
        outcome.points = band.points
    return outcome


def rank(values: dict[str, Decimal], tie_rule: str = "shared_position") -> dict[str, int]:
    """Rank identifiers by value, highest first, honouring the school's tie rule.

    ``shared_position``: tied entries share a position and the next position
    skips (1, 2, 2, 4). ``sequential``: every entry gets a distinct position.
    """
    ordered = sorted(values.items(), key=lambda item: (-item[1], str(item[0])))
    positions: dict[str, int] = {}
    previous_value: Decimal | None = None
    previous_position = 0

    for index, (key, value) in enumerate(ordered, start=1):
        if tie_rule == "shared_position" and previous_value is not None and value == previous_value:
            positions[key] = previous_position
        else:
            positions[key] = index
            previous_position = index
            previous_value = value
    return positions


def compute_aggregate(
    outcomes: dict[str, SubjectOutcome],
    settings: EngineSettings,
    subject_weights: dict[str, Decimal] | None = None,
) -> tuple[Decimal | None, int]:
    """Combine a student's subjects into the school's configured overall figure."""
    usable = {
        subject_id: outcome
        for subject_id, outcome in outcomes.items()
        if outcome.has_total and not outcome.is_blocked
    }
    if not usable:
        return None, 0

    method = settings.aggregate_method

    if method == "sum_of_best_n_points":
        compulsory = {str(s) for s in settings.best_n_compulsory_subject_ids}
        scored = [
            (subject_id, outcome.points if outcome.points is not None else ZERO)
            for subject_id, outcome in usable.items()
        ]
        # Lower points are better in a points-based system (grade 1 beats grade 6).
        compulsory_rows = [row for row in scored if row[0] in compulsory]
        optional_rows = sorted(
            (row for row in scored if row[0] not in compulsory), key=lambda row: row[1]
        )
        n = settings.best_n or len(scored)
        remaining = max(n - len(compulsory_rows), 0)
        counted = compulsory_rows + optional_rows[:remaining]
        if not counted:
            return None, 0
        total = sum((row[1] for row in counted), ZERO)
        return (
            apply_rounding(total, settings.rounding_mode, settings.rounding_decimals),
            len(counted),
        )

    if method == "weighted_mean" and subject_weights:
        weight_total = ZERO
        weighted_sum = ZERO
        for subject_id, outcome in usable.items():
            weight = subject_weights.get(str(subject_id), Decimal("1"))
            weighted_sum += outcome.total_score * weight
            weight_total += weight
        if weight_total == ZERO:
            return None, 0
        return (
            apply_rounding(
                weighted_sum / weight_total, settings.rounding_mode, settings.rounding_decimals
            ),
            len(usable),
        )

    # mean_of_totals
    total = sum((outcome.total_score for outcome in usable.values()), ZERO)
    mean = total / Decimal(len(usable))
    return apply_rounding(mean, settings.rounding_mode, settings.rounding_decimals), len(usable)


def is_pass(total: Decimal | None, settings: EngineSettings) -> bool | None:
    if total is None:
        return None
    return total >= settings.pass_mark


# ==========================================================================
# Persistence -- loads the tenant's configuration, computes, materialises
# ==========================================================================
def load_settings(school_id=None) -> EngineSettings:
    from ..models import AssessmentSettings

    row = AssessmentSettings.query.first()
    if row is None:
        return EngineSettings()
    return EngineSettings(
        weight_interpretation=row.weight_interpretation,
        rounding_mode=row.rounding_mode,
        rounding_decimals=row.rounding_decimals,
        missing_score_rule=row.missing_score_rule,
        absent_rule=row.absent_rule,
        position_basis=row.position_basis,
        position_scope=row.position_scope,
        tie_rule=row.tie_rule,
        aggregate_method=row.aggregate_method,
        best_n=row.best_n,
        best_n_compulsory_subject_ids=tuple(
            str(s) for s in (row.best_n_compulsory_subject_ids or [])
        ),
        pass_mark=Decimal(row.pass_mark),
    )


def load_components(subject_id=None) -> list[ComponentConfig]:
    from ..models import AssessmentComponent

    rows = AssessmentComponent.query.filter_by(is_active=True).all()
    return [
        ComponentConfig(
            id=str(row.id),
            code=row.code,
            name=row.name,
            weight=Decimal(row.weight),
            max_score=Decimal(row.max_score),
            sequence=row.sequence,
        )
        for row in rows
        if subject_id is None or row.applies_to_subject(subject_id)
    ]


def load_bands(class_subject=None, school_class=None) -> list[BandConfig]:
    """Resolve the applicable scale: per subject, then per level, then default."""
    from ..models import GradeScale

    scale = None
    if class_subject is not None and class_subject.grade_scale_id:
        scale = GradeScale.query.filter_by(id=class_subject.grade_scale_id).first()

    if scale is None and school_class is not None:
        for candidate in GradeScale.query.all():
            applies = candidate.applies_to or {}
            levels = [str(level) for level in applies.get("levels", [])]
            curricula = [str(c) for c in applies.get("curricula", [])]
            if levels and str(school_class.level) in levels:
                scale = candidate
                break
            if curricula and school_class.curriculum and school_class.curriculum in curricula:
                scale = candidate
                break

    if scale is None:
        scale = GradeScale.query.filter_by(is_default=True).first() or GradeScale.query.first()

    if scale is None:
        return []

    return [
        BandConfig(
            grade=band.grade,
            min_score=Decimal(band.min_score),
            max_score=Decimal(band.max_score),
            remark=band.remark,
            points=Decimal(band.points) if band.points is not None else None,
            sequence=band.sequence,
        )
        for band in scale.bands
    ]


def recompute_class_term(class_id, term_id) -> dict:
    """Compute every subject for every enrolled student, then rank the class.

    Positions require the whole class, so this is the unit of computation even
    when only one student's score changed.
    """
    from ..extensions import db
    from ..models import (
        AssessmentScore,
        ClassSubject,
        Enrollment,
        Result,
        SchoolClass,
        Term,
        TermResult,
    )
    from ..tenancy import current_school_id
    from ..utils.errors import not_found

    school_class = SchoolClass.query.filter_by(id=class_id).first()
    if school_class is None:
        raise not_found("Class")
    term = Term.query.filter_by(id=term_id).first()
    if term is None:
        raise not_found("Term")

    school_id = current_school_id()
    settings = load_settings()
    class_subjects = ClassSubject.query.filter_by(class_id=school_class.id).all()
    enrollments = Enrollment.query.filter_by(class_id=school_class.id, status="active").all()
    student_ids = [e.student_id for e in enrollments]

    if not student_ids or not class_subjects:
        return {"students": 0, "subjects": len(class_subjects), "results_written": 0}

    scores = AssessmentScore.query.filter(
        AssessmentScore.class_id == school_class.id,
        AssessmentScore.term_id == term.id,
    ).all()

    # (student_id, subject_id) -> {component_id: ScoreInput}
    score_index: dict[tuple, dict[str, ScoreInput]] = {}
    for score in scores:
        key = (score.student_id, score.subject_id)
        score_index.setdefault(key, {})[str(score.component_id)] = ScoreInput(
            component_id=str(score.component_id),
            raw_score=Decimal(score.raw_score) if score.raw_score is not None else None,
            is_absent=score.is_absent,
        )

    computed_at = datetime.now(timezone.utc)
    # student_id -> subject_id -> outcome
    outcomes: dict[uuid.UUID, dict[str, SubjectOutcome]] = {sid: {} for sid in student_ids}
    subject_weights: dict[str, Decimal] = {}

    for class_subject in class_subjects:
        components = load_components(subject_id=class_subject.subject_id)
        bands = load_bands(class_subject=class_subject, school_class=school_class)
        subject_weights[str(class_subject.subject_id)] = sum(
            (c.weight for c in components), ZERO
        ) or Decimal("1")

        for student_id in student_ids:
            entry = score_index.get((student_id, class_subject.subject_id), {})
            outcomes[student_id][str(class_subject.subject_id)] = grade_subject(
                entry, components, bands, settings
            )

    # ---- subject positions, ranked within the configured scope --------------
    subject_positions: dict[str, dict[str, int]] = {}
    for class_subject in class_subjects:
        subject_key = str(class_subject.subject_id)
        rankable = {
            str(student_id): outcome.total_score
            for student_id, subjects in outcomes.items()
            if (outcome := subjects.get(subject_key)) is not None
            and outcome.has_total
            and outcome.is_ranked
        }
        subject_positions[subject_key] = rank(rankable, settings.tie_rule)

    # ---- persist per-subject results ---------------------------------------
    existing_results = {
        (r.student_id, r.subject_id): r
        for r in Result.query.filter(
            Result.class_id == school_class.id, Result.term_id == term.id
        ).all()
    }

    written = 0
    for student_id in student_ids:
        for class_subject in class_subjects:
            subject_key = str(class_subject.subject_id)
            outcome = outcomes[student_id][subject_key]
            row = existing_results.get((student_id, class_subject.subject_id))
            if row is None:
                row = Result(
                    school_id=school_id,
                    student_id=student_id,
                    subject_id=class_subject.subject_id,
                    class_id=school_class.id,
                    term_id=term.id,
                )
                db.session.add(row)
            row.total_score = outcome.total_score
            row.grade = outcome.grade
            row.remark = outcome.remark
            row.points = outcome.points
            row.is_ranked = outcome.is_ranked
            row.component_breakdown = outcome.breakdown
            row.subject_position = subject_positions[subject_key].get(str(student_id))
            row.computed_at = computed_at
            written += 1

    # ---- aggregate and overall position ------------------------------------
    aggregates: dict[str, Decimal] = {}
    aggregate_counts: dict[uuid.UUID, int] = {}
    for student_id in student_ids:
        aggregate, counted = compute_aggregate(
            outcomes[student_id], settings, subject_weights=subject_weights
        )
        aggregate_counts[student_id] = counted
        if aggregate is not None:
            aggregates[str(student_id)] = aggregate

    if settings.aggregate_method == "sum_of_best_n_points":
        # Fewer points is a better aggregate; invert so the ranking stays "highest first".
        ranking_input = {key: -value for key, value in aggregates.items()}
    else:
        ranking_input = aggregates
    overall_positions = rank(ranking_input, settings.tie_rule)

    existing_term_results = {
        r.student_id: r
        for r in TermResult.query.filter(
            TermResult.class_id == school_class.id, TermResult.term_id == term.id
        ).all()
    }

    for student_id in student_ids:
        row = existing_term_results.get(student_id)
        if row is None:
            row = TermResult(
                school_id=school_id,
                student_id=student_id,
                class_id=school_class.id,
                term_id=term.id,
            )
            db.session.add(row)
        aggregate = aggregates.get(str(student_id))
        row.aggregate = aggregate
        row.aggregate_method = settings.aggregate_method
        row.subjects_counted = aggregate_counts[student_id]
        row.overall_position = overall_positions.get(str(student_id))
        row.class_size = len(student_ids)
        row.is_ranked = aggregate is not None
        row.computed_at = computed_at

    db.session.flush()
    return {
        "class_id": str(school_class.id),
        "term_id": str(term.id),
        "students": len(student_ids),
        "subjects": len(class_subjects),
        "results_written": written,
        "computed_at": computed_at.isoformat(),
    }
