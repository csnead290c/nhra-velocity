from __future__ import annotations

"""Persistent engineering bookmarks and A/B regions attached to a run."""

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional
import uuid

from .models import TelemetryRun


VALID_KINDS={"bookmark","region"}


@dataclass
class Annotation:
    id: str
    kind: str
    label: str
    x_mode: str
    x1: float
    x2: Optional[float] = None
    note: str = ""
    color: str = "#8f949a"
    source: str = "user"

    @classmethod
    def from_dict(cls, obj: Dict[str, Any]) -> "Annotation":
        kind=str(obj.get("kind","bookmark"))
        if kind not in VALID_KINDS:
            raise ValueError(f"Unknown annotation kind: {kind}")
        return cls(
            id=str(obj.get("id") or uuid.uuid4().hex),
            kind=kind,
            label=str(obj.get("label") or ("Bookmark" if kind=="bookmark" else "Region")),
            x_mode=str(obj.get("x_mode") or "Time from Launch"),
            x1=float(obj.get("x1",0.0)),
            x2=None if obj.get("x2") is None else float(obj.get("x2")),
            note=str(obj.get("note") or ""),
            color=str(obj.get("color") or "#8f949a"),
            source=str(obj.get("source") or "user"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def annotations(run: TelemetryRun) -> List[Annotation]:
    out=[]
    for obj in run.metadata.get("annotations",[]) or []:
        try:
            out.append(Annotation.from_dict(dict(obj)))
        except Exception:
            continue
    return out


def _save(run: TelemetryRun, rows: List[Annotation]):
    run.metadata["annotations"]=[r.to_dict() for r in rows]


def add_bookmark(run: TelemetryRun, x: float, label: str, *, x_mode: str="Time from Launch", note: str="", color: str="#8f949a", source: str="user") -> Annotation:
    row=Annotation(uuid.uuid4().hex,"bookmark",str(label).strip() or "Bookmark",str(x_mode),float(x),None,str(note),str(color),str(source))
    rows=annotations(run); rows.append(row); _save(run,rows); return row


def add_region(run: TelemetryRun, x1: float, x2: float, label: str, *, x_mode: str="Time from Launch", note: str="", color: str="#5b8fb9", source: str="user") -> Annotation:
    a,b=sorted((float(x1),float(x2)))
    if b<=a:
        raise ValueError("Region end must be greater than region start.")
    row=Annotation(uuid.uuid4().hex,"region",str(label).strip() or "Region",str(x_mode),a,b,str(note),str(color),str(source))
    rows=annotations(run); rows.append(row); _save(run,rows); return row


def delete_annotation(run: TelemetryRun, annotation_id: str) -> bool:
    rows=annotations(run); new=[r for r in rows if r.id != str(annotation_id)]
    changed=len(new)!=len(rows)
    if changed:_save(run,new)
    return changed


def clear_annotations(run: TelemetryRun):
    run.metadata["annotations"]=[]


def annotations_for_mode(run: TelemetryRun, x_mode: str) -> List[Annotation]:
    mode=str(x_mode).strip().lower()
    return [a for a in annotations(run) if str(a.x_mode).strip().lower()==mode]
