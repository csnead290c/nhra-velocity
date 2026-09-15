from __future__ import annotations

"""Content-addressed local evidence storage.

The managed object store is an expendable local cache for immutable source bytes.
Production Run Assets remain authoritative on NHRA Tech Services; cached objects
are named and verified by SHA-256 rather than user filename.
"""

from dataclasses import dataclass
from pathlib import Path
import hashlib
import os
import shutil
from typing import BinaryIO

from .diagnostics import app_data_root


@dataclass(frozen=True)
class StoredObject:
    sha256: str
    path: Path
    size_bytes: int
    existed: bool


def sha256_file(path: str | os.PathLike[str], chunk_size: int = 4 * 1024 * 1024) -> tuple[str, int]:
    h = hashlib.sha256(); size = 0
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            h.update(chunk); size += len(chunk)
    return h.hexdigest(), size


class LocalObjectStore:
    def __init__(self, root: str | os.PathLike[str] | None = None):
        self.root = Path(root) if root is not None else app_data_root() / "library" / "objects"
        self.root.mkdir(parents=True, exist_ok=True)

    def object_path(self, sha256: str) -> Path:
        token = str(sha256).lower()
        return self.root / token[:2] / token[2:4] / token

    def ingest(self, path: str | os.PathLike[str]) -> StoredObject:
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        digest, size = sha256_file(source)
        target = self.object_path(digest)
        existed = target.exists()
        if not existed:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".partial")
            try:
                shutil.copy2(source, tmp)
                check, copied_size = sha256_file(tmp)
                if check != digest or copied_size != size:
                    raise IOError("Managed evidence copy failed hash verification")
                os.replace(tmp, target)
            finally:
                tmp.unlink(missing_ok=True)
        return StoredObject(digest, target, size, existed)

    def verify(self, sha256: str) -> bool:
        path = self.object_path(sha256)
        if not path.is_file():
            return False
        actual, _ = sha256_file(path)
        return actual.lower() == str(sha256).lower()
    def ingest_bytes(self, content: bytes, *, expected_sha256: str = "") -> StoredObject:
        """Store immutable bytes in the local cache and verify the authoritative hash when supplied."""
        data=bytes(content)
        digest=hashlib.sha256(data).hexdigest()
        if expected_sha256 and digest.lower()!=str(expected_sha256).lower():
            raise IOError(f"Downloaded asset SHA-256 mismatch: expected {expected_sha256}, got {digest}")
        target=self.object_path(digest)
        existed=target.exists()
        if not existed:
            target.parent.mkdir(parents=True,exist_ok=True)
            tmp=target.with_suffix('.partial')
            try:
                tmp.write_bytes(data)
                check,size=sha256_file(tmp)
                if check!=digest or size!=len(data):
                    raise IOError('Managed asset write failed hash verification')
                os.replace(tmp,target)
            finally:
                tmp.unlink(missing_ok=True)
        return StoredObject(digest,target,len(data),existed)

