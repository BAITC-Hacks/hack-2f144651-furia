"""Bounded synthetic EKT audit; no partner files or external services.

Run with the project interpreter. JSON lines report measured phases, not SLAs.
Each size runs in a fresh subprocess, limited to 180 seconds and 800 MiB RSS.
"""
from __future__ import annotations

import argparse
import ctypes
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
import json
import os
from pathlib import Path
import platform
import site
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def memory(pid):
    if os.name != "nt":
        return None

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    api = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
    api.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    handle = kernel.OpenProcess(0x1000 | 0x10, False, pid)
    if not handle:
        return None
    try:
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if api(handle, ctypes.byref(counters), counters.cb):
            return {"rss_mib": round(counters.WorkingSetSize / 2**20, 2),
                    "peak_rss_mib": round(counters.PeakWorkingSetSize / 2**20, 2)}
    finally:
        kernel.CloseHandle(handle)


def emit(**data):
    print(json.dumps(data, ensure_ascii=True), flush=True)


def phase(name, function):
    start = time.perf_counter()
    result = function()
    emit(phase=name, seconds=round(time.perf_counter() - start, 4),
         memory=memory(os.getpid()))
    return result


def synthetic(count, days):
    import numpy as np
    import pandas as pd
    from ekt.demo import DEMO_DATE
    from ekt.schema import Bundle, normalize

    skus = np.array([f"AUD-{i:07d}" for i in range(count)])
    suppliers = np.array(["IEK" if i % 2 == 0 else "Systeme" for i in range(count)])
    dates = pd.date_range(end=DEMO_DATE, periods=days)
    tables = {
        "products": pd.DataFrame(dict(supplier_id=suppliers, sku_1c=skus,
            supplier_sku=skus, name="Synthetic audit item", unit="pcs", category_id="A")),
        "sales": pd.DataFrame(dict(supplier_id=np.repeat(suppliers, days),
            sku_1c=np.repeat(skus, days), warehouse_scope="AUDIT",
            date=np.tile(dates.to_numpy(), count), document_id=np.tile([f"D{i}" for i in range(days)], count),
            customer_id="synthetic-customer", quantity_signed=np.tile(1 + np.arange(days) % 7 / 10, count),
            unit="pcs", document_type="sale")),
        "stock_snapshots": pd.DataFrame(dict(supplier_id=suppliers, sku_1c=skus,
            warehouse_scope="AUDIT", as_of=DEMO_DATE, on_hand=10.0, reserved=0.0,
            available=10.0, snapshot_kind="current")),
        "inbound": pd.DataFrame(dict(supplier_id=suppliers, sku_1c=skus,
            warehouse_scope="AUDIT", order_id="AUDIT-IN", qty_base_unit=4.0,
            eta=DEMO_DATE + pd.Timedelta(days=5), eta_kind="expected", status="confirmed")),
        "policies": pd.DataFrame(dict(supplier_id=["IEK", "Systeme"], category_id="A",
            lead_time_days=14, review_days=7, safety_days=3,
            min_order_qty=0, order_multiple=1, origin="synthetic audit")),
    }
    return normalize(Bundle(tables, ["SYNTHETIC AUDIT ONLY"], "synthetic"))


