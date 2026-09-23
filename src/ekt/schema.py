"""Canonical contracts, provenance, strict validation and stable fingerprints."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import numpy as np
import pandas as pd

KEY = ["supplier_id", "sku_1c", "warehouse_scope"]
PROVENANCE = ["source_file", "source_sheet", "source_row", "data_mode"]
SCHEMAS = {
    "products": ["supplier_id", "sku_1c", "supplier_sku", "name", "unit", "category_id"],
    "sales": KEY + ["date", "document_id", "customer_id", "quantity_signed", "unit", "document_type"],
    "monthly_sales": KEY + ["month", "qty_net", "is_complete", "coverage_start", "coverage_end"],
    "stock_snapshots": KEY + ["as_of", "on_hand", "reserved", "available", "snapshot_kind"],
    "inbound": KEY + ["order_id", "qty_base_unit", "eta", "eta_kind", "status"],
    "stockouts": KEY + ["start_date", "end_date", "evidence"],
    "policies": ["supplier_id", "category_id", "lead_time_days", "review_days", "safety_days", "min_order_qty", "order_multiple", "origin"],
    "growth_plan": ["supplier_id", "sku_1c", "category_id", "start_date", "end_date", "extra_growth_rate", "source"],
    "seasonal_prior": ["supplier_id", "category_id", "month_of_year", "factor", "known_as_of", "source"],
}
NUMBERS = {"quantity_signed", "qty_net", "on_hand", "reserved", "available", "qty_base_unit", "lead_time_days", "review_days", "safety_days", "min_order_qty", "order_multiple", "extra_growth_rate", "factor", "month_of_year"}
DATES = {"date", "month", "coverage_start", "coverage_end", "as_of", "eta", "start_date", "end_date", "known_as_of"}
REQUIRED = {
    "products": ["supplier_id", "sku_1c", "name"],
    "sales": KEY + ["date", "quantity_signed", "unit", "document_type"],
    "monthly_sales": KEY + ["month", "qty_net", "is_complete", "coverage_start", "coverage_end"],
    "stock_snapshots": KEY + ["as_of", "snapshot_kind"],
    "inbound": KEY + ["order_id", "qty_base_unit", "status"],
    "stockouts": KEY + ["start_date", "end_date", "evidence"],
    "policies": ["supplier_id", "lead_time_days", "review_days", "safety_days", "min_order_qty", "order_multiple", "origin"],
    "growth_plan": ["supplier_id", "start_date", "end_date", "extra_growth_rate", "source"],
    "seasonal_prior": ["supplier_id", "month_of_year", "factor", "known_as_of", "source"],
}


def empty_table(name):
    return pd.DataFrame(columns=SCHEMAS[name] + PROVENANCE)


@dataclass
class Bundle:
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    mode: str = "manual"

    def __post_init__(self):
        for name in SCHEMAS:
            self.tables.setdefault(name, empty_table(name))

    def __getitem__(self, name):
        return self.tables[name]

    def copy(self):
        return Bundle({k: v.copy(deep=True) for k, v in self.tables.items()}, self.notes.copy(), self.mode)


def normalize(bundle: Bundle) -> Bundle:
    result = bundle.copy()
    for name, frame in result.tables.items():
        for col in SCHEMAS[name] + PROVENANCE:
            if col not in frame:
                frame[col] = pd.NA
        for col in frame:
            if col in NUMBERS:
                original = frame[col].replace("", pd.NA)
                parsed = pd.to_numeric(original, errors="coerce")
                invalid = original.notna() & parsed.isna()
                if invalid.any():
                    raise ValueError(f"{name}.{col}: нечисловые значения, строки {(np.flatnonzero(invalid) + 2).tolist()[:10]}")
                frame[col] = parsed.astype(float)
            elif col in DATES:
                original = frame[col].replace("", pd.NA)
                parsed = pd.to_datetime(original, errors="coerce", format="mixed")
                if (original.notna() & parsed.isna()).any():
                    raise ValueError(f"{name}.{col}: неверная дата; используйте YYYY-MM-DD")
                frame[col] = parsed.dt.normalize()
            elif col == "is_complete":
                values = frame[col].astype("string").str.lower().str.strip()
                if not values.dropna().isin(["true", "false", "1", "0", "да", "нет"]).all():
                    raise ValueError("monthly_sales.is_complete: допустимы true/false")
                frame[col] = values.map({"true": True, "1": True, "да": True, "false": False, "0": False, "нет": False}).astype("boolean")
            else:
                frame[col] = frame[col].astype("string").str.strip().replace("", pd.NA)
        frame["data_mode"] = frame["data_mode"].fillna(bundle.mode)
        frame["source_file"] = frame["source_file"].fillna("manual")
        frame["source_sheet"] = frame["source_sheet"].fillna(name)
        frame["source_row"] = frame["source_row"].fillna(pd.Series([str(i + 2) for i in range(len(frame))], index=frame.index, dtype="string"))
        result.tables[name] = frame.reset_index(drop=True)
    return result


def validate(bundle: Bundle) -> list[str]:
    errors = []
    if bundle["products"].empty:
        errors.append("products: нет товаров")
    for name, frame in bundle.tables.items():
        if frame.empty:
            continue
        for col in REQUIRED[name]:
            missing = frame[col].isna()
            if missing.any():
                errors.append(f"{name}.{col}: пустые значения в строках {(np.flatnonzero(missing) + 2).tolist()[:8]}")
        for col in NUMBERS.intersection(frame.columns):
            finite = frame[col].dropna()
            if not np.isfinite(finite.to_numpy(dtype=float)).all():
                errors.append(f"{name}.{col}: NaN/Infinity недопустимы")
        if not frame["data_mode"].isin(["partner", "synthetic", "manual"]).all():
            errors.append(f"{name}: data_mode должен быть partner/synthetic/manual")
        if bundle.mode == "partner" and frame["data_mode"].eq("synthetic").any():
            errors.append(f"{name}: нельзя смешивать синтетику с данными партнёра")
        if name in ["sales", "monthly_sales", "stock_snapshots", "inbound", "stockouts"]:
            unknown = frame.merge(bundle["products"][["supplier_id", "sku_1c"]], on=["supplier_id", "sku_1c"], how="left", indicator=True)
            if unknown["_merge"].eq("left_only").any():
                errors.append(f"{name}: есть коды без соответствия в products")
    unique = {
        "products": ["supplier_id", "sku_1c"],
        "monthly_sales": KEY + ["month"],
        "stock_snapshots": KEY + ["as_of", "snapshot_kind"],
        "inbound": KEY + ["order_id", "eta"],
        "policies": ["supplier_id", "category_id"],
        "seasonal_prior": ["supplier_id", "category_id", "month_of_year", "known_as_of"],
    }
    for name, cols in unique.items():
        if bundle[name].duplicated(cols).any():
            errors.append(f"{name}: дубли ключа {', '.join(cols)}; строки не суммировались автоматически")
    for name in ["stockouts", "growth_plan"]:
        frame = bundle[name]
        if (frame["end_date"] < frame["start_date"]).any():
            errors.append(f"{name}: конец интервала раньше начала")
    monthly = bundle["monthly_sales"]
    if not monthly.empty:
        if (monthly["coverage_end"] < monthly["coverage_start"]).any():
            errors.append("monthly_sales: неверное покрытие дат")
        if (monthly["month"].dt.day != 1).any():
            errors.append("monthly_sales.month: первое число месяца")
        complete = monthly["is_complete"].fillna(False)
        if (complete & ((monthly["coverage_start"] != monthly["month"]) | (monthly["coverage_end"] != monthly["month"] + pd.offsets.MonthEnd(0)))).any():
            errors.append("monthly_sales: полный месяц должен иметь полное покрытие")
    policy = bundle["policies"]
    for col in ["lead_time_days", "review_days", "safety_days", "min_order_qty"]:
        if (policy[col] < 0).any():
            errors.append(f"policies.{col}: значение не может быть отрицательным")
    for col in ["lead_time_days", "review_days"]:
        if (policy[col].dropna() % 1 != 0).any():
            errors.append(f"policies.{col}: требуется целое число дней")
    if ((policy["order_multiple"] <= 0) | (policy["lead_time_days"] + policy["review_days"] <= 0)).any():
        errors.append("policies: кратность и горизонт должны быть больше 0")
    if ((policy["lead_time_days"] + policy["review_days"]) > 730).any():
        errors.append("policies: горизонт MVP ограничен 730 днями")
    if (bundle["growth_plan"]["extra_growth_rate"] < -1).any():
        errors.append("growth_plan: снижение ниже −100% недопустимо")
    if (bundle["inbound"]["qty_base_unit"] < 0).any():
        errors.append("inbound: отрицательное количество")
    if not bundle["inbound"]["status"].isin(["confirmed", "pending", "cancelled"]).all():
        errors.append("inbound.status: confirmed/pending/cancelled")
    prior = bundle["seasonal_prior"]
    if ((prior["factor"] <= 0) | ~prior["month_of_year"].isin(range(1, 13))).any():
        errors.append("seasonal_prior: месяцы 1–12, коэффициенты > 0")
    for _, group in prior.groupby(["supplier_id", "category_id", "known_as_of"], dropna=False):
        if len(group) != 12:
            errors.append("seasonal_prior: требуется ровно 12 месяцев для каждого набора")
    return errors


def fingerprint(bundle: Bundle, config=None):
    digest = hashlib.sha256()
    digest.update(bundle.mode.encode())
    for name in sorted(bundle.tables):
        digest.update(name.encode())
        digest.update(bundle[name].to_json(orient="split", date_format="iso", default_handler=str).encode())
    digest.update(json.dumps(config or {}, sort_keys=True, default=str).encode())
    return digest.hexdigest()


def select(frame, key):
    mask = pd.Series(True, index=frame.index)
    for col, value in zip(KEY, key):
        mask &= frame[col].eq(value).fillna(False)
    return frame.loc[mask].copy()
