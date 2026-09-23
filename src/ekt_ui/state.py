"""Frontend-owned session transitions; input operations remain in ekt."""
import streamlit as st


def clear_review():
    for key in ("approval", "review_edits", "review_context", "review_editor_key", "review_notice"):
        st.session_state.pop(key, None)
    st.session_state.review_revision = st.session_state.get("review_revision", 0) + 1


def invalidate_calculation():
    clear_review()
    for key in ("calculation", "input_signature"):
        st.session_state.pop(key, None)


def load_bundle(bundle):
    st.session_state.bundle = bundle
    st.session_state.version = st.session_state.get("version", 0) + 1
    invalidate_calculation()
    st.session_state.pop("import_result", None)
    st.session_state.pop("input_notice", None)


def invalidate_changed_inputs(signature):
    previous = st.session_state.get("input_signature")
    if previous is not None and previous != signature:
        invalidate_calculation()
        return True
    return False
