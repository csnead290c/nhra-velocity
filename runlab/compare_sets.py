from __future__ import annotations

"""Named Compare Set/session state independent of the Qt renderer.

A Compare Set is display state, not evidence ownership. It records which loaded
runs participate in a comparison, the reference run, view-only alignment, and
optional per-display run selection. No operation here rewrites telemetry time or
server Run/Asset relationships.
"""

from dataclasses import dataclass, field, asdict
from typing import Iterable, Optional
import uuid


@dataclass
class CompareRun:
    run_key: str
    label: str = ""
    enabled: bool = True
    alignment_s: float = 0.0
    role: str = "overlay"  # main | reference | overlay

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, obj: dict) -> "CompareRun":
        return cls(
            run_key=str(obj.get("run_key", "")),
            label=str(obj.get("label", "")),
            enabled=bool(obj.get("enabled", True)),
            alignment_s=float(obj.get("alignment_s", 0.0) or 0.0),
            role=str(obj.get("role", "overlay") or "overlay"),
        )


@dataclass
class CompareSet:
    name: str
    runs: list[CompareRun] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    reference_run_key: str = ""
    display_run_selection: dict[str, list[str]] = field(default_factory=dict)
    display_alignment_s: dict[str, dict[str, float]] = field(default_factory=dict)

    def _find(self, run_key: str) -> CompareRun:
        for row in self.runs:
            if row.run_key == run_key:
                return row
        raise KeyError(run_key)

    def add_run(self, run_key: str, *, label: str = "", role: str = "overlay", alignment_s: float = 0.0) -> CompareRun:
        key = str(run_key)
        try:
            row = self._find(key)
            if label:
                row.label = str(label)
            row.role = str(role or row.role)
            row.alignment_s = float(alignment_s)
            row.enabled = True
            return row
        except KeyError:
            row = CompareRun(key, str(label), True, float(alignment_s), str(role or "overlay"))
            self.runs.append(row)
            if row.role == "reference" or not self.reference_run_key:
                self.set_reference(key)
            return row

    def remove_run(self, run_key: str) -> None:
        key = str(run_key)
        self.runs = [r for r in self.runs if r.run_key != key]
        if self.reference_run_key == key:
            self.reference_run_key = next((r.run_key for r in self.runs if r.enabled), "")
            self._sync_reference_roles()
        for display, keys in list(self.display_run_selection.items()):
            self.display_run_selection[display] = [k for k in keys if k != key]
        for display in list(self.display_alignment_s):
            self.display_alignment_s[display].pop(key, None)

    def set_reference(self, run_key: str) -> None:
        key = str(run_key)
        row = self._find(key)
        row.enabled = True
        self.reference_run_key = key
        self._sync_reference_roles()

    def _sync_reference_roles(self) -> None:
        for row in self.runs:
            if row.run_key == self.reference_run_key:
                row.role = "reference"
            elif row.role == "reference":
                row.role = "overlay"

    def set_enabled(self, run_key: str, enabled: bool) -> None:
        row = self._find(str(run_key))
        row.enabled = bool(enabled)
        if not row.enabled and self.reference_run_key == row.run_key:
            self.reference_run_key = next((r.run_key for r in self.runs if r.enabled), "")
            self._sync_reference_roles()

    def set_alignment(self, run_key: str, seconds: float, *, display_id: str = "") -> None:
        key = str(run_key)
        self._find(key)
        if display_id:
            self.display_alignment_s.setdefault(str(display_id), {})[key] = float(seconds)
        else:
            self._find(key).alignment_s = float(seconds)

    def alignment_for(self, run_key: str, *, display_id: str = "") -> float:
        key = str(run_key)
        if display_id and key in self.display_alignment_s.get(str(display_id), {}):
            return float(self.display_alignment_s[str(display_id)][key])
        return float(self._find(key).alignment_s)

    def set_display_runs(self, display_id: str, run_keys: Iterable[str]) -> None:
        known = {r.run_key for r in self.runs}
        keys = []
        for raw in run_keys:
            key = str(raw)
            if key in known and key not in keys:
                keys.append(key)
        self.display_run_selection[str(display_id)] = keys

    def runs_for_display(self, display_id: str = "") -> list[CompareRun]:
        enabled = [r for r in self.runs if r.enabled]
        if not display_id or str(display_id) not in self.display_run_selection:
            return enabled
        selected = set(self.display_run_selection[str(display_id)])
        return [r for r in enabled if r.run_key in selected]

    def step_reference(self, direction: int = 1) -> Optional[str]:
        enabled = [r.run_key for r in self.runs if r.enabled]
        if not enabled:
            self.reference_run_key = ""
            return None
        if self.reference_run_key not in enabled:
            self.set_reference(enabled[0])
            return enabled[0]
        idx = enabled.index(self.reference_run_key)
        new = enabled[(idx + (1 if direction >= 0 else -1)) % len(enabled)]
        self.set_reference(new)
        return new

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "reference_run_key": self.reference_run_key,
            "runs": [r.to_dict() for r in self.runs],
            "display_run_selection": {str(k): list(v) for k, v in self.display_run_selection.items()},
            "display_alignment_s": {
                str(display): {str(run): float(value) for run, value in values.items()}
                for display, values in self.display_alignment_s.items()
            },
        }

    @classmethod
    def from_dict(cls, obj: dict) -> "CompareSet":
        out = cls(
            name=str(obj.get("name", "Compare Set")),
            id=str(obj.get("id") or uuid.uuid4()),
            reference_run_key=str(obj.get("reference_run_key", "")),
            runs=[CompareRun.from_dict(x) for x in obj.get("runs", []) if isinstance(x, dict)],
            display_run_selection={str(k): [str(x) for x in v] for k, v in (obj.get("display_run_selection", {}) or {}).items()},
            display_alignment_s={
                str(display): {str(run): float(value) for run, value in (values or {}).items()}
                for display, values in (obj.get("display_alignment_s", {}) or {}).items()
            },
        )
        if out.reference_run_key and any(r.run_key == out.reference_run_key for r in out.runs):
            out._sync_reference_roles()
        elif out.runs:
            out.reference_run_key = next((r.run_key for r in out.runs if r.enabled), out.runs[0].run_key)
            out._sync_reference_roles()
        return out


