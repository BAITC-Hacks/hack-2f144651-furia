"""Canonical file presence is independent of the number of imported rows."""
import io
import zipfile

import pandas as pd
import pytest

from ekt.application import import_canonical_files
from ekt.ingest import merge_tables, read_canonical
from ekt.schema import Bundle, REQUIRED, SCHEMAS, normalize


def _previous():
    tables = {
        "sales": pd.DataFrame([
            ["TEST", "0007", "W", "2026-09-01", "D1", "C1", -2, "pcs", "return"],
        ], columns=SCHEMAS["sales"]),
        "inbound": pd.DataFrame([
            ["TEST", "0007", "W", "IN1", 11, "2026-09-25", "expected", "confirmed"],
        ], columns=SCHEMAS["inbound"]),
    }
    for name, frame in tables.items():
        frame["source_file"] = "synthetic-test.csv"
        frame["source_sheet"] = name
        frame["source_row"] = "12"
    return normalize(Bundle(tables, ["Synthetic backend test only"], "synthetic"))


def _file(extension, tables):
    """Construct in-memory synthetic files without common fixtures."""
    if extension == "csv":
        assert len(tables) == 1
        name, frame = next(iter(tables.items()))
        return f"{name}.csv", frame.to_csv(index=False).encode("utf-8-sig")
    buffer = io.BytesIO()
    if extension == "zip":
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, frame in tables.items():
                archive.writestr(f"{name}.csv", frame.to_csv(index=False))
    else:
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            for name, frame in tables.items():
                frame.to_excel(writer, sheet_name=name, index=False)
    return f"input.{extension}", buffer.getvalue()


def _assert_unchanged(actual, expected):
    assert actual.mode == expected.mode
    assert actual.notes == expected.notes
    for name in expected.tables:
        pd.testing.assert_frame_equal(actual[name], expected[name])
        assert actual[name].attrs == expected[name].attrs


@pytest.mark.parametrize("extension", ["csv", "zip", "xlsx"])
def test_present_header_only_table_clears_only_that_table(extension):
    previous = _previous()
    original = previous.copy()
    upload = _file(extension, {"inbound": pd.DataFrame(columns=SCHEMAS["inbound"])})

    result = import_canonical_files([upload], previous=previous)

    assert result["inbound"].empty
    for name in previous.tables:
        if name != "inbound":
            pd.testing.assert_frame_equal(result[name], previous[name])
    assert result["sales"].quantity_signed.tolist() == [-2.0]
    assert result["sales"].sku_1c.tolist() == ["0007"]
    _assert_unchanged(previous, original)


@pytest.mark.parametrize("extension", ["csv", "zip", "xlsx"])
def test_omitted_table_is_preserved_when_another_table_is_imported(extension):
    previous = _previous()
    sales = previous["sales"].copy()
    sales.loc[0, "quantity_signed"] = 19

    result = import_canonical_files([_file(extension, {"sales": sales})], previous=previous)

    assert result["sales"].quantity_signed.tolist() == [19.0]
    pd.testing.assert_frame_equal(result["inbound"], previous["inbound"])


@pytest.mark.parametrize("copy_and_normalize", [False, True])
def test_empty_import_survives_copy_and_normalize_without_mutating_inputs(copy_and_normalize):
    previous = _previous()
    original = previous.copy()
    filename, data = _file("csv", {"inbound": pd.DataFrame(columns=REQUIRED["inbound"])})
    addition = read_canonical(data, filename)
    if copy_and_normalize:
        addition = normalize(addition.copy())
    addition_original = addition.copy()

    result = merge_tables(previous, addition)

    assert result["inbound"].empty
    pd.testing.assert_frame_equal(result["sales"], previous["sales"])
    _assert_unchanged(previous, original)
    _assert_unchanged(addition, addition_original)


def test_plain_empty_bundle_does_not_request_table_deletion():
    previous = _previous()
    addition = normalize(Bundle({"inbound": pd.DataFrame(columns=SCHEMAS["inbound"])}))

    result = merge_tables(previous, addition)

    _assert_unchanged(result, previous)


@pytest.mark.parametrize("clear_last", [False, True])
def test_sequential_files_apply_last_present_table_even_when_empty(clear_last):
    previous = _previous()
    inbound = previous["inbound"].copy()
    inbound.loc[0, "qty_base_unit"] = 23
    replacement = _file("csv", {"inbound": inbound})
    clearing = _file("csv", {"inbound": pd.DataFrame(columns=SCHEMAS["inbound"])})
    files = [replacement, clearing] if clear_last else [clearing, replacement]
    # This last file omits inbound and must not undo either operation.
    files.append(_file("csv", {"sales": previous["sales"]}))

    result = import_canonical_files(files, previous=previous)

    if clear_last:
        assert result["inbound"].empty
    else:
        assert result["inbound"].qty_base_unit.tolist() == [23.0]
    pd.testing.assert_frame_equal(result["sales"], previous["sales"])


@pytest.mark.parametrize("extension", ["csv", "zip", "xlsx"])
@pytest.mark.parametrize("columns", [["unrecognized"], ["supplier_id", "sku_1c"]])
def test_malformed_empty_headers_do_not_clear_previous(extension, columns):
    previous = _previous()
    original = previous.copy()
    upload = _file(extension, {"inbound": pd.DataFrame(columns=columns)})

    with pytest.raises(ValueError, match="inbound.*заголовки"):
        import_canonical_files([upload], previous=previous)

    _assert_unchanged(previous, original)


@pytest.mark.parametrize("data", [b"", b"\n \n", b"\xef\xbb\xbf"])
def test_blank_csv_is_not_a_request_to_clear(data):
    previous = _previous()
    original = previous.copy()

    with pytest.raises(ValueError, match="заголовков"):
        import_canonical_files([("inbound.csv", data)], previous=previous)

    _assert_unchanged(previous, original)


def test_empty_excel_sheet_is_not_a_request_to_clear():
    previous = _previous()
    original = previous.copy()
    upload = _file("xlsx", {"inbound": pd.DataFrame()})

    with pytest.raises(ValueError, match="inbound.*заголовки"):
        import_canonical_files([upload], previous=previous)

    _assert_unchanged(previous, original)


def test_failed_file_after_clear_keeps_previous_bundle():
    previous = _previous()
    original = previous.copy()
    clear = _file("csv", {"inbound": pd.DataFrame(columns=SCHEMAS["inbound"])})
    bad_sales = b"supplier_id,sku_1c,quantity_signed\nTEST,0007,not-a-number\n"

    with pytest.raises(ValueError, match="sales.quantity_signed"):
        import_canonical_files([clear, ("sales.csv", bad_sales)], previous=previous)

    _assert_unchanged(previous, original)


def test_nonempty_partial_import_still_defers_required_field_validation():
    previous = _previous()

    result = import_canonical_files([
        ("inbound.csv", b"supplier_id,sku_1c,qty_base_unit\nTEST,0007,13\n"),
    ], previous=previous)

    assert result["inbound"].qty_base_unit.tolist() == [13.0]
    assert result["inbound"].status.isna().all()
    pd.testing.assert_frame_equal(result["sales"], previous["sales"])
