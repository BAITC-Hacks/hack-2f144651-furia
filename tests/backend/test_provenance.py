"""Synthetic records with distinct sources; no partner archive is represented."""
import pandas as pd
import pytest

from ekt.application import edit_table
from ekt.schema import Bundle, PROVENANCE, normalize


def sales_bundle():
    # Same business key/document/date, different actual records: KEY is not an ID.
    rows = [
        dict(supplier_id="TEST", sku_1c="00007", warehouse_scope="TEST-WH",
             date="2026-01-02", document_id="TEST-DOC", customer_id=customer,
             quantity_signed=quantity, unit="pcs", document_type="sale",
             comment=comment, source_file=f"synthetic-{label}.csv",
             source_sheet="sales", source_row=source_row, data_mode="synthetic")
        for label, customer, quantity, comment, source_row in [
            ("A", "TEST-A", 3, None, "12"),
            ("B", "TEST-B", 5, "detail", "37"),
            ("C", "TEST-C", -2, None, "91"),
        ]
    ]
    return normalize(Bundle({"sales": pd.DataFrame(rows)}, mode="synthetic"))


def assert_manual(frame, positions, name="sales"):
    for i in positions:
        assert frame.loc[i, "source_file"] == "manual"
        assert frame.loc[i, "source_sheet"] == name
        assert frame.loc[i, "source_row"] == str(i + 2)
        assert frame.loc[i, "data_mode"] == "manual"


def assert_sources(actual, original, mapping):
    for new_position, old_position in mapping.items():
        pd.testing.assert_series_equal(
            actual.loc[new_position, PROVENANCE],
            original.loc[old_position, PROVENANCE], check_names=False)


@pytest.mark.parametrize("positions", [[2, 0, 1], [2, 0], [1, 2]])
@pytest.mark.parametrize("index_kind", ["reset", "duplicate", "original"])
def test_reorder_and_delete_keep_each_records_own_source(positions, index_kind):
    bundle = sales_bundle()
    before = bundle.copy()
    changed = bundle["sales"].drop(columns=PROVENANCE).iloc[positions].copy()
    if index_kind == "reset":
        changed = changed.reset_index(drop=True)
    elif index_kind == "duplicate":
        changed.index = [99] * len(changed)
    # Column order has no identifying meaning either.
    changed = changed[changed.columns[::-1]]
    editor_before = changed.copy(deep=True)

    result = edit_table(bundle, "sales", changed)

    assert_sources(result["sales"], before["sales"], dict(enumerate(positions)))
    assert result["sales"].sku_1c.eq("00007").all()
    for name in before.tables:
        pd.testing.assert_frame_equal(bundle[name], before[name])
    pd.testing.assert_frame_equal(changed, editor_before)


def test_inserting_duplicate_marks_all_indistinguishable_copies_manual():
    bundle = sales_bundle()
    changed = bundle["sales"].drop(columns=PROVENANCE).iloc[[0, 1, 0, 2]]

    result = edit_table(bundle, "sales", changed)["sales"]

    assert len(result) == 4  # No deduplication or summation.
    assert result.quantity_signed.tolist() == [3, 5, 3, -2]
    assert_manual(result, [0, 2])
    assert_sources(result, bundle["sales"], {1: 1, 3: 2})


@pytest.mark.parametrize("positions", [[0, 1, 2, 3], [3, 1, 0, 2], [0, 1, 2], [3, 1, 2]])
def test_old_duplicates_never_choose_a_source_by_position(positions):
    bundle = sales_bundle()
    duplicate = bundle["sales"].iloc[[0]].copy()
    duplicate["source_file"] = "different-synthetic-source.csv"
    duplicate["source_row"] = "777"
    bundle.tables["sales"] = pd.concat([bundle["sales"], duplicate], ignore_index=True)
    changed = bundle["sales"].drop(columns=PROVENANCE).iloc[positions].reset_index(drop=True)

    result = edit_table(bundle, "sales", changed)["sales"]

    ambiguous = [i for i, old in enumerate(positions) if old in (0, 3)]
    assert_manual(result, ambiguous)
    assert_sources(result, bundle["sales"],
                   {i: old for i, old in enumerate(positions) if old in (1, 2)})


@pytest.mark.parametrize("column,value", [("quantity_signed", 8), ("comment", "corrected")])
def test_changed_content_after_reorder_is_manual(column, value):
    bundle = sales_bundle()
    changed = bundle["sales"].drop(columns=PROVENANCE).iloc[[2, 0, 1]].reset_index(drop=True)
    changed.loc[0, column] = value

    result = edit_table(bundle, "sales", changed)["sales"]

    assert_manual(result, [0])
    assert_sources(result, bundle["sales"], {1: 0, 2: 1})


