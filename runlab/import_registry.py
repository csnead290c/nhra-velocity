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
    status: str  # direct | bridge | pending | container | interchange
    decoder_key: str = ""
    binary: bool = False
    message: str = ""

    def matches(self, path: str | Path) -> bool:
        p = Path(path)
        name = p.name.lower()
        return any(name.endswith(ext) for ext in self.extensions)


FORMAT_SPECS: tuple[ImportFormatSpec, ...] = (
    ImportFormatSpec("racepak", "RacePak / DataLink", (".rpk", ".rpk.bin"), "direct", "RacePak", True),
    ImportFormatSpec("motec", "MoTeC i2 / M1", (".ld", ".ld.bin"), "direct", "MoTeC", True),
    ImportFormatSpec("maxxecu", "MaxxECU", (".maxxecu-log", ".maxxlog", ".maxxecu-zip-log"), "direct", "MaxxECU"),
    ImportFormatSpec("vbox_vbo", "Racelogic VBOX VBO", (".vbo",), "interchange", "VBOX"),
    ImportFormatSpec("tunerstudio", "EFI Analytics TunerStudio / MegaSquirt", (".msl", ".mlg"), "interchange", "TunerStudio"),
    ImportFormatSpec("excel", "Excel telemetry table", (".xlsx", ".xlsm"), "interchange", "Excel"),
    ImportFormatSpec("archive", "Telemetry archive", (".zip",), "container", "Archive", True),
    ImportFormatSpec("delimited", "Delimited telemetry", (".csv", ".tsv", ".txt", ".log"), "interchange", "Delimited"),

    ImportFormatSpec(
        "fueltech", "FuelTech Vision / PowerFT", (".ftlog", ".ftml"), "pending", "FuelTech", True,
        "Native FuelTech FTLOG/FTML decoding is not qualified in this build. "
        "FuelTech CSV exports and MoTeC i2 .ld exports are supported."
    ),
    ImportFormatSpec(
        "asam_mdf", "ASAM MDF3/MDF4", (".mf4", ".mdf"), "bridge", "ASAM MDF", True,
        "ASAM MDF is recognized and the adapter boundary is reserved, but a packaged/qualified MDF decoder is not present in this build."
    ),
    ImportFormatSpec(
        "aim", "AiM RaceStudio", (".xrk", ".xrz", ".drk"), "bridge", "AiM", True,
        "AiM RaceStudio native files are recognized. The intended Windows path is the official AiM data-access DLL behind an isolated adapter; no vendor binary is bundled here."
    ),
    ImportFormatSpec("holley", "Holley EFI", (".dl", ".dlz"), "pending", "Holley", True,
        "Holley DL/DLZ is recognized. NHRA Tech Data has identified a multi-generation NHRA qualification corpus (including Pro Stock), but native decoding is not yet qualified in this build."),
    ImportFormatSpec("bigstuff_tune", "BigStuff / BigComm calibration", (".bigtune", ".big"), "pending", "BigStuff", True,
        "BigStuff .bigTune/.big files are recognized as calibration/support files, not assumed to be telemetry logs. A native BigStuff data-log format must be identified and qualified separately."),
    ImportFormatSpec("hptuners", "HP Tuners VCM Scanner", (".hpl",), "pending", "HP Tuners", True, "HP Tuners HPL is recognized, but a version-qualified VCM Scanner decoder is not yet available."),
    ImportFormatSpec("vbox_vbb", "Racelogic VBOX VBB", (".vbb",), "pending", "VBOX VBB", True, "VBOX VBB is recognized; the newer binary decoder is not yet qualified. Text VBO files are supported directly."),
    ImportFormatSpec("aem", "AEM", (".daq", ".itlog"), "pending", "AEM", True, "AEM AQ-1/Infinity native files are recognized, but a decoder is not yet qualified."),
    ImportFormatSpec("ecumaster", "ECUMaster", (".emublog3",), "pending", "ECUMaster", True, "ECUMaster EMU Black V3 logs are recognized, but a native decoder is not yet qualified."),
    ImportFormatSpec("emtron", "Emtron EmVision", (".elf", ".elo"), "pending", "Emtron", True, "Emtron EmVision log files are recognized, but a native decoder is not yet qualified."),
    ImportFormatSpec("cosworth_pi", "Cosworth / Pi", (".pds",), "pending", "Cosworth/Pi", True, "Cosworth/Pi logged-data files are recognized, but a native decoder/bridge is not yet qualified."),
    ImportFormatSpec("iracing", "iRacing telemetry", (".ibt",), "pending", "iRacing", True, "iRacing IBT is recognized, but a native decoder is not yet qualified."),
    ImportFormatSpec("syvecs", "Syvecs SView", (".sd",), "pending", "Syvecs", True, "Syvecs SView native logs are recognized, but a native decoder is not yet qualified. CSV interchange remains supported."),
    ImportFormatSpec("megasquirt_frd", "MegaSquirt raw logger", (".frd",), "pending", "MegaSquirt FRD", True, "MegaSquirt FRD requires the matching ECU/firmware definition and is not guessed without it."),
    ImportFormatSpec("can_capture", "CAN/network capture", (".asc", ".blf", ".pcap", ".pcapng"), "pending", "CAN capture", True, "Raw CAN/network capture is recognized. A future adapter will preserve raw frames and optionally decode them with DBC/A2L definitions."),
    ImportFormatSpec("legacy_sheet", "Legacy spreadsheet", (".xls", ".ods"), "pending", "Legacy spreadsheet", True, "Legacy XLS/ODS telemetry tables are recognized. Save/export as XLSX or CSV until an optional legacy reader is packaged."),
)


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
    if spec_for_path(p) is not None:
        return True
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
