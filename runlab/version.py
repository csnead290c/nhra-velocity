from __future__ import annotations

"""Single source of truth for application version/channel.

Development branches use semantic pre-release versions. Stable GitHub releases
remove the pre-release suffix and are tagged ``vX.Y.Z``.
"""

__version__ = "0.38.0-dev.1"
__channel__ = "development"


def version_tuple() -> tuple[int, int, int]:
    core = __version__.split("-", 1)[0]
    major, minor, patch = (int(part) for part in core.split("."))
    return major, minor, patch
