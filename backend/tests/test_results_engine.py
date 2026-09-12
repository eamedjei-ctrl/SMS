"""The highest-priority suite (spec 10.2).

An error here reaches a parent's hand on a printed card, so this file tests the
pure engine directly: every weighting shape, every rounding mode, every boundary
and every tie rule the configuration surface allows.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.results_engine import (
    BandConfig,
    ComponentConfig,
    EngineSettings,
    ScoreInput,
    apply_rounding,
    compute_aggregate,
    compute_subject_total,
    grade_subject,
    rank,
    resolve_band,
)

D = Decimal


def component(code, weight, max_score, sequence=0):
    return ComponentConfig(
        id=code,
        code=code,
        name=code,
        weight=D(str(weight)),
        max_score=D(str(max_score)),
        sequence=sequence,
    )


def scores(**values):
    return {
        code: ScoreInput(component_id=code, raw_score=None if raw is None else D(str(raw)))
        for code, raw in values.items()
    }


GES_BANDS = [
    BandConfig("1", D(80), D(100), "Excellent", D(1), 0),
    BandConfig("2", D(70), D(79), "Very Good", D(2), 1),
    BandConfig("3", D(60), D(69), "Good", D(3), 2),
    BandConfig("4", D(50), D(59), "Credit", D(4), 3),
    BandConfig("5", D(40), D(49), "Pass", D(5), 4),
    BandConfig("6", D(0), D(39), "Fail", D(6), 5),
]

CAMBRIDGE_BANDS = [
    BandConfig("A*", D(90), D(100), "Outstanding", None, 0),
    BandConfig("A", D(80), D(89), "Excellent", None, 1),
    BandConfig("B", D(70), D(79), "Very Good", None, 2),
    BandConfig("C", D(60), D(69), "Good", None, 3),
    BandConfig("D", D(50), D(59), "Satisfactory", None, 4),
    BandConfig("E", D(0), D(49), "Developing", None, 5),
]


# ==========================================================================
# Component shapes and weighting
# ==========================================================================
def test_two_components_fifty_fifty():
    components = [component("CA", 50, 100), component("EX", 50, 100)]
    outcome = compute_subject_total(scores(CA=60, EX=80), components, EngineSettings())
    assert outcome.total_score == D("70")


def test_three_components_30_20_50():
    components = [component("A", 30, 100), component("B", 20, 50), component("C", 50, 100)]
    # 60/100*30 = 18 ; 40/50*20 = 16 ; 90/100*50 = 45  -> 79
    outcome = compute_subject_total(scores(A=60, B=40, C=90), components, EngineSettings())
    assert outcome.total_score == D("79")


def test_five_components_uneven_weights():
    components = [
        component("HW", 10, 20),
        component("CT", 15, 30),
        component("PR", 15, 50),
        component("MT", 20, 40),
        component("EX", 40, 100),
    ]
    settings = EngineSettings(rounding_mode="half_up", rounding_decimals=2)
    outcome = compute_subject_total(scores(HW=18, CT=24, PR=40, MT=30, EX=72), components, settings)
    # 9 + 12 + 12 + 15 + 28.8 = 76.8
    assert outcome.total_score == D("76.80")


def test_the_spec_worked_example():
    """Class Test (20/20), Project (10/10), Exam (70/100) -> 68.1."""
    components = [component("CT", 20, 20), component("PR", 10, 10), component("EX", 70, 100)]
    settings = EngineSettings(rounding_decimals=1)
    outcome = grade_subject(scores(CT=16, PR=8, EX=63), components, GES_BANDS, settings)
    assert outcome.total_score == D("68.1")
    assert outcome.grade == "3"
    assert outcome.remark == "Good"
    assert outcome.points == D(3)


def test_weights_as_arbitrary_points_not_percentages():
    """Weights need not sum to 100; the engine never assumes a scale."""
    components = [component("A", 3, 10), component("B", 7, 10)]
    outcome = compute_subject_total(scores(A=10, B=10), components, EngineSettings())
    assert outcome.total_score == D("10")


def test_same_raw_scores_under_two_curricula_differ_correctly():
    """The acceptance criterion: no code change, different configured outcome."""
    ges_components = [component("CLS", 30, 100), component("EXM", 70, 100)]
    cambridge_components = [component("CW", 40, 100), component("EX", 60, 100)]

    ges = grade_subject(
        scores(CLS=80, EXM=60), ges_components, GES_BANDS, EngineSettings(rounding_decimals=0)
    )
    cambridge = grade_subject(
        {
            "CW": ScoreInput("CW", D(80)),
            "EX": ScoreInput("EX", D(60)),
        },
        cambridge_components,
        CAMBRIDGE_BANDS,
        EngineSettings(rounding_decimals=1),
    )

    assert ges.total_score == D("66")  # 24 + 42
    assert ges.grade == "3"
    assert cambridge.total_score == D("68.0")  # 32 + 36
    assert cambridge.grade == "C"


# ==========================================================================
# Missing scores and absence
# ==========================================================================
def test_missing_score_treated_as_zero():
    components = [component("CA", 50, 100), component("EX", 50, 100)]
    outcome = compute_subject_total(
        scores(CA=80, EX=None), components, EngineSettings(missing_score_rule="treat_as_zero")
    )
    assert outcome.total_score == D("40")
    assert outcome.is_ranked is True


def test_missing_score_excludes_student_from_ranking():
    components = [component("CA", 50, 100), component("EX", 50, 100)]
    outcome = compute_subject_total(
        scores(CA=80, EX=None),
        components,
        EngineSettings(missing_score_rule="exclude_from_ranking"),
    )
    assert outcome.total_score == D("40")
    assert outcome.is_ranked is False


def test_absent_treated_as_zero():
    components = [component("CA", 50, 100), component("EX", 50, 100)]
    entries = {
        "CA": ScoreInput("CA", D(80)),
        "EX": ScoreInput("EX", None, is_absent=True),
    }
    outcome = compute_subject_total(
        entries, components, EngineSettings(absent_rule="treat_as_zero")
    )
    assert outcome.total_score == D("40")


def test_absent_ignored_and_remaining_components_reweighted():
    """The surviving components carry the full weight, not a partial total."""
    components = [component("CA", 30, 100), component("EX", 70, 100)]
    entries = {
        "CA": ScoreInput("CA", D(80)),
        "EX": ScoreInput("EX", None, is_absent=True),
    }
    outcome = compute_subject_total(
        entries, components, EngineSettings(absent_rule="ignore_and_reweight")
    )
    # 24 of a counted weight of 30, scaled to 100 -> 80
    assert outcome.total_score == D("80")


def test_absent_can_block_computation_entirely():
    components = [component("CA", 30, 100), component("EX", 70, 100)]
    entries = {
        "CA": ScoreInput("CA", D(80)),
        "EX": ScoreInput("EX", None, is_absent=True),
    }
    outcome = compute_subject_total(
        entries, components, EngineSettings(absent_rule="block_computation")
    )
    assert outcome.is_blocked is True
    assert outcome.total_score is None
    assert outcome.is_ranked is False


def test_absent_can_exclude_from_ranking():
    components = [component("CA", 50, 100), component("EX", 50, 100)]
    entries = {
        "CA": ScoreInput("CA", D(90)),
        "EX": ScoreInput("EX", None, is_absent=True),
    }
    outcome = compute_subject_total(
        entries, components, EngineSettings(absent_rule="exclude_from_ranking")
    )
    assert outcome.total_score == D("45")
    assert outcome.is_ranked is False


def test_every_component_reweighted_away_yields_no_total():
    components = [component("CA", 50, 100), component("EX", 50, 100)]
    entries = {
        "CA": ScoreInput("CA", None, is_absent=True),
        "EX": ScoreInput("EX", None, is_absent=True),
    }
    outcome = compute_subject_total(
        entries, components, EngineSettings(absent_rule="ignore_and_reweight")
    )
    assert outcome.total_score is None
    assert outcome.is_ranked is False


# ==========================================================================
# Rounding, at every mode and boundary
# ==========================================================================
@pytest.mark.parametrize(
    "value,mode,decimals,expected",
    [
        ("68.15", "half_up", 1, "68.2"),
        ("68.25", "half_up", 1, "68.3"),
        ("68.5", "half_up", 0, "69"),
        ("67.5", "half_up", 0, "68"),
        ("68.5", "half_even", 0, "68"),
        ("67.5", "half_even", 0, "68"),
        ("68.25", "half_even", 1, "68.2"),
        ("68.35", "half_even", 1, "68.4"),
        ("68.4567", "none", 0, "68.4567"),
        ("79.999", "half_up", 2, "80.00"),
    ],
)
def test_rounding_modes(value, mode, decimals, expected):
    assert apply_rounding(D(value), mode, decimals) == D(expected)


def test_rounding_can_move_a_score_across_a_band_boundary():
    """79.6 rounds to 80 and becomes grade 1 -- the school's rule, applied."""
    components = [component("EX", 100, 100)]
    rounded = grade_subject(
        scores(EX=79.6), components, GES_BANDS, EngineSettings(rounding_decimals=0)
    )
    unrounded = grade_subject(
        scores(EX=79.6), components, GES_BANDS, EngineSettings(rounding_mode="none")
    )
    assert rounded.total_score == D("80") and rounded.grade == "1"
    assert unrounded.grade == "2"


