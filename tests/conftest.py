"""Expose checkout sources to test subprocesses without installing the project."""

import os
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def source_environment():
    # pytest's pythonpath option updates sys.path, not the child environment.
    # CLI and simulator tests launch fresh Python interpreters, sometimes from
    # a different working directory, so propagate the absolute source path.
    source = str(Path(__file__).resolve().parents[1] / "src")
    previous = os.environ.get("PYTHONPATH")
    path = os.pathsep.join([source, previous]) if previous else source
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("PYTHONPATH", path)
        yield
