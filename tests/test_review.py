import numpy as np
import pandas as pd
import pytest

from ekt.engine import Calculation
from ekt.review import approve, export_frame, initial_edits, review_signature


@pytest.fixture
def calculation():
    return Calculation(pd.DataFrame({"row_id": ["a", "b"], "recommended_qty": [10., 20.]}), {}, "input-hash", {})


@pytest.mark.parametrize("operation", [approve, export_frame])
@pytest.mark.parametrize("bad", ["missing", "extra", "duplicate", "null", "blank", "number"])
def test_review_rejects_ambiguous_or_incomplete_identity(calculation, operation, bad):
    edits = initial_edits(calculation.rows).astype({"row_id": object})
    if bad == "missing":
        edits = edits.iloc[:1]
    elif bad == "extra":
        edits.loc[2] = ["unknown", False, 0, ""]
    elif bad == "duplicate":
        edits.loc[1, "row_id"] = "a"
    else:
        edits.loc[1, "row_id"] = {"null": None, "blank": " ", "number": 17}[bad]
    with pytest.raises(ValueError, match="row_id"):
        operation(calculation, edits)


def test_unselected_rows_still_require_id_and_full_coverage(calculation):
    edits = initial_edits(calculation.rows)
    edits.loc[1, "selected"] = False
    assert export_frame(calculation, edits).row_id.tolist() == ["a"]
    with pytest.raises(ValueError, match="row_id"):
        export_frame(calculation, edits.iloc[:1])


def test_reordering_keeps_identity_and_manual_zero(calculation):
    edits = initial_edits(calculation.rows).iloc[::-1].copy()
    edits.loc[edits.row_id.eq("a"), ["adjusted_qty", "reason"]] = [0, "Do not order"]
    approved = approve(calculation, edits)
    frame = export_frame(calculation, edits, approved).set_index("row_id")
    assert frame.loc["a", "final_qty"] == 0
    assert frame.loc["b", "final_qty"] == 20
    assert frame.approval_status.eq("approved").all()
    edits.loc[edits.row_id.eq("a"), "adjusted_qty"] = 1
    assert export_frame(calculation, edits, approved).approval_status.eq("draft").all()


@pytest.mark.parametrize("column", ["row_id", "selected", "adjusted_qty", "reason"])
def test_missing_edit_columns_are_clear_errors(calculation, column):
    with pytest.raises(ValueError, match="столбц"):
        approve(calculation, initial_edits(calculation.rows).drop(columns=column))


@pytest.mark.parametrize("bad", ["false", 1, "yes"])
def test_selected_is_not_truthiness_of_strings(calculation, bad):
    edits = initial_edits(calculation.rows).astype({"selected": object})
    edits.loc[0, "selected"] = bad
    with pytest.raises(ValueError, match="selected"):
        approve(calculation, edits)


def test_invalid_calculation_id_is_rejected(calculation):
    edits = initial_edits(calculation.rows)
    calculation.rows.loc[1, "row_id"] = "a"
    with pytest.raises(ValueError, match="row_id"):
        export_frame(calculation, edits)


def test_approval_is_invalidated_by_lossless_input_fingerprint(make_bundle):
    from ekt.engine import calculate

    bundle = make_bundle()
    previous = calculate(bundle, "2026-08-31")
    edits = initial_edits(previous.rows)
    approval = approve(previous, edits)
    bundle["sales"].loc[0, "quantity_signed"] = 10.00000000004
    current = calculate(bundle, "2026-08-31")

    assert previous.fingerprint != current.fingerprint
    assert export_frame(current, edits, approval).approval_status.eq("draft").all()


def test_review_signature_preserves_adjusted_quantity_precision(calculation):
    first = initial_edits(calculation.rows)
    second = first.copy()
    first.loc[0, "adjusted_qty"] = 230.0
    second.loc[0, "adjusted_qty"] = 231.0
    assert review_signature(calculation, first) != review_signature(calculation, second)
    subtle = second.copy()
    subtle.loc[0, "adjusted_qty"] = 230.00000000004
    assert review_signature(calculation, first) != review_signature(calculation, subtle)


def test_small_relative_change_requires_reason_and_manager_override(calculation):
    calculation.rows.loc[0, "recommended_qty"] = 1_000_000.0
    edits = initial_edits(calculation.rows)
    edits.loc[0, "adjusted_qty"] = 1_000_009.0

    frame = export_frame(calculation, edits)
    assert frame.loc[0, "manager_override"]
    with pytest.raises(ValueError, match="причину"):
        approve(calculation, edits)
    edits.loc[0, "reason"] = "обоснованное изменение"
    assert approve(calculation, edits).signature


@pytest.mark.parametrize("bad", ["not a number", np.inf, -1])
def test_invalid_quantity_is_value_error(calculation, bad):
    edits = initial_edits(calculation.rows).astype({"adjusted_qty": object})
    edits.loc[0, "adjusted_qty"] = bad
    with pytest.raises(ValueError):
        approve(calculation, edits)