# ==========================================================================
# Band resolution at the edges
# ==========================================================================
@pytest.mark.parametrize(
    "score,expected",
    [
        (100, "1"),
        (80, "1"),  # lower edge of the top band
        (79.999, "2"),
        (79, "2"),  # upper edge
        (70, "2"),
        (69.5, "3"),
        (40, "5"),
        (39.999, "6"),
        (0, "6"),
    ],
)
def test_band_boundaries_are_inclusive_on_both_edges(score, expected):
    band = resolve_band(D(str(score)), GES_BANDS)
    assert band is not None and band.grade == expected


def test_score_outside_every_band_returns_no_grade():
    assert resolve_band(D("120"), GES_BANDS) is None


def test_no_components_configured_is_not_a_crash():
    outcome = compute_subject_total({}, [], EngineSettings())
    assert outcome.total_score is None and outcome.is_ranked is False


# ==========================================================================
# Positions and ties
# ==========================================================================
def test_ranking_orders_highest_first():
    positions = rank({"a": D(90), "b": D(70), "c": D(80)})
    assert positions == {"a": 1, "c": 2, "b": 3}


def test_two_way_tie_shares_a_position_and_skips_the_next():
    positions = rank({"a": D(90), "b": D(90), "c": D(70)}, "shared_position")
    assert positions["a"] == 1 and positions["b"] == 1
    assert positions["c"] == 3


