"""UI fixtures exercise real backend operations and the root entry point."""
from io import BytesIO
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from ekt_ui import review


class Upload(BytesIO):
    def __init__(self, name, data):
        super().__init__(data)
        self.name = name


@pytest.fixture
def app():
    return AppTest.from_file(Path(__file__).resolve().parents[2] / "app.py", default_timeout=30).run()


@pytest.fixture
def calculated_app(app):
    next(b for b in app.button if b.label == "Загрузить демо").click().run()
    next(b for b in app.button if b.label == "Рассчитать предложения").click().run()
    assert not app.exception
    return app


@pytest.fixture
def uploads(monkeypatch):
    # AppTest has no uploader interaction API; only this widget boundary is replaced.
    files = {"canonical": [], "partner": None}

    def uploader(label, **kwargs):
        if kwargs.get("accept_multiple_files"):
            return [Upload(name, data) for name, data in files["canonical"]]
        upload = files["partner"]
        return Upload(*upload) if upload else None

    monkeypatch.setattr(st, "file_uploader", uploader)
    return files


@pytest.fixture
def downloads(monkeypatch):
    contents = {}
    original_csv = review.csv_bytes
    original_xlsx = review.xlsx_bytes

    def csv(frame, separator):
        contents["csv"] = original_csv(frame, separator)
        return contents["csv"]

    def xlsx(frame, metadata):
        contents["xlsx"] = original_xlsx(frame, metadata)
        return contents["xlsx"]

    monkeypatch.setattr(review, "csv_bytes", csv)
    monkeypatch.setattr(review, "xlsx_bytes", xlsx)
    return contents
