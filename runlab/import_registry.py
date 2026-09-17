from __future__ import annotations

"""Declarative telemetry import registry.

The registry separates three questions that used to be mixed together inside
``load_telemetry``:

1. Is this file family recognized?
2. Is a decoder/bridge available in this build?
3. Has that path actually been qualified well enough to advertise as direct?

Recognition is deliberately broader than decoding. Proprietary/unknown binary
files fail closed with a useful next-step message instead of falling through to
pandas text parsing.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


@dataclass(frozen=True)
class ImportFormatSpec:
    key: str
    label: str
    extensions: tuple[str, ...]
    status: str  # direct | bridge | pending | container | interchange | support
    decoder_key: str = ""
    binary: bool = False
    message: str = ""

    def matches(self, path: str | Path) -> bool:
        p = Path(path)
        name = p.name.lower()
        return any(name.endswith(ext) for ext in self.extensions)


FORMAT_SPECS: tuple[ImportFormatSpec, ...] = (
    ImportFormatSpec("racepak", "RacePak / DataLink", (".rpk", ".rpk.bin"), "direct", "RacePak", True),
    ImportFormatSpec("racepak_ddf", "RacePak raw logger DDF", (".ddf",), "direct", "RacePak DDF", True,
        "Raw RacePak DDF decoding is supported directly. A matching RCG/RPK configuration is optional for channel names/units; without one, stable channel-id labels are used and canonical roles are not guessed."),
    ImportFormatSpec(
        "racepak_config", "RacePak logger configuration", (".rcg",), "support", "RacePak configuration", True,
        "RacePak .rcg files are logger/channel configuration assets rather than run recordings. They may be used to enrich matching DDF logs."
    ),
    ImportFormatSpec("motec", "MoTeC i2 / M1", (".ld", ".ld.bin"), "direct", "MoTeC", True),
    ImportFormatSpec(
        "motec_ldx", "MoTeC LD metadata sidecar", (".ldx",), "support", "MoTeC LDX", True,
        "MoTeC .ldx files are companion metadata/index files for the corresponding .ld recording, not the primary data log. "
        "Open the matching .ld file; VELOCITY can retain the .ldx as a support asset."
    ),
    ImportFormatSpec("maxxecu", "MaxxECU", (".maxxecu-log", ".maxxlog", ".maxxecu-zip-log"), "direct", "MaxxECU"),
    ImportFormatSpec("vbox_vbo", "Racelogic VBOX VBO", (".vbo",), "interchange", "VBOX"),
    ImportFormatSpec("tunerstudio", "EFI Analytics TunerStudio / MegaSquirt", (".msl", ".mlg"), "interchange", "TunerStudio"),
    ImportFormatSpec("excel", "Excel telemetry table", (".xlsx", ".xlsm"), "interchange", "Excel"),
    ImportFormatSpec("archive", "Telemetry archive", (".zip",), "container", "Archive", True),
    ImportFormatSpec("delimited", "Delimited telemetry", (".csv", ".tsv", ".txt", ".log"), "interchange", "Delimited"),

    ImportFormatSpec(
        "fueltech", "FuelTech Vision / PowerFT data log", (".ftlog", ".ftml"), "pending", "FuelTech", True,
        "Native FuelTech FTLOG/FTML decoding is not qualified in this build. "
        "FuelTech CSV exports and MoTeC i2 .ld exports are supported."
    ),
    ImportFormatSpec(
        "fueltech_map", "FuelTech FTManager map / calibration", (".ftm",), "support", "FuelTech map", True,
        "FuelTech .ftm files are ECU map/calibration files rather than data logs. "
        "They are retained as recognized support assets and are not sent to a data-log decoder."
    ),
    ImportFormatSpec(
        "asam_mdf", "ASAM MDF3/MDF4", (".mf4", ".mdf"), "bridge", "ASAM MDF", True,
        "ASAM MDF is recognized and the adapter boundary is reserved, but a packaged/qualified MDF decoder is not present in this build."
    ),
    ImportFormatSpec(
        "aim", "AiM RaceStudio", (".xrk", ".xrz", ".drk"), "bridge", "AiM", True,
        "AiM RaceStudio native files are recognized. The intended Windows path is the official AiM data-access DLL behind an isolated adapter; no vendor binary is bundled here."
    ),
    ImportFormatSpec("holley", "Holley EFI V6", (".dl", ".dlz"), "direct", "Holley", True,
        "Native Holley V6 DL/DLZ import is qualified against paired NHRA Pro Stock Holley/RacePak data. V5 sparse and V3/other families remain fail-closed."),
    ImportFormatSpec(
        "holley_config", "Holley EFI configuration", (".hefi",), "support", "Holley configuration", True,
        "Holley .hefi files are ECU configuration files rather than data logs. "
        "They are retained as recognized support assets and are not sent to a data-log decoder."
    ),
    ImportFormatSpec("bigstuff_tune", "BigStuff / BigComm calibration", (".bigtune", ".big"), "support", "BigStuff", True,
        "BigStuff .bigTune/.big files are recognized as calibration/support files, not assumed to be telemetry logs. A native BigStuff data-log format must be identified and qualified separately."),
    ImportFormatSpec("hptuners", "HP Tuners VCM Scanner", (".hpl",), "pending", "HP Tuners", True, "HP Tuners HPL is recognized, but a version-qualified VCM Scanner decoder is not yet available."),
    ImportFormatSpec("vbox_vbb", "Racelogic VBOX VBB", (".vbb",), "pending", "VBOX VBB", True, "VBOX VBB is recognized; the newer binary decoder is not yet qualified. Text VBO files are supported directly."),
    ImportFormatSpec(
        "daq_binary", "DAQ binary (MSD Power Grid / AEM)", (".daq",), "pending", "DAQ binary", True,
        "The .daq extension is shared by more than one logger family. The current NHRA Race Data corpus contains MSD 7730 Power Grid DAQ files; "
        "a signature-qualified Power Grid/AEM decoder is not yet available, so these files intentionally fail closed."
    ),
    ImportFormatSpec(
        "msd_power_grid_dqi", "MSD Power Grid ReView data log", (".dqi",), "pending", "MSD Power Grid", True,
        "MSD Power Grid .dqi ReView logs are recognized, but a native decoder is not yet qualified."
    ),
    ImportFormatSpec(
        "msd_power_grid_config", "MSD Power Grid configuration", (".mff",), "support", "MSD Power Grid configuration", True,
        "MSD Power Grid .mff files are controller configuration/tune files rather than data logs and are kept as support assets."
    ),
    ImportFormatSpec("aem", "AEM", (".itlog",), "pending", "AEM", True, "AEM Infinity ITLOG files are recognized, but a decoder is not yet qualified."),
    ImportFormatSpec("ecumaster", "ECUMaster", (".emublog3",), "pending", "ECUMaster", True, "ECUMaster EMU Black V3 logs are recognized, but a native decoder is not yet qualified."),
    ImportFormatSpec("emtron", "Emtron EmVision", (".elf", ".elo"), "pending", "Emtron", True, "Emtron EmVision log files are recognized, but a native decoder is not yet qualified."),
    ImportFormatSpec("cosworth_pi", "Cosworth / Pi", (".pds",), "pending", "Cosworth/Pi", True, "Cosworth/Pi logged-data files are recognized, but a native decoder/bridge is not yet qualified."),
    ImportFormatSpec("iracing", "iRacing telemetry", (".ibt",), "pending", "iRacing", True, "iRacing IBT is recognized, but a native decoder is not yet qualified."),
    ImportFormatSpec("syvecs", "Syvecs SView", (".sd",), "pending", "Syvecs", True, "Syvecs SView native logs are recognized, but a native decoder is not yet qualified. CSV interchange remains supported."),
    ImportFormatSpec("megasquirt_frd", "MegaSquirt raw logger", (".frd",), "pending", "MegaSquirt FRD", True, "MegaSquirt FRD requires the matching ECU/firmware definition and is not guessed without it."),
    ImportFormatSpec("can_capture", "CAN/network capture", (".asc", ".blf", ".pcap", ".pcapng"), "pending", "CAN capture", True, "Raw CAN/network capture is recognized. A future adapter will preserve raw frames and optionally decode them with DBC/A2L definitions."),
    ImportFormatSpec("legacy_sheet", "Legacy spreadsheet", (".xls", ".ods"), "pending", "Legacy spreadsheet", True, "Legacy XLS/ODS telemetry tables are recognized. Save/export as XLSX or CSV until an optional legacy reader is packaged."),
)


OPENABLE_STATUSES = frozenset({"direct", "interchange", "container"})


def _glob_patterns(specs: Iterable[ImportFormatSpec]) -> tuple[str, ...]:
    """Return stable Qt file-dialog wildcard patterns for registry specs.

    The registry is the authority for file recognition. Keeping dialog patterns
    derived from it prevents a decoder from being added without making its file
    type selectable in the desktop UI (the historical MaxxECU-Zip-log bug).
    """
    patterns: set[str] = set()
    for spec in specs:
        for ext in spec.extensions:
            clean = str(ext).strip()
            if not clean:
                continue
            patterns.add(f"*{clean}")
    return tuple(sorted(patterns, key=lambda value: (value.lower(), value)))


def openable_specs() -> tuple[ImportFormatSpec, ...]:
    """Formats that this build can currently decode/import directly."""
    return tuple(spec for spec in FORMAT_SPECS if spec.status in OPENABLE_STATUSES)


def recognized_unavailable_specs() -> tuple[ImportFormatSpec, ...]:
    """Recognized data-log formats that intentionally fail closed in this build."""
    return tuple(
        spec for spec in FORMAT_SPECS
        if spec.status not in OPENABLE_STATUSES and spec.status != "support"
    )


def support_specs() -> tuple[ImportFormatSpec, ...]:
    """Recognized calibration/configuration assets that are not data logs."""
    return tuple(spec for spec in FORMAT_SPECS if spec.status == "support")


def qt_file_dialog_filter(*, include_recognized_unavailable: bool = True, include_support: bool = True) -> str:
    """Build the desktop data-log picker filter from ``FORMAT_SPECS``.

    Qt expects groups separated by ``;;`` and wildcards inside parentheses.
    Openable formats are listed first. Recognized-but-unavailable families get
    their own explicitly labelled group so users can select them and receive the
    registry's fail-closed diagnostic instead of having to switch to All files.
    """
    groups: list[str] = []

    openable = openable_specs()
    openable_patterns = _glob_patterns(openable)
    groups.append(f"Openable data logs ({' '.join(openable_patterns)})")

    preferred_groups: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("RacePak", ("racepak", "racepak_ddf")),
        ("MoTeC", ("motec",)),
        ("MaxxECU", ("maxxecu",)),
        ("Holley EFI", ("holley",)),
        ("VBOX", ("vbox_vbo",)),
        ("TunerStudio / MegaSquirt", ("tunerstudio",)),
        ("Tables / interchange", ("excel", "delimited")),
        ("Archives", ("archive",)),
    )
    for label, keys in preferred_groups:
        specs = tuple(_BY_KEY[key] for key in keys if key in _BY_KEY and _BY_KEY[key].status in OPENABLE_STATUSES)
        patterns = _glob_patterns(specs)
        if patterns:
            groups.append(f"{label} ({' '.join(patterns)})")

    if include_recognized_unavailable:
        recognized_patterns = _glob_patterns(recognized_unavailable_specs())
        if recognized_patterns:
            groups.append(
                "Recognized data logs - decoder pending "
                f"({' '.join(recognized_patterns)})"
            )

    if include_support:
        support_patterns = _glob_patterns(support_specs())
        if support_patterns:
            groups.append(
                "Calibration / support files - not data logs "
                f"({' '.join(support_patterns)})"
            )

    groups.append("All files (*.*)")
    return ";;".join(groups)


_BY_KEY = {spec.key: spec for spec in FORMAT_SPECS}


def format_spec(key: str) -> ImportFormatSpec:
    return _BY_KEY[str(key)]


def spec_for_path(path: str | Path) -> Optional[ImportFormatSpec]:
    p = Path(path)
    # longest suffix first so .rpk.bin beats a generic .bin fallback
    matches = [spec for spec in FORMAT_SPECS if spec.matches(p)]
    if not matches:
        return None
    return max(matches, key=lambda spec: max(len(ext) for ext in spec.extensions))


def recognized_extensions() -> tuple[str, ...]:
    return tuple(sorted({ext for spec in FORMAT_SPECS for ext in spec.extensions}))


def telemetry_candidate(path: str | Path) -> bool:
    p = Path(path)
    spec = spec_for_path(p)
    if spec is not None:
        return spec.status != "support"
    name = p.name.lower()
    return p.suffix.lower() == ".bin" and any(token in name for token in (".rpk.", ".ld.", "racepak", "motec"))


def pending_message(spec: ImportFormatSpec) -> str:
    detail = spec.message or f"{spec.label} is recognized, but this build does not have a qualified decoder."
    return (
        f"{detail} The file was intentionally not sent to a generic text parser. "
        "Recognition does not imply native qualification."
    )


def registry_rows() -> list[dict[str, object]]:
    return [
        {
            "key": spec.key,
            "label": spec.label,
            "extensions": list(spec.extensions),
            "status": spec.status,
            "decoder_key": spec.decoder_key,
            "binary": spec.binary,
        }
        for spec in FORMAT_SPECS
    ]
