from __future__ import annotations

"""Small deterministic diagnostic checks for a field installation.

This module has no Qt dependency. The desktop Help menu can run it even when a
specific user log is failing and distinguish decoder/data failures from a GUI
rendering problem.
"""

from pathlib import Path
from typing import Dict, List

from .display_data import validate_default_waveform
from .importers import load_telemetry
from .plotability import assess_plotability


BUNDLED_NATIVE_DEMOS = (
    ("native_demo_racepak.rpk", "RacePak"),
    ("native_demo_motec.ld", "MoTeC"),
    ("native_demo_maxxecu.MaxxECU-log", "MaxxECU"),
)


def run_data_pipeline_selftest(example_dir: str | Path) -> List[Dict[str, object]]:
    root=Path(example_dir)
    rows: List[Dict[str, object]]=[]
    for filename,expected_vendor in BUNDLED_NATIVE_DEMOS:
        path=root/filename
        row: Dict[str,object]={"file":filename,"expected_vendor":expected_vendor,"pass":False}
        try:
            run=load_telemetry(path)
            report=assess_plotability(run)
            points=validate_default_waveform(run,report.default_channels)
            row.update({
                "vendor":run.vendor,
                "decoder":run.metadata.get("import_decoder",""),
                "plotable":bool(report.plotable),
                "timebase":report.timebase,
                "default_channels":list(report.default_channels),
                "plot_points":points,
                "warnings":list(run.metadata.get("data_warnings",[])),
            })
            row["pass"]=(run.vendor==expected_vendor and report.plotable and bool(points) and all(int(v)>=2 for v in points.values()))
            if not row["pass"]:
                row["error"]="decoded, but vendor/plotability/default-waveform contract did not pass"
        except Exception as exc:
            row["error"]=str(exc)
        rows.append(row)
    return rows


def format_selftest(rows: List[Dict[str, object]]) -> str:
    lines=["NHRA Tech Data — import/plot data-pipeline self-test",""]
    for row in rows:
        status="PASS" if row.get("pass") else "FAIL"
        lines.append(f"[{status}] {row.get('file')} — {row.get('vendor', row.get('expected_vendor',''))}")
        if row.get('pass'):
            lines.append(f"  decoder={row.get('decoder')}  timebase={row.get('timebase')}")
            lines.append(f"  default traces={', '.join(map(str,row.get('default_channels',[])))}")
            lines.append(f"  finite plot points={row.get('plot_points')}")
        else:
            lines.append(f"  error={row.get('error','unknown')}")
        for warning in row.get('warnings',[]) or []:
            lines.append(f"  warning={warning}")
        lines.append("")
    ok=sum(bool(r.get('pass')) for r in rows)
    lines.append(f"Result: {ok}/{len(rows)} native demo pipelines passed.")
    lines.append("If all pipelines PASS but the desktop waveform is visually blank, the remaining problem is in the Qt/pyqtgraph rendering/interaction layer rather than file decoding or X/Y extraction.")
    return "\n".join(lines)
