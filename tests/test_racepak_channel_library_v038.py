from __future__ import annotations

from pathlib import Path
import numpy as np

from runlab.importers import load_telemetry
from runlab.racepak_channel_library import (
    build_channel_id_census,
    install_census,
    lookup_channel_evidence,
    lookup_exact_descriptor_profile,
    lookup_verified_channel,
)


def _lp(text: str) -> bytes:
    raw = text.encode("latin1"); assert len(raw) < 256
    return bytes([len(raw)]) + raw


def _channel(cid: int, name: str, unit: str = "RPM", rate: int = 100) -> bytes:
    desc = f'ScaledBuffer: (0=>0,1=>1) [(0,12000),%-5.0lf,{unit}] _CONNECT4_COMMAND="{cid}"'
    return b"\x43\x09\x02\x00" + _lp("RPM") + _lp(name) + _lp(desc) + _lp("0.0") + _lp(f"Timer_{rate}sps") + b"\x00" * 12


def _config(cid: int = 2, name: str = "ENGINE RPM", unit: str = "RPM", rate: int = 2) -> bytes:
    return b"\x00" * 64 + _channel(cid, name, unit, rate) + b"\x00" * 32


def _descriptor(flag: int, channel_id: int, rate: int, config_rate: int) -> bytes:
    return bytes([0x33, flag]) + int(channel_id).to_bytes(4, "little") + int(rate).to_bytes(4, "little") + int(config_rate).to_bytes(4, "little") + b"\x00" * 8


def _ddf(cid: int = 2, rate: int = 2, *, flag: int = 0x00) -> bytes:
    header = bytearray(14); header[12:14] = (1).to_bytes(2, "little")
    values = np.arange(rate * 2, dtype="<i2") + 1000
    return bytes(header) + _descriptor(flag, cid, rate, rate) + values.tobytes()


def test_channel_id_history_counts_distinct_configs_but_is_never_automatic(tmp_path: Path):
    # Three genuinely distinct configs agree on channel 2. One appears twice,
    # but repeated files may not manufacture extra evidence -- and even strong
    # ID history remains suggestion-only.
    for i, extra in enumerate((101, 102, 103)):
        blob = _config(2, "ENGINE RPM") + _channel(extra, f"OTHER {extra}", "PSI", 10)
        (tmp_path / f"cfg{i}.rcg").write_bytes(blob)
    (tmp_path / "duplicate.rcg").write_bytes((tmp_path / "cfg0.rcg").read_bytes())

    payload = build_channel_id_census([tmp_path], rpk_mode="none")
    row = next(x for x in payload["channels"] if x["channel_id"] == 2)
    assert row["distinct_configurations"] == 3
    assert row["file_occurrences"] == 4
    assert row["evidence_level"] == "consistent-3plus"
    assert row["suggestion_only"] is True
    assert row["automatic_naming_allowed"] is False
    assert row["suggested_name"] == "ENGINE RPM"


def test_conflicting_global_id_is_retained_as_conflict_evidence(tmp_path: Path):
    (tmp_path / "a.rcg").write_bytes(_config(2, "ENGINE RPM"))
    (tmp_path / "b.rcg").write_bytes(_config(2, "DRIVE SHAFT"))
    (tmp_path / "c.rcg").write_bytes(_config(2, "ENGINE RPM"))
    payload = build_channel_id_census([tmp_path], rpk_mode="none")
    row = next(x for x in payload["channels"] if x["channel_id"] == 2)
    assert row["evidence_level"] == "conflict"
    assert row["automatic_naming_allowed"] is False
    assert set(row["distinct_names"]) == {"drive shaft", "engine rpm"}


