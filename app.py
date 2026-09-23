"""Stable entry point: streamlit run app.py."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent / "src"))

from ekt_ui.app import main

main()
