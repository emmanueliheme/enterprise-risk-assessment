from pathlib import Path

from streamlit.testing.v1 import AppTest


def _app():
    at = AppTest.from_file(str(Path(__file__).resolve().parent.parent / "app.py"), default_timeout=60)
    at.run()
    return at


def test_app_runs_without_errors():
    at = _app()
    assert not at.exception
    assert any("Enterprise Risk Assessment" in t.value for t in at.title)


def test_what_if_edit_changes_score():
    at = _app()
    before = at.session_state["edits"]
    assert before == {}
    at.session_state["edits"] = {"R22-D1": {"control_score": 5}}
    at.run()
    assert not at.exception
    assert any("what-if edits" in i.value for i in at.info)


def test_kri_overlay_toggle():
    at = _app()
    at.toggle[0].set_value(True).run()
    assert not at.exception