@pytest.mark.parametrize("operation", ["remove", "add"])
def test_extra_column_values_participate_in_identity(operation):
    bundle = sales_bundle()
    changed = bundle["sales"].drop(columns=PROVENANCE).copy()
    if operation == "remove":
        changed = changed.drop(columns="comment")
    else:
        changed["extra_detail"] = [None, "new value", None]

    result = edit_table(bundle, "sales", changed)["sales"]

    assert_manual(result, [1])
    assert_sources(result, bundle["sales"], {0: 0, 2: 2})


def test_equivalent_normalized_values_keep_sources():
    bundle = sales_bundle()
    changed = bundle["sales"].drop(columns=PROVENANCE).astype(object)
    changed["quantity_signed"] = ["3.00", "5", "-2.0"]
    changed["date"] = ["2026-01-02", pd.Timestamp("2026-01-02"), "2026-01-02T12:30:00"]
    changed["comment"] = [float("nan"), " detail ", None]
    changed["sku_1c"] = " 00007 "

    result = edit_table(bundle, "sales", changed)["sales"]

    assert_sources(result, bundle["sales"], {0: 0, 1: 1, 2: 2})
    assert result.quantity_signed.tolist() == [3, 5, -2]


def test_missing_dates_and_booleans_match_after_normalization():
    bundle = normalize(Bundle({"monthly_sales": pd.DataFrame([
        dict(supplier_id="TEST", sku_1c="00007", warehouse_scope="TEST-WH",
             month="2026-01-01", qty_net=3, is_complete=True,
             coverage_start=None, coverage_end=None, source_file="synthetic-monthly.csv",
             source_row="88", data_mode="synthetic")])}, mode="synthetic"))
    changed = bundle["monthly_sales"].drop(columns=PROVENANCE).astype(object)
    changed["is_complete"] = "да"
    changed["coverage_start"] = None
    changed["coverage_end"] = ""

    result = edit_table(bundle, "monthly_sales", changed)["monthly_sales"]

    assert_sources(result, bundle["monthly_sales"], {0: 0})


def test_new_row_and_forged_provenance_do_not_inherit_sources():
    bundle = sales_bundle()
    changed = bundle["sales"].iloc[[2, 0, 1, 0]].reset_index(drop=True)
    changed.loc[3, "customer_id"] = "TEST-NEW"
    changed.loc[:, "source_file"] = "forged.csv"
    changed.loc[:, "source_row"] = "999"
    changed.loc[:, "data_mode"] = "partner"
    editor_before = changed.copy(deep=True)

    result = edit_table(bundle, "sales", changed)["sales"]

    assert_sources(result, bundle["sales"], {0: 2, 1: 0, 2: 1})
    assert_manual(result, [3])
    pd.testing.assert_frame_equal(changed, editor_before)


def test_invalid_edit_does_not_mutate_either_input():
    bundle = sales_bundle()
    before = bundle.copy()
    changed = bundle["sales"].drop(columns=PROVENANCE).astype(object)
    changed.loc[1, "quantity_signed"] = "not a number"
    editor_before = changed.copy(deep=True)

    with pytest.raises(ValueError, match="quantity_signed"):
        edit_table(bundle, "sales", changed)

    for name in before.tables:
        pd.testing.assert_frame_equal(bundle[name], before[name])
    pd.testing.assert_frame_equal(changed, editor_before)


@pytest.mark.parametrize("column", ["quantity_signed", "date"])
@pytest.mark.parametrize("clear", [False, True])
def test_raw_invalid_table_can_be_repaired_or_cleared(column, clear):
    bundle = sales_bundle()
    changed = bundle["sales"].drop(columns=PROVENANCE).copy()
    if clear:
        changed = changed.iloc[0:0]
    bundle.tables["sales"] = bundle["sales"].astype(object)
    bundle["sales"].loc[0, column] = "invalid"
    before = bundle.copy()
    editor_before = changed.copy(deep=True)

    result = edit_table(bundle, "sales", changed)["sales"]

    pd.testing.assert_frame_equal(result.drop(columns=PROVENANCE), changed)
    assert_manual(result, range(len(result)))
    for name in before.tables:
        pd.testing.assert_frame_equal(bundle[name], before[name])
    pd.testing.assert_frame_equal(changed, editor_before)
