"""Pytest config: ensure the tests/ directory is importable for helpers.py."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
