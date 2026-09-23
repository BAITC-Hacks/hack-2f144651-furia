"""Local review state. Approval is tied to both inputs and manager edits."""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import numpy as np
import pandas as pd


@dataclass
class Approval:
    signature: str = ""
    approved_at: str = ""


def initial_edits(rows):
    return pd.DataFrame({"row_id": rows.row_id, "selected": rows.recommended_qty.notna() & rows.recommended_qty.gt(0),
                         "adjusted_qty": rows.recommended_qty, "reason": ""})


def reviewed_rows(calculation, edits):
    frame = calculation.rows.merge(edits, on="row_id", validate="one_to_one")
    frame = frame.loc[frame["selected"].fillna(False)].copy()
    if frame.empty:
        return frame
    if frame["recommended_qty"].isna().any():
        raise ValueError("Нельзя экспортировать выбранные позиции с незавершённым расчётом")
    frame["final_qty"] = frame["adjusted_qty"].where(frame["adjusted_qty"].notna(), frame["recommended_qty"])
    if (~np.isfinite(frame["final_qty"]) | frame["final_qty"].lt(0)).any():
        raise ValueError("Итоговое количество должно быть конечным и неотрицательным")
    frame["manager_override"] = ~np.isclose(frame["final_qty"], frame["recommended_qty"])
    return frame


def review_signature(calculation, edits):
    return hashlib.sha256((calculation.fingerprint + edits.to_json(orient="split", default_handler=str)).encode()).hexdigest()


def approve(calculation, edits):
    frame = reviewed_rows(calculation, edits)
    if frame.empty:
        raise ValueError("Выберите хотя бы одну позицию")
    if (frame["manager_override"] & frame["reason"].fillna("").astype(str).str.strip().eq("")).any():
        raise ValueError("Укажите причину для каждого изменённого количества")
    return Approval(review_signature(calculation, edits), datetime.now(timezone.utc).isoformat())


def export_frame(calculation, edits, approval=None):
    frame = reviewed_rows(calculation, edits)
    approved = approval is not None and approval.signature == review_signature(calculation, edits)
    frame["approval_status"] = "approved" if approved else "draft"
    frame["approved_at"] = approval.approved_at if approved else ""
    return frame