def test_three_way_tie_shares_a_position():
    positions = rank({"a": D(90), "b": D(90), "c": D(90), "d": D(50)}, "shared_position")
    assert positions["a"] == positions["b"] == positions["c"] == 1
    assert positions["d"] == 4


def test_whole_class_tied():
    positions = rank({k: D(75) for k in "abcdef"}, "shared_position")
    assert set(positions.values()) == {1}


def test_sequential_tie_rule_gives_distinct_positions():
    positions = rank({"a": D(90), "b": D(90), "c": D(70)}, "sequential")
    assert sorted(positions.values()) == [1, 2, 3]


def test_class_of_one_student():
    assert rank({"only": D(64)}) == {"only": 1}


# ==========================================================================
# Aggregation
# ==========================================================================
def _outcome(total, points=None):
    from app.services.results_engine import SubjectOutcome

    return SubjectOutcome(
        total_score=D(str(total)), points=None if points is None else D(str(points))
    )


def test_mean_of_totals():
    outcomes = {"m": _outcome(80), "e": _outcome(70), "s": _outcome(60)}
    aggregate, counted = compute_aggregate(outcomes, EngineSettings(rounding_decimals=2))
    assert aggregate == D("70.00") and counted == 3


def test_best_n_when_n_is_less_than_subjects_taken():
    """Fewer points is better, so best-N keeps the lowest point values."""
    outcomes = {
        "m": _outcome(80, 1),
        "e": _outcome(70, 2),
        "s": _outcome(60, 3),
        "x": _outcome(40, 5),
    }
    settings = EngineSettings(aggregate_method="sum_of_best_n_points", best_n=3)
    aggregate, counted = compute_aggregate(outcomes, settings)
    assert aggregate == D("6")  # 1 + 2 + 3
    assert counted == 3


