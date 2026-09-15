from __future__ import annotations

"""Product security policy switches.

A frozen/distributed desktop is protected by default. Source development stays
usable until the real Tech Services auth adapter is bound. Explicit environment
switches exist for CI/development packaging but should not be set in released
production shortcuts/installers.
"""

import os
import sys
from typing import Mapping, Optional


def _truthy(value: str) -> bool:
    return str(value or "").strip().lower() in {"1","true","yes","on"}


def desktop_auth_required(*, frozen: Optional[bool]=None, env: Optional[Mapping[str,str]]=None) -> bool:
    environ=os.environ if env is None else env
    if "NHRA_TECH_AUTH_REQUIRED" in environ:
        return _truthy(environ.get("NHRA_TECH_AUTH_REQUIRED", ""))
    if _truthy(environ.get("NHRA_TECH_DEV_UNAUTHENTICATED", "")):
        return False
    is_frozen=bool(getattr(sys,"frozen",False)) if frozen is None else bool(frozen)
    return is_frozen
