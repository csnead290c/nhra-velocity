from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = (ROOT / "desktop.py").read_text(encoding="utf-8")
INSTALLER = (ROOT / "installer" / "NHRA-Velocity.iss").read_text(encoding="utf-8")
WINDOWS_BUILD = (ROOT / ".github" / "workflows" / "windows-build.yml").read_text(encoding="utf-8")
RELEASE = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
BUILD_BAT = (ROOT / "build_windows_exe.bat").read_text(encoding="utf-8")


def test_desktop_exposes_network_free_packaged_smoke_mode():
    assert "def _desktop_smoke_requested()" in DESKTOP
    assert "'--smoke-test' in sys.argv" in DESKTOP
    assert "NHRA_TECH_DEV_UNAUTHENTICATED" in DESKTOP
    assert "PACKAGED_DESKTOP_SMOKE_PASS" in DESKTOP
    assert "_run_desktop_smoke_scenario(win,app)" in DESKTOP


def test_windows_development_build_smokes_frozen_and_installed_executables():
    assert "Smoke frozen desktop" in WINDOWS_BUILD
    assert "Smoke installed desktop" in WINDOWS_BUILD
    assert WINDOWS_BUILD.count("--smoke-test") >= 2
    assert "NHRA_VELOCITY_HOME" in WINDOWS_BUILD
    assert "WaitForExit(60000)" in WINDOWS_BUILD


def test_release_workflow_smokes_frozen_and_installed_executables():
    assert "Smoke frozen desktop" in RELEASE
    assert "Smoke installed release" in RELEASE
    assert RELEASE.count("--smoke-test") >= 2
    assert "WaitForExit(60000)" in RELEASE


def test_installer_version_reads_same_environment_variable_as_workflows():
    assert 'GetEnv("NHRA_VELOCITY_VERSION")' in INSTALLER
    assert "NHRA_TECH_VERSION" not in INSTALLER
    assert "NHRA_VELOCITY_VERSION=$version" in WINDOWS_BUILD
    assert "NHRA_VELOCITY_VERSION=$version" in RELEASE


def test_product_audit_is_bundled_into_windows_build():
    assert 'PRODUCT_AUDIT_v0_38.md' in BUILD_BAT


def test_brand_assets_are_bundled_into_windows_executable_and_installer():
    assets = ROOT / "assets"
    for name in ("nhra-velocity.ico", "nhra-velocity-256.png", "nhra-velocity-logo.svg", "nhra-velocity-mark.svg"):
        assert (assets / name).is_file(), name
    assert '--icon "assets\\nhra-velocity.ico"' in BUILD_BAT
    assert '--add-data "assets;assets"' in BUILD_BAT
    assert 'SetupIconFile=..\\assets\\nhra-velocity.ico' in INSTALLER


def test_installer_creates_desktop_shortcut_by_default():
    assert 'Name: "{autodesktop}\\NHRA Velocity"' in INSTALLER
    task_line = next(line for line in INSTALLER.splitlines() if line.startswith('Name: "desktopicon"'))
    assert 'unchecked' not in task_line.lower()


def test_development_shortcut_script_uses_velocity_icon():
    shortcut = (ROOT / 'scripts' / 'Create-NHRA-Velocity-Dev-Shortcut.ps1').read_text(encoding='utf-8')
    assert 'NHRA Velocity Dev.lnk' in shortcut
    assert 'NHRA-Velocity.ico' in shortcut
    assert 'IconLocation' in shortcut