def test_id_only_evidence_never_renames_configless_ddf(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NHRA_VELOCITY_HOME", str(tmp_path / "home"))
    defs = tmp_path / "defs"; defs.mkdir()
    for i, extra in enumerate((201, 202, 203)):
        (defs / f"cfg{i}.rcg").write_bytes(_config(2, "ENGINE RPM") + _channel(extra, f"EXTRA {extra}", "PSI", 10))
    payload = build_channel_id_census([defs], rpk_mode="none")
    install_census(payload)

    evidence = lookup_channel_evidence(2)
    assert evidence["suggested_name"] == "ENGINE RPM"
    assert evidence["automatic_naming_allowed"] is False
    # Compatibility API from dev.22 must fail closed.
    assert lookup_verified_channel(2) == {}

    p = tmp_path / "orphan.ddf"; p.write_bytes(_ddf(2, 2))
    run = load_telemetry(p)
    source = "RacePak Channel 2"
    assert source in run.native_channels
    assert run.native_channels[source].unit == ""
    assert run.native_channels[source].metadata["racepak_definition_source"] == "channel_id_evidence_only"
    assert run.native_channels[source].metadata["racepak_id_evidence_suggested_name"] == "ENGINE RPM"
    assert run.native_channels[source].metadata["racepak_id_evidence_automatic_naming_allowed"] is False
    assert set(run.channel_map) == {"time_s"}
    assert run.metadata["ddf_definition_authority"] == "channel_id_evidence_only"


def test_exact_known_ddf_descriptor_fingerprint_can_recover_source_names(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NHRA_VELOCITY_HOME", str(tmp_path / "home"))
    known = tmp_path / "known"; known.mkdir()
    ddf_bytes = _ddf(2, 2)
    (known / "known.ddf").write_bytes(ddf_bytes)
    (known / "known.rcg").write_bytes(_config(2, "ENGINE RPM", "RPM", 2))

    payload = build_channel_id_census([tmp_path], rpk_mode="none")
    assert payload["summary"]["safe_exact_descriptor_profiles"] == 1
    install_census(payload)
    profile = payload["descriptor_profiles"][0]
    assert lookup_exact_descriptor_profile(profile["descriptor_signature_sha256"])

    # Same exact descriptor table, no sibling config at the new location.
    orphan_dir = tmp_path / "orphan"; orphan_dir.mkdir()
    p = orphan_dir / "orphan.ddf"; p.write_bytes(ddf_bytes)
    run = load_telemetry(p)
    assert "ENGINE RPM" in run.native_channels
    assert run.units["ENGINE RPM"] == "rpm"
    assert run.native_channels["ENGINE RPM"].metadata["racepak_definition_source"] == "exact_corpus_descriptor_fingerprint"
    # Source-name recovery still cannot decide the engineering Common Channel.
    assert set(run.channel_map) == {"time_s"}
    assert run.metadata["ddf_definition_authority"] == "exact_corpus_descriptor_fingerprint"


def test_same_channel_id_with_different_descriptor_fingerprint_stays_generic(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NHRA_VELOCITY_HOME", str(tmp_path / "home"))
    known = tmp_path / "known"; known.mkdir()
    (known / "known.ddf").write_bytes(_ddf(2, 2))
    (known / "known.rcg").write_bytes(_config(2, "OIL PRESSURE", "PSI", 2))
    payload = build_channel_id_census([tmp_path], rpk_mode="none")
    install_census(payload)

    # The id is identical but rate changes, therefore the complete descriptor
    # fingerprint differs. Corpus history may be shown as evidence, never used
    # to rename or assign a unit.
    orphan_dir = tmp_path / "other"; orphan_dir.mkdir()
    p = orphan_dir / "different.ddf"; p.write_bytes(_ddf(2, 4))
    run = load_telemetry(p)
    source = "RacePak Channel 2"
    assert source in run.native_channels
    assert run.native_channels[source].unit == ""
    assert run.native_channels[source].metadata["racepak_id_evidence_suggested_name"] == "OIL PRESSURE"
    assert run.metadata["ddf_corpus_exact_descriptor_bound_channels"] == 0


def test_conflict_on_same_exact_descriptor_fingerprint_disables_recovery(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NHRA_VELOCITY_HOME", str(tmp_path / "home"))
    ddf_bytes = _ddf(2, 2)
    a = tmp_path / "a"; a.mkdir(); (a / "run.ddf").write_bytes(ddf_bytes); (a / "a.rcg").write_bytes(_config(2, "ENGINE RPM", "RPM", 2))
    b = tmp_path / "b"; b.mkdir(); (b / "run.ddf").write_bytes(ddf_bytes); (b / "b.rcg").write_bytes(_config(2, "OIL PRESSURE", "PSI", 2))

    payload = build_channel_id_census([tmp_path], rpk_mode="none")
    profile = payload["descriptor_profiles"][0]
    assert profile["confidence"] == "exact-descriptor-conflict"
    assert profile["safe_for_exact_descriptor_recovery"] is False
    install_census(payload)

    c = tmp_path / "c"; c.mkdir(); p = c / "run.ddf"; p.write_bytes(ddf_bytes)
    run = load_telemetry(p)
    assert "RacePak Channel 2" in run.native_channels
    assert run.metadata["ddf_corpus_exact_descriptor_bound_channels"] == 0
