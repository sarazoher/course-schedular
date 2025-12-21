from __future__ import annotations
from dataclasses import dataclass
from typing import Union, List

@dataclass(frozen=True)
class ReqLeaf:
    # store course code if known; otherwise token string
    code: str | None
    raw: str

@dataclass(frozen=True)
class ReqAnd:
    items: List["Req"]

@dataclass(frozen=True)
class ReqOr:
    items: List["Req"]

Req = Union[ReqLeaf, ReqAnd, ReqOr]
