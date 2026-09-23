"""Input workflows shared by UI and other local clients; no Streamlit state."""
from collections import Counter

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


def _row_contents(frame, columns):
    """Exact normalized values, with one missing-value marker and no row index."""
    return [tuple(None if pd.isna(value) else value for value in row)
            for row in frame.reindex(columns=columns).itertuples(index=False, name=None)]


def edit_table(bundle, name, changed):
    """Retain sources only for unique, unchanged normalized row contents.

    All business columns participate, including optional extra columns. Ambiguous
    duplicates on either side are manual: row order/index cannot identify them.
    """
    updated = bundle.copy()
    changed = changed.copy().reset_index(drop=True)
    for col in PROVENANCE:
        changed[col] = "manual" if col in ["source_file", "data_mode"] else name if col == "source_sheet" else ""
    updated.tables[name] = changed
    updated = normalize(updated)
    saved = updated[name]
    try:
        frame = normalize(Bundle({name: bundle[name]}, mode=bundle.mode))[name]
    except ValueError:
        # A local caller may repair invalid raw input. Only the saved table must
        # normalize successfully; an invalid original cannot establish a source.
        return updated
    columns = sorted((set(frame.columns) | set(saved.columns)) - set(PROVENANCE))
    original_keys = _row_contents(frame, columns)
    saved_keys = _row_contents(saved, columns)
    original_counts, saved_counts = Counter(original_keys), Counter(saved_keys)
    originals = {key: i for i, key in enumerate(original_keys) if original_counts[key] == 1}
    for i, key in enumerate(saved_keys):
        if key in originals and saved_counts[key] == 1:
            saved.loc[i, PROVENANCE] = frame.loc[originals[key], PROVENANCE]
    return updated
