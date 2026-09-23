"""Frontend-owned session transitions; input operations remain in ekt."""
import streamlit as st


def invalidate_calculation():
    for key in ("calculation", "approval", "input_signature"):
        st.session_state.pop(key, None)


def load_bundle(bundle):
    st.session_state.bundle = bundle
    st.session_state.version = st.session_state.get("version", 0) + 1
    invalidate_calculation()
    st.session_state.pop("import_result", None)


def invalidate_changed_inputs(signature):
    previous = st.session_state.get("input_signature")
    if previous is not None and previous != signature:
        invalidate_calculation()
        return True
    return False
