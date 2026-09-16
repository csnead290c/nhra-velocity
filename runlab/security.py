from __future__ import annotations

"""Product security policy switches.

NHRA Velocity is protected by default in both source/development and frozen builds.
The Tech Services authentication adapter is now bound, so source execution should
match the installed product's access boundary. An explicit development bypass
remains available for CI and controlled engineering work.
"""

import os
from typing import Mapping, Optional


def _truthy(value: str) -> bool:
    return str(value or "").strip().lower() in {"1","true","yes","on"}


def desktop_auth_required(*, frozen: Optional[bool]=None, env: Optional[Mapping[str,str]]=None) -> bool:
    environ=os.environ if env is None else env
    if "NHRA_TECH_AUTH_REQUIRED" in environ:
        return _truthy(environ.get("NHRA_TECH_AUTH_REQUIRED", ""))
    if _truthy(environ.get("NHRA_TECH_DEV_UNAUTHENTICATED", "")):
        return False
    # Auth is now bound to the existing Tech Services account system, so the
    # normal source-development build should enforce the same boundary as the
    # packaged executable. CI/controlled development can opt out explicitly via
    # NHRA_TECH_DEV_UNAUTHENTICATED=1.
    return True
