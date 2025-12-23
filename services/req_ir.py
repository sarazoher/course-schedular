from __future__ import annotations
from dataclasses import dataclass
from typing import Union, List

@dataclass(frozen=True)
class ReqLeaf:
    # For internal courses, 'code' is a resolved catalog course code.
    # For external/unresolved tokens, 'code' is None and 'kind' captures the classification.
    code: str | None
    raw: str
    kind: str = "internal" # "internal" | "external" | "unresolved"

@dataclass(frozen=True)
class ReqAnd:
    items: List["Req"]

@dataclass(frozen=True)
class ReqOr:
    items: List["Req"]

Req = Union[ReqLeaf, ReqAnd, ReqOr]
