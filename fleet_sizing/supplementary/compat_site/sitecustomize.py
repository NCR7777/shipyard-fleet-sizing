"""Loaded by every Python process when supplementary/compat_site is on PYTHONPATH (needed off Windows for exact_run.py)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import compat  # noqa: E402,F401