def worker(count, days, ui, concurrent):
    from ekt.application import import_canonical_files
    from ekt.demo import DEMO_DATE, canonical_zip
    from ekt.engine import calculate
    from ekt.export import csv_bytes, xlsx_bytes
    from ekt.review import approve, export_frame, initial_edits
    from ekt.schema import fingerprint, normalize, validate
    from ekt_ui.presentation import order_grid

    emit(kind="start", sku_count=count, sales_rows=count * days, days=days,
         python=platform.python_version(), platform=platform.system())
    bundle = phase("generate", lambda: synthetic(count, days))
    if concurrent > 1:
        def one(index):
            started = time.perf_counter()
            result = calculate(bundle, DEMO_DATE)
            assert len(result.rows) == count and result.rows.recommended_qty.notna().all()
            return {"job": index, "seconds": round(time.perf_counter() - started, 4)}
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=concurrent) as pool:
            jobs = list(pool.map(one, range(concurrent)))
        emit(kind="concurrent_calculation", threads=concurrent, jobs=jobs,
             wall_seconds=round(time.perf_counter()-started, 4), memory=memory(os.getpid()))
        return
    payload = phase("zip_input", lambda: canonical_zip(bundle))
    emit(kind="size", zip_bytes=len(payload), rows=sum(map(len, bundle.tables.values())))
    bundle = phase("canonical_import", lambda: import_canonical_files([("synthetic.zip", payload)], "synthetic"))
    issues = phase("validate", lambda: validate(bundle))
    assert not issues, issues
    calculation = phase("calculate", lambda: calculate(bundle, DEMO_DATE))
    assert len(calculation.rows) == count
    assert calculation.rows.recommended_qty.notna().all()
    edits = initial_edits(calculation.rows)
    edits.loc[0, ["adjusted_qty", "reason"]] = [0.0, "Synthetic audit manual zero"]
    approval = phase("approve", lambda: approve(calculation, edits))
    exported = phase("export_frame", lambda: export_frame(calculation, edits, approval))
    assert exported.iloc[0].final_qty == 0
    assert exported.approval_status.eq("approved").all()
    phase("order_grid", lambda: order_grid(calculation, edits))
    phase("input_fingerprint", lambda: fingerprint(normalize(bundle), calculation.config))
    csv = phase("csv_export", lambda: csv_bytes(exported))
    xlsx = phase("xlsx_export", lambda: xlsx_bytes(exported))
    phase("zip_current_inputs", lambda: canonical_zip(bundle))
    emit(kind="output", csv_bytes=len(csv), xlsx_bytes=len(xlsx), positions=len(exported))
    if ui:
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
        app.session_state.bundle = bundle
        app.session_state.version = 1
        app.session_state.calculation = calculation
        app.session_state.calc_version = 1
        app.session_state.review_edits = edits
        app.session_state.approval = approval
        phase("ui_initial_render", app.run)
        assert not app.exception, [error.message for error in app.exception]
        widget = next(x for x in app.segmented_control if x.label == "Поставщики")
        phase("ui_filter_rerun", lambda: widget.set_value("IEK").run())
        assert not app.exception, [error.message for error in app.exception]
    emit(kind="complete", memory=memory(os.getpid()))


def supervise(count, args):
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", str(count),
               "--days", str(args.days), "--concurrent", str(args.concurrent)] + (["--ui"] if args.ui else [])
    if os.name == "nt":
        # Windows venv python.exe is a redirector; monitor the real interpreter.
        boot = (f"import site,runpy; [site.addsitedir(p) for p in {site.getsitepackages()!r}]; "
                f"runpy.run_path({str(Path(__file__).resolve())!r}, run_name='__main__')")
        command = [sys._base_executable, "-c", boot] + command[2:]
    # Temporary output prevents a full stdout pipe blocking the measured child.
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        start = time.perf_counter()
        child = subprocess.Popen(command, cwd=ROOT, stdout=stdout, stderr=stderr,
                                 env={**os.environ, "PYTHONUTF8": "1"})
        stopped = None
        peak = 0.0
        while child.poll() is None:
            current = memory(child.pid)
            if current:
                peak = max(peak, current["peak_rss_mib"])
            if time.perf_counter() - start > args.timeout:
                stopped = "time_limit"
            if peak > args.memory_mib:
                stopped = "memory_limit"
            if stopped:
                child.kill()
                child.wait()
                break
            time.sleep(.2)
        stdout.seek(0)
        stderr.seek(0)
        for line in stdout.read().decode("utf-8", errors="replace").splitlines():
            print(line, flush=True)
        errors = stderr.read().decode("utf-8", errors="replace")
        emit(kind="supervisor", sku_count=count, returncode=child.returncode,
             stopped=stopped, wall_seconds=round(time.perf_counter()-start, 3),
             observed_peak_rss_mib=round(peak, 2),
             error_tail=errors[-2500:] if child.returncode else None)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", type=int, nargs="+", default=[10, 100, 500])
    parser.add_argument("--worker", type=int)
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--ui", action="store_true")
    parser.add_argument("--concurrent", type=int, choices=(1, 2), default=1)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--memory-mib", type=float, default=800)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker, args.days, args.ui, args.concurrent)
    else:
        for size in args.sizes:
            supervise(size, args)
