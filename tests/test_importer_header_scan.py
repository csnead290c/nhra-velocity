from __future__ import annotations

import re
from pathlib import Path

import pytest

import runlab.importers as imp

ROOT = Path(__file__).resolve().parents[1]


def _legacy_find_header_line(lines, delimiter: str) -> int:
    """Reference copy of the pre-optimization header scan.

    Kept here so the optimized implementation can be checked for exact
    output equivalence instead of only 'still parses something'.
    """
    best_idx, best_score = 0, -1.0
    for i, line in enumerate(lines[:80]):
        parts = [p.strip().strip('"') for p in line.split(delimiter)]
        if len(parts) < 2:
            continue
        alpha = sum(bool(re.search(r"[A-Za-z]", p)) for p in parts)
        numeric = sum(imp._is_number(p) for p in parts)
        known = sum(
            any(
                imp._norm(s) in imp._norm(p)
                for vals in imp.CANONICAL_CHANNELS.values()
                for s in vals
            )
            for p in parts
        )
        next_numeric = 0
        if i + 1 < len(lines):
            nxt = [p.strip().strip('"') for p in lines[i + 1].split(delimiter)]
            next_numeric = sum(imp._is_number(p) for p in nxt)
        score = alpha * 2.0 + known * 6.0 + next_numeric * 0.5 - numeric
        if score > best_score:
            best_idx, best_score = i, score
    return best_idx


def _cases():
    yield ["a\tb\tc", "1\t2\t3"], "\t"
    yield [
        "# logger comment line",
        "",
        "Time [s]\tEngine RPM [rpm]\tTPS [%]",
        "0.0\t3000\t15",
        "0.01\t3001\t16",
    ], "\t"
    yield [
        "Session metadata, ignored preamble",
        "notes, more preamble text",
        "time,rpm,speed,throttle",
        "0,2800,0,22",
        "1,2900,10,24",
    ], ","
    yield (ROOT / "examples" / "native_demo_maxxecu.MaxxECU-log").read_text(
        encoding="utf-8", errors="replace"
    ).splitlines(), "\t"


def test_header_scan_result_identical_to_legacy_scan():
    for lines, delimiter in _cases():
        assert imp._find_header_line(lines, delimiter) == _legacy_find_header_line(lines, delimiter)


def test_header_scan_norm_calls_bounded(monkeypatch):
    """The quadratic path re-normalized every canonical synonym for every
    cell of every scanned line.  Bound total _norm calls so that cost cannot
    silently return without depending on wall-clock timing in CI."""
    lines = (
        ROOT / "examples" / "native_demo_maxxecu.MaxxECU-log"
    ).read_text(encoding="utf-8", errors="replace").splitlines()
    calls = 0
    original = imp._norm

    def counting(text):
        nonlocal calls
        calls += 1
        return original(text)

    monkeypatch.setattr(imp, "_norm", counting)
    imp._find_header_line(lines, "\t")
    assert calls < 5000


def test_maxxecu_demo_decode_output_equivalence():
    run = imp.load_telemetry(str(ROOT / "examples" / "native_demo_maxxecu.MaxxECU-log"))
    assert list(run.data.columns)[:5] == [
        "Time [s]", "Engine RPM [rpm]", "Vehicle Speed [km/h]", "Throttle [%]", "Boost [psi]",
    ]
    assert len(run.data) == 250
    assert run.channel_map["engine_rpm"] == "__engine_rpm"
    assert run.channel_map["speed_mph"] == "__speed_mph"
    first = run.data.iloc[0].tolist()
    last = run.data.iloc[-1].tolist()
    assert first[:5] == [0.0, 2800.0, 0.0, 22.0, 0.0]
    assert last[:5] == [4.98, 8200.0, 208.166, 100.0, 22.0]
    assert run.units["Engine RPM [rpm]"] == "rpm"
    assert run.units["Boost [psi]"] == "psi"
