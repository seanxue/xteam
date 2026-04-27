from pathlib import Path

import pytest


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_xteam_root(tmp_path: Path) -> Path:
    """Root for .xteam/<session>/ paths during tests."""
    root = tmp_path / ".xteam"
    root.mkdir()
    return root
