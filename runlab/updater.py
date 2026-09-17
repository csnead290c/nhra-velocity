from __future__ import annotations

"""Small, dependency-free update client for signed NHRA Velocity releases.

The application never replaces its own executable in-place. It downloads a
normal Windows installer, verifies its size/SHA-256 (and optionally its Windows
Authenticode signature), then launches the installer only after explicit user
approval.
"""

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import tempfile
from typing import Any, Mapping
from urllib.request import Request, urlopen

from .version import __version__
from .platform_support import current_platform_support

UPDATE_MANIFEST_ENV = "NHRA_TECH_UPDATE_MANIFEST_URL"
UPDATE_CHANNEL_ENV = "NHRA_TECH_UPDATE_CHANNEL"


@dataclass(frozen=True, order=True)
class ParsedVersion:
    major: int
    minor: int
    patch: int
    prerelease_rank: int
    prerelease_number: int


_PRE_RANK = {"dev": 0, "alpha": 1, "a": 1, "beta": 2, "b": 2, "rc": 3}
_VERSION_RE = re.compile(
    r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:[-.]?(?P<label>dev|alpha|a|beta|b|rc)[.-]?(?P<num>\d+)?)?$",
    re.IGNORECASE,
)


def parse_version(value: str) -> ParsedVersion:
    m = _VERSION_RE.fullmatch(str(value).strip())
    if not m:
        raise ValueError(f"Unsupported application version: {value!r}")
    label = (m.group("label") or "").lower()
    if label:
        rank = _PRE_RANK[label]
        number = int(m.group("num") or 0)
    else:
        rank = 4
        number = 0
    return ParsedVersion(
        int(m.group("major")), int(m.group("minor")), int(m.group("patch")), rank, number
    )


@dataclass(frozen=True)
class UpdateManifest:
    schema: int
    product: str
    version: str
    channel: str
    installer_url: str
    sha256: str
    size_bytes: int
    source_commit: str = ""
    release_notes_url: str = ""
    minimum_supported_version: str = ""
    mandatory: bool = False
    require_authenticode: bool = False
    authenticode_subject: str = ""

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "UpdateManifest":
        manifest = cls(
            schema=int(raw.get("schema", 0)),
            product=str(raw.get("product", "")),
            version=str(raw.get("version", "")),
            channel=str(raw.get("channel", "stable")),
            installer_url=str(raw.get("installer_url", "")),
            sha256=str(raw.get("sha256", "")).lower(),
            size_bytes=int(raw.get("size_bytes", 0)),
            source_commit=str(raw.get("source_commit", "")),
            release_notes_url=str(raw.get("release_notes_url", "")),
            minimum_supported_version=str(raw.get("minimum_supported_version", "")),
            mandatory=bool(raw.get("mandatory", False)),
            require_authenticode=bool(raw.get("require_authenticode", False)),
            authenticode_subject=str(raw.get("authenticode_subject", "")),
        )
        manifest.validate()
        return manifest

    def validate(self) -> None:
        if self.schema != 1:
            raise ValueError(f"Unsupported update manifest schema {self.schema}")
        if self.product != "NHRA Velocity":
            raise ValueError(f"Unexpected update product {self.product!r}")
        parse_version(self.version)
        if self.channel not in {"stable", "beta", "development"}:
            raise ValueError(f"Unsupported update channel {self.channel!r}")
        if not self.installer_url.lower().startswith("https://"):
            raise ValueError("Update installer_url must use HTTPS")
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("Update manifest SHA-256 must contain 64 lowercase hex characters")
        if self.size_bytes <= 0:
            raise ValueError("Update manifest size_bytes must be positive")
        if self.minimum_supported_version:
            parse_version(self.minimum_supported_version)

    def is_newer_than(self, current_version: str = __version__) -> bool:
        return parse_version(self.version) > parse_version(current_version)


@dataclass(frozen=True)
class UpdateCheck:
    current_version: str
    manifest: UpdateManifest
    available: bool
    current_below_minimum: bool


def configured_manifest_url(env: Mapping[str, str] | None = None) -> str:
    values = os.environ if env is None else env
    return str(values.get(UPDATE_MANIFEST_ENV, "")).strip()