@dataclass
class CompareSetLibrary:
    sets: list[CompareSet] = field(default_factory=list)
    active_id: str = ""

    @property
    def active(self) -> Optional[CompareSet]:
        return next((x for x in self.sets if x.id == self.active_id), None)

    def create(self, name: str, run_keys: Iterable[str] = ()) -> CompareSet:
        obj = CompareSet(str(name or "Compare Set"))
        for i, key in enumerate(run_keys):
            obj.add_run(str(key), role="reference" if i == 0 else "overlay")
        self.sets.append(obj)
        self.active_id = obj.id
        return obj

    def set_active(self, compare_set_id: str) -> CompareSet:
        obj = next((x for x in self.sets if x.id == str(compare_set_id)), None)
        if obj is None:
            raise KeyError(compare_set_id)
        self.active_id = obj.id
        return obj

    def delete(self, compare_set_id: str) -> None:
        key = str(compare_set_id)
        self.sets = [x for x in self.sets if x.id != key]
        if self.active_id == key:
            self.active_id = self.sets[0].id if self.sets else ""

    def to_dict(self) -> dict:
        return {"active_id": self.active_id, "sets": [x.to_dict() for x in self.sets]}

    @classmethod
    def from_dict(cls, obj: dict) -> "CompareSetLibrary":
        lib = cls(
            sets=[CompareSet.from_dict(x) for x in obj.get("sets", []) if isinstance(x, dict)],
            active_id=str(obj.get("active_id", "")),
        )
        if lib.active_id and not any(x.id == lib.active_id for x in lib.sets):
            lib.active_id = lib.sets[0].id if lib.sets else ""
        return lib
