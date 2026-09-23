import pandas as pd
import numpy as np
import pytest
from ekt.schema import Bundle, SCHEMAS, normalize


@pytest.fixture
def make_bundle():
    def factory(start="2026-06-01", end="2026-08-31", rate=10., values=None):
        dates = pd.date_range(start, end)
        quantities = np.full(len(dates), rate) if values is None else np.asarray(values)
        records = [["S", "000001_", "W", date, f"D{i}", "anon-regular", q, "шт", "sale"] for i, (date, q) in enumerate(zip(dates, quantities))]
        tables = {
            "products": pd.DataFrame([["S", "000001_", "ART-1", "Synthetic product", "шт", "A"]], columns=SCHEMAS["products"]),
            "sales": pd.DataFrame(records, columns=SCHEMAS["sales"]),
            "stock_snapshots": pd.DataFrame([["S", "000001_", "W", end, 0, 0, 0, "current"]], columns=SCHEMAS["stock_snapshots"]),
            "policies": pd.DataFrame([["S", "A", 14, 7, 2, 0, 1, "demo"], ["S", "B", 14, 7, 10, 0, 1, "demo"]], columns=SCHEMAS["policies"]),
        }
        return normalize(Bundle(tables, [], "synthetic"))
    return factory
