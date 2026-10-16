"""Cycle history: what has already been injected this run.

Fault selection reads it to avoid repeating a direction; query formulation
and synthesis read it so the next search looks somewhere new.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bedlam.faults.primitives import FaultKind
from bedlam.topology import Layer


@dataclass(frozen=True, slots=True)
class FaultRecord:
    cycle: int
    option_id: str
    layer: Layer
    kind: FaultKind
    specialist: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle": self.cycle,
            "fault_id": self.option_id,
            "layer": self.layer.value,
            "kind": self.kind.value,
            "specialist": self.specialist,
        }
