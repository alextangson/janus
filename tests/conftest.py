from pathlib import Path

import pytest

from gatekeeper.registry import Registry

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture
def registry() -> Registry:
    return Registry.from_file(DATA / "devices.json")
