import pandas as pd
import pytest

from ekt.application import edit_table, import_canonical_files, replace_supplier
from ekt.demo import demo_bundle
from ekt.schema import Bundle, PROVENANCE, normalize


def test_import_replaces_uploaded_table_without_mutating_previous():
    previous = demo_bundle()
    original = previous["products"].copy(deep=True)
    payload = b"supplier_id,sku_1c,name,unit,category_id\nIEK,000001_,New,pcs,A\n"
    result = import_canonical_files([("products.csv", payload)], "manual", previous)
    assert result["products"].sku_1c.tolist() == ["000001_"]
    assert result["products"].name.tolist() == ["New"]
    pd.testing.assert_frame_equal(result["sales"], previous["sales"])
    pd.testing.assert_frame_equal(previous["products"], original)


def test_failed_import_keeps_previous_bundle():
    previous = demo_bundle()
    original = previous.copy()
    with pytest.raises(ValueError):
        import_canonical_files([("unknown.csv", b"x\n1\n")], previous=previous)
    for name in original.tables:
        pd.testing.assert_frame_equal(previous[name], original[name])


def test_supplier_replacement_isolated_and_repeatable():
    previous = demo_bundle()
    previous.mode = "partner"
    for frame in previous.tables.values():
        frame["data_mode"] = "partner"
    previous = normalize(previous)
    incoming = normalize(Bundle({name: frame.loc[frame.supplier_id.eq("IEK")].copy()
                                 for name, frame in previous.tables.items()}, ["new import"], "partner"))
    incoming["products"].loc[:, "name"] = "Replacement"
    original = previous.copy()
    source = incoming.copy()
    result = replace_supplier(previous, incoming, "IEK")
    repeated = replace_supplier(result, incoming, "IEK")
    for name in previous.tables:
        pd.testing.assert_frame_equal(result[name], repeated[name])
        pd.testing.assert_frame_equal(previous[name], original[name])
        pd.testing.assert_frame_equal(incoming[name], source[name])
        pd.testing.assert_frame_equal(
            result[name].loc[result[name].supplier_id.eq("Systeme")].reset_index(drop=True),
            previous[name].loc[previous[name].supplier_id.eq("Systeme")].reset_index(drop=True))
    assert result["products"].loc[result["products"].supplier_id.eq("IEK"), "name"].eq("Replacement").all()


def test_non_partner_previous_is_not_merged():
    previous = demo_bundle()
    incoming = normalize(Bundle(mode="partner"))
    result = replace_supplier(previous, incoming, "IEK")
    assert all(frame.empty for frame in result.tables.values())
    assert result.mode == "partner"


def test_manual_edits_preserve_unchanged_provenance_and_inputs():
    bundle = demo_bundle()
    original = bundle["products"].copy(deep=True)
    changed = original.drop(columns=PROVENANCE).copy()
    changed.loc[1, "name"] = "Manually corrected"
    editor_input = changed.copy(deep=True)
    result = edit_table(bundle, "products", changed)
    pd.testing.assert_series_equal(result["products"].loc[0, PROVENANCE], original.loc[0, PROVENANCE])
    assert result["products"].loc[1, "data_mode"] == "manual"
    assert result["products"].loc[1, "source_file"] == "manual"
    pd.testing.assert_frame_equal(bundle["products"], original)
    pd.testing.assert_frame_equal(changed, editor_input)


def test_editor_can_clear_table():
    bundle = demo_bundle()
    changed = bundle["inbound"].drop(columns=PROVENANCE).iloc[0:0]
    result = edit_table(bundle, "inbound", changed)
    assert result["inbound"].empty
    assert not bundle["inbound"].empty