def configured_channel(env: Mapping[str, str] | None = None) -> str:
    values = os.environ if env is None else env
    channel = str(values.get(UPDATE_CHANNEL_ENV, "stable")).strip().lower() or "stable"
    if channel not in {"stable", "beta", "development"}:
        raise ValueError(f"Invalid {UPDATE_CHANNEL_ENV}: {channel!r}")
    return channel


def fetch_manifest(url: str, *, timeout_s: float = 8.0) -> UpdateManifest:
    req = Request(url, headers={"User-Agent": f"NHRA-Velocity/{__version__}"})
    with urlopen(req, timeout=timeout_s) as response:  # noqa: S310 - URL is explicit/configured HTTPS
        payload = json.loads(response.read().decode("utf-8"))
    return UpdateManifest.from_dict(payload)


def check_for_update(
    url: str,
    *,
    current_version: str = __version__,
    channel: str = "stable",
    timeout_s: float = 8.0,
) -> UpdateCheck:
    manifest = fetch_manifest(url, timeout_s=timeout_s)
    if manifest.channel != channel:
        raise ValueError(
            f"Update feed returned channel {manifest.channel!r}; application requested {channel!r}"
        )
    below = bool(
        manifest.minimum_supported_version
        and parse_version(current_version) < parse_version(manifest.minimum_supported_version)
    )
    return UpdateCheck(current_version, manifest, manifest.is_newer_than(current_version), below)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_update(manifest: UpdateManifest, target_dir: str | Path | None = None) -> Path:
    target_root = Path(target_dir) if target_dir is not None else Path(tempfile.mkdtemp(prefix="nhra-tech-update-"))
    target_root.mkdir(parents=True, exist_ok=True)
    filename = Path(manifest.installer_url.split("?", 1)[0]).name or f"NHRA-Velocity-{manifest.version}-Setup.exe"
    target = target_root / filename
    req = Request(manifest.installer_url, headers={"User-Agent": f"NHRA-Velocity/{__version__}"})
    with urlopen(req, timeout=60.0) as response, target.open("wb") as out:  # noqa: S310
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
    if target.stat().st_size != manifest.size_bytes:
        target.unlink(missing_ok=True)
        raise ValueError("Downloaded update size does not match signed release manifest")
    actual = sha256_file(target)
    if actual.lower() != manifest.sha256.lower():
        target.unlink(missing_ok=True)
        raise ValueError("Downloaded update SHA-256 does not match release manifest")
    if manifest.require_authenticode:
        verify_windows_authenticode(target, expected_subject=manifest.authenticode_subject or None)
    return target


def verify_windows_authenticode(path: str | Path, *, expected_subject: str | None = None) -> str:
    """Require a valid Windows Authenticode signature and optionally publisher text."""
    if os.name != "nt":
        raise RuntimeError("Authenticode verification is only available on Windows")
    escaped = str(Path(path)).replace("'", "''")
    script = (
        f"$s=Get-AuthenticodeSignature -LiteralPath '{escaped}'; "
        "$subject=if($s.SignerCertificate){$s.SignerCertificate.Subject}else{''}; "
        "Write-Output ($s.Status.ToString() + '|' + $subject)"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    status, _, subject = result.stdout.strip().partition("|")
    if result.returncode != 0 or status != "Valid":
        raise ValueError(f"Update installer Authenticode signature is not valid ({status or result.stderr.strip()})")
    if expected_subject and expected_subject.lower() not in subject.lower():
        raise ValueError(f"Update installer signer {subject!r} does not match expected publisher")
    return subject


def launch_installer(path: str | Path) -> None:
    """Launch a verified platform installer.

    Windows is production-enabled today. macOS intentionally remains fail-closed
    until the Developer ID/notarized distribution handoff described in
    ``MACOS_PLAN.md`` is implemented.
    """
    support = current_platform_support()
    if not support.automatic_installer_launch:
        raise RuntimeError(
            f"NHRA Velocity automatic update installation is not yet enabled on {support.display_name}. "
            "Use the approved platform package; macOS production updates remain gated on signing/notarization."
        )
    subprocess.Popen([str(Path(path))], close_fds=True)  # noqa: S603
