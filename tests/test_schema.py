"""Regression checks for shared types used by partner adapters and UI."""
import pandas as pd
import pytest

from ekt.engine import calculate
from ekt.schema import normalize


def test_unconfirmed_moq_stays_numeric_without_becoming_an_approved_policy(make_bundle):
    bundle = make_bundle()
    bundle["products"]["unconfirmed_moq"] = "10.0"
    normalized = normalize(bundle)

    assert pd.api.types.is_numeric_dtype(normalized["products"]["unconfirmed_moq"])
    assert normalized["products"].unconfirmed_moq.iloc[0] == 10.0
    assert normalize(normalized)["products"].unconfirmed_moq.iloc[0] == 10.0
    row = calculate(normalized, "2026-08-31").rows.iloc[0]
    assert pd.isna(row.recommended_qty)
    assert "семантика MOQ" in row.explanation


def test_invalid_unconfirmed_moq_reports_numeric_input_error(make_bundle):
    bundle = make_bundle()
    bundle["products"]["unconfirmed_moq"] = "ten"
    with pytest.raises(ValueError, match="products.unconfirmed_moq"):
        normalize(bundle)
