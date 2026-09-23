"""CLI check of the same pipeline used by the app; no external services."""
from pathlib import Path
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ekt.demo import demo_bundle, canonical_zip
from ekt.ingest import read_canonical
from ekt.engine import calculate
from ekt.review import initial_edits, approve, export_frame
from ekt.export import csv_bytes, xlsx_bytes

bundle = read_canonical(canonical_zip(demo_bundle()), "synthetic_demo.zip", "synthetic")
result = calculate(bundle, "2026-09-22")
assert result.rows.recommended_qty.notna().all()
edits = initial_edits(result.rows)
edits.loc[0, "adjusted_qty"] = 0
edits.loc[0, "reason"] = "Synthetic smoke test"
frame = export_frame(result, edits, approve(result, edits))
assert frame.iloc[0].final_qty == 0
assert frame.approval_status.eq("approved").all()
print(json.dumps({"mode": bundle.mode, "positions": len(frame), "suppliers": frame.supplier_id.nunique(),
                  "csv_bytes": len(csv_bytes(frame)), "xlsx_bytes": len(xlsx_bytes(frame)),
                  "manual_zero": float(frame.iloc[0].final_qty), "approval": "approved"}, ensure_ascii=False))
