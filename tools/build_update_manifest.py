from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    p = argparse.ArgumentParser(description="Create NHRA Tech Data update.json for a release installer")
    p.add_argument("installer")
    p.add_argument("--version", required=True)
    p.add_argument("--channel", choices=("stable", "beta", "development"), default="stable")
    p.add_argument("--installer-url", required=True)
    p.add_argument("--source-commit", default="")
    p.add_argument("--release-notes-url", default="")
    p.add_argument("--minimum-supported-version", default="")
    p.add_argument("--mandatory", action="store_true")
    p.add_argument("--require-authenticode", action="store_true")
    p.add_argument("--authenticode-subject", default="")
    p.add_argument("--output", default="update.json")
    args = p.parse_args()
    installer = Path(args.installer)
    payload = {
        "schema": 1,
        "product": "NHRA Tech Data",
        "version": args.version,
        "channel": args.channel,
        "installer_url": args.installer_url,
        "sha256": sha256_file(installer),
        "size_bytes": installer.stat().st_size,
        "source_commit": args.source_commit,
        "release_notes_url": args.release_notes_url,
        "minimum_supported_version": args.minimum_supported_version,
        "mandatory": bool(args.mandatory),
        "require_authenticode": bool(args.require_authenticode),
        "authenticode_subject": args.authenticode_subject,
    }
    Path(args.output).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
