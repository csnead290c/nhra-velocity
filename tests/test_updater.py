from pathlib import Path
import hashlib
import json
import pytest

from runlab.updater import UpdateManifest, parse_version, sha256_file


def _manifest(**overrides):
    raw = {
        'schema': 1,
        'product': 'NHRA Tech Data',
        'version': '0.38.0',
        'channel': 'stable',
        'installer_url': 'https://example.com/NHRA-Tech-Data-Setup.exe',
        'sha256': 'a' * 64,
        'size_bytes': 123,
    }
    raw.update(overrides)
    return UpdateManifest.from_dict(raw)


def test_semver_prerelease_ordering():
    assert parse_version('0.38.0-dev.1') < parse_version('0.38.0-beta.1')
    assert parse_version('0.38.0-beta.9') < parse_version('0.38.0-rc.1')
    assert parse_version('0.38.0-rc.2') < parse_version('0.38.0')
    assert parse_version('0.38.0') < parse_version('0.39.0-dev.1')


def test_manifest_validates_and_detects_newer_version():
    m = _manifest()
    assert m.is_newer_than('0.37.1')
    assert not m.is_newer_than('0.38.0')


def test_manifest_rejects_non_https_and_invalid_hash():
    with pytest.raises(ValueError, match='HTTPS'):
        _manifest(installer_url='http://example.com/file.exe')
    with pytest.raises(ValueError, match='SHA-256'):
        _manifest(sha256='nope')


def test_sha256_file(tmp_path: Path):
    p = tmp_path / 'x.bin'
    p.write_bytes(b'NHRA Tech Data')
    assert sha256_file(p) == hashlib.sha256(b'NHRA Tech Data').hexdigest()
