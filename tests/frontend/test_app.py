from pathlib import Path
from streamlit.testing.v1 import AppTest


def test_streamlit_full_demo():
    app = AppTest.from_file(Path(__file__).resolve().parents[2] / "app.py", default_timeout=30).run()
    assert not app.exception
    app.button[0].click().run()
    assert not app.exception
    next(b for b in app.button if b.label == "Рассчитать предложения").click().run()
    assert not app.exception
    assert app.metric[1].value == "4"
    next(b for b in app.button if b.label == "Утвердить выбранные позиции").click().run()
    assert not app.exception
    assert any("утверждены" in message.value for message in app.success)
    app.toggle[0].set_value(False).run()
    assert "calculation" not in app.session_state
    assert "approval" not in app.session_state
    assert not app.exception
