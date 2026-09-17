from pathlib import Path

from runlab.diagnostics import app_data_root
from runlab.platform_support import current_platform_support, platform_id


def test_platform_ids_are_stable():
    assert platform_id("Windows") == "windows"
    assert platform_id("Darwin") == "macos"
    assert platform_id("Linux") == "linux"


def test_macos_capability_contract_is_explicit():
    support = current_platform_support("Darwin")
    assert support.id == "macos"
    assert support.packaged_app_kind == "app-bundle"
    assert support.secure_credential_store == "macOS Keychain"
    assert support.automatic_installer_launch is False
    assert support.vendor_windows_dlls is False


def test_windows_capability_contract_retains_current_installer_behavior():
    support = current_platform_support("Windows")
    assert support.automatic_installer_launch is True
    assert support.vendor_windows_dlls is True


def test_macos_app_data_path(monkeypatch):
    import runlab.diagnostics as diagnostics

    monkeypatch.delenv("NHRA_VELOCITY_HOME", raising=False)
    monkeypatch.delenv("NHRA_TECH_DATA_HOME", raising=False)
    monkeypatch.setattr(diagnostics.platform, "system", lambda: "Darwin")
    path = diagnostics.app_data_root()
    assert path == Path.home() / "Library" / "Application Support" / "NHRA Velocity"
