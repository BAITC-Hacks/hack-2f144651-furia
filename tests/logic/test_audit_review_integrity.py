"""Causal AUD-LOG-01 regressions for exact input/result/review identity."""
import hashlib

import numpy as np
import pandas as pd
import pytest

from ekt.engine import Calculation
from ekt.review import approve, export_frame, initial_edits, review_signature
from ekt.schema import Bundle, fingerprint


def calculation():
    return Calculation(pd.DataFrame({"row_id": ["a"], "supplier_id": ["S"],
                                     "recommended_qty": [10.0]}), {}, "same-inputs", {})


@pytest.mark.parametrize("column,value", [("supplier_id", "OTHER"), ("recommended_qty", 20.0)])
def test_approval_binds_actual_calculation_rows(column, value):
    result = calculation()
    edits = initial_edits(result.rows)
    approved = approve(result, edits)
    result.rows.loc[0, column] = value
    assert export_frame(result, edits, approved).approval_status.eq("draft").all()


def test_approval_binds_actual_calculation_config():
    result = calculation()
    edits = initial_edits(result.rows)
    approved = approve(result, edits)
    result.config["as_of"] = "2026-09-01"
    assert export_frame(result, edits, approved).approval_status.eq("draft").all()


@pytest.mark.parametrize("bad", [np.inf, -np.inf, -1, "not-a-number"])
def test_invalid_recommendation_cannot_be_replaced_by_manual_quantity(bad):
    result = calculation()
    result.rows["recommended_qty"] = pd.Series([bad])
    edits = pd.DataFrame({"row_id": ["a"], "selected": [True],
                          "adjusted_qty": [10.0], "reason": ["manual"]})
    with pytest.raises(ValueError, match="количество|количеств|расчёт"):
        approve(result, edits)


@pytest.mark.parametrize("dtype", [float, object])
def test_fingerprint_preserves_adjacent_binary_floats(dtype):
    first = Bundle({"sales": pd.DataFrame({"quantity_signed": pd.Series([1.0], dtype=dtype)})})
    second = first.copy()
    second["sales"].loc[0, "quantity_signed"] = np.nextafter(1.0, np.inf)
    assert fingerprint(first) != fingerprint(second)
    assert fingerprint(first) == fingerprint(first.copy())


def test_fingerprint_preserves_submillisecond_dates():
    first = Bundle({"sales": pd.DataFrame({"date": [pd.Timestamp("2026-01-01T00:00:00.000001")]})})
    second = first.copy()
    second["sales"].loc[0, "date"] = pd.Timestamp("2026-01-01T00:00:00.000002")
    assert fingerprint(first) != fingerprint(second)


def test_legacy_approval_and_subtle_edits_are_not_reused():
    result = calculation()
    edits = initial_edits(result.rows)
    approved = approve(result, edits)
    legacy = hashlib.sha256((result.fingerprint + edits.to_json(orient="split", default_handler=str)).encode()).hexdigest()
    assert approved.signature != legacy
    changed = edits.copy()
    changed.loc[0, "adjusted_qty"] = np.nextafter(10.0, np.inf)
    assert review_signature(result, edits) != review_signature(result, changed)
    assert export_frame(result, changed, approved).approval_status.eq("draft").all()
