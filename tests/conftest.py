"""Pytest fixtures for PFF integration tests.

Resolves test-data paths from environment variables first, then falls back
to ``tests/local_paths.py`` (gitignored). Tests requiring data are skipped
gracefully when neither source provides a usable path.
"""
import os
from pathlib import Path

import pytest

try:
    from tests import local_paths
except ImportError:
    local_paths = None


def _resolve(env_var, attr):
    val = os.environ.get(env_var)
    if not val and local_paths is not None:
        val = getattr(local_paths, attr, None)
    return Path(val) if val else None


def _require(env_var, attr, label):
    p = _resolve(env_var, attr)
    if p is None:
        pytest.skip(
            f"{label} not configured. Set {env_var} or copy "
            f"tests/local_paths.example.py to tests/local_paths.py and fill in."
        )
    if not p.exists():
        pytest.skip(f"{label} path does not exist: {p}")
    return p


@pytest.fixture(scope="session")
def bhutan_gee_dir():
    """Directory containing the GEE-exported Bhutan bundle (BTN_*.tif + AOI .shp)."""
    return _require("PFF_BHUTAN_GEE_DIR", "BHUTAN_GEE_DIR", "Bhutan GEE export bundle")


@pytest.fixture(scope="session")
def bhutan_plugin_out():
    """Directory containing a baseline full_workflow output for Bhutan."""
    return _require(
        "PFF_BHUTAN_PLUGIN_OUT", "BHUTAN_PLUGIN_OUT", "Bhutan plugin output baseline"
    )
