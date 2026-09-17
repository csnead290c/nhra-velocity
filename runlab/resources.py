from __future__ import annotations

from pathlib import Path
import sys


def resource_root() -> Path:
    """Root containing packaged read-only resources.

    PyInstaller exposes bundled data below ``sys._MEIPASS``. Source runs use
    the project root (parent of the runlab package).
    """
    frozen=getattr(sys,'_MEIPASS',None)
    if frozen:
        return Path(frozen)
    return Path(__file__).resolve().parents[1]


def bundled_examples_dir() -> Path:
    return resource_root()/'examples'


def brand_asset(name: str) -> Path:
    """Return a bundled NHRA Velocity brand asset path."""
    return resource_root() / 'assets' / str(name)
