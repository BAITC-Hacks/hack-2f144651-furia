"""Input workflows shared by UI and other local clients; no Streamlit state."""
import pandas as pd

from .schema import Bundle, PROVENANCE, SCHEMAS, normalize
from .ingest import merge_tables, read_canonical


def import_canonical_files(files, mode="manual", previous=None):
    """Read (filename, bytes) pairs, optionally replacing tables in a bundle."""
    combined = previous.copy() if previous is not None else Bundle(mode=mode)
    for filename, data in files:
        combined = merge_tables(combined, read_canonical(data, filename, mode))
    return combined


def replace_supplier(previous, incoming, supplier):
    """Replace one supplier's reports, preserving other partner suppliers."""
    result = incoming.copy()
    if previous is not None and previous.mode == "partner":
        for name in SCHEMAS:
            retained = previous[name].loc[~previous[name].supplier_id.eq(supplier)]
            result.tables[name] = pd.concat([retained, result[name]], ignore_index=True)
        result.notes = list(dict.fromkeys(previous.notes + result.notes))
    return normalize(result)


def edit_table(bundle, name, changed):
    """Save editor rows; unchanged positional rows retain their provenance."""
    updated = bundle.copy()
    frame = bundle[name]
    editable = frame[[col for col in frame.columns if col not in PROVENANCE]]
    changed = changed.copy().reset_index(drop=True)
    for col in PROVENANCE:
        changed[col] = "manual" if col in ["source_file", "data_mode"] else name if col == "source_sheet" else ""
    for i in range(min(len(changed), len(frame))):
        if changed.loc[i, editable.columns].equals(editable.iloc[i]):
            for col in PROVENANCE:
                changed.loc[i, col] = frame.iloc[i][col]
    updated.tables[name] = changed
    return normalize(updated)
