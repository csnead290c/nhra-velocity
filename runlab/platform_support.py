from __future__ import annotations

"""Small platform boundary for NHRA Velocity desktop integration.

Core engineering code should not branch on operating system.  This module keeps
OS-specific packaging/update/integration capability decisions explicit and easy
to regression-test as macOS becomes a first-class target.
"""

from dataclasses import dataclass
import os
import platform
import sys


@dataclass(frozen=True)
class PlatformSupport:
    id: str
    display_name: str
    packaged_app_kind: str
    secure_credential_store: str
    automatic_installer_launch: bool
    vendor_windows_dlls: bool


def platform_id(system: str | None = None) -> str:
    name = (system or platform.system()).strip().lower()
    if name == "windows":
        return "windows"
    if name == "darwin":
        return "macos"
    if name == "linux":
        return "linux"
    return name or "unknown"


def current_platform_support(system: str | None = None) -> PlatformSupport:
    pid = platform_id(system)
    if pid == "windows":
        return PlatformSupport(
            id="windows",
            display_name="Windows",
            packaged_app_kind="inno-exe",
            secure_credential_store="Windows Credential Manager",
            automatic_installer_launch=True,
            vendor_windows_dlls=True,
        )
    if pid == "macos":
        return PlatformSupport(
            id="macos",
            display_name="macOS",
            packaged_app_kind="app-bundle",
            secure_credential_store="macOS Keychain",
            automatic_installer_launch=False,
            vendor_windows_dlls=False,
        )
    if pid == "linux":
        return PlatformSupport(
            id="linux",
            display_name="Linux",
            packaged_app_kind="source-development",
            secure_credential_store="Secret Service / system keyring",
            automatic_installer_launch=False,
            vendor_windows_dlls=False,
        )
    return PlatformSupport(
        id=pid,
        display_name=pid or "Unknown",
        packaged_app_kind="unsupported",
        secure_credential_store="system keyring",
        automatic_installer_launch=False,
        vendor_windows_dlls=False,
    )


def is_frozen_app() -> bool:
    return bool(getattr(sys, "frozen", False))


def macos_app_bundle() -> bool:
    return platform_id() == "macos" and is_frozen_app() and ".app/Contents/MacOS" in str(sys.executable)


def dev_home_override_present() -> bool:
    return bool(os.environ.get("NHRA_VELOCITY_HOME") or os.environ.get("NHRA_TECH_DATA_HOME"))