def test_best_n_when_n_exceeds_subjects_taken():
    outcomes = {"m": _outcome(80, 1), "e": _outcome(70, 2)}
    settings = EngineSettings(aggregate_method="sum_of_best_n_points", best_n=6)
    aggregate, counted = compute_aggregate(outcomes, settings)
    assert aggregate == D("3") and counted == 2


def test_best_n_always_counts_compulsory_subjects():
    outcomes = {
        "core_maths": _outcome(45, 5),
        "easy_one": _outcome(95, 1),
        "easy_two": _outcome(92, 1),
    }
    settings = EngineSettings(
        aggregate_method="sum_of_best_n_points",
        best_n=2,
        best_n_compulsory_subject_ids=("core_maths",),
    )
    aggregate, counted = compute_aggregate(outcomes, settings)
    assert aggregate == D("6")  # compulsory 5 + best optional 1
    assert counted == 2


def test_weighted_mean_uses_subject_weights():
    outcomes = {"m": _outcome(90), "e": _outcome(60)}
    settings = EngineSettings(aggregate_method="weighted_mean", rounding_decimals=1)
    aggregate, _ = compute_aggregate(outcomes, settings, subject_weights={"m": D(3), "e": D(1)})
    assert aggregate == D("82.5")


def test_aggregate_ignores_subjects_with_no_total():
    from app.services.results_engine import SubjectOutcome

    outcomes = {"m": _outcome(80), "blocked": SubjectOutcome(total_score=None, is_blocked=True)}
    aggregate, counted = compute_aggregate(outcomes, EngineSettings())
    assert aggregate == D("80") and counted == 1


def test_student_with_no_usable_subjects_has_no_aggregate():
    aggregate, counted = compute_aggregate({}, EngineSettings())
    assert aggregate is None and counted == 0


# ==========================================================================
# Idempotency
# ==========================================================================
def test_computing_twice_produces_identical_results():
    components = [component("CA", 30, 100), component("EX", 70, 100)]
    settings = EngineSettings(rounding_decimals=1)
    first = grade_subject(scores(CA=71, EX=64), components, GES_BANDS, settings)
    second = grade_subject(scores(CA=71, EX=64), components, GES_BANDS, settings)
    assert (first.total_score, first.grade, first.points) == (
        second.total_score,
        second.grade,
        second.points,
    )


def test_configuration_change_changes_the_outcome():
    """Same raw scores, 30/70 then 50/50 -- totals differ, with no code change."""
    thirty_seventy = [component("CA", 30, 100), component("EX", 70, 100)]
    fifty_fifty = [component("CA", 50, 100), component("EX", 50, 100)]
    raw = scores(CA=90, EX=50)

    assert compute_subject_total(raw, thirty_seventy, EngineSettings()).total_score == D("62")
    assert compute_subject_total(raw, fifty_fifty, EngineSettings()).total_score == D("70")


def test_breakdown_records_every_component_state():
    components = [component("CA", 50, 100), component("EX", 50, 100)]
    entries = {
        "CA": ScoreInput("CA", D(80)),
        "EX": ScoreInput("EX", None, is_absent=True),
    }
    outcome = compute_subject_total(entries, components, EngineSettings())
    assert outcome.breakdown["CA"]["state"] == "scored"
    assert outcome.breakdown["CA"]["contribution"] == 40.0
    assert outcome.breakdown["EX"]["state"] == "absent_zero"
    assert outcome.breakdown["EX"]["is_absent"] is True
