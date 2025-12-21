from __future__ import annotations
import re
from services.req_ir import Req, ReqAnd, ReqOr, ReqLeaf

def normalize_text(s: str) -> str:
    s = s.strip()
    s = s.replace("–", "-")
    s = re.sub(r"\s+", " ", s)
    return s

def split_top(s: str, sep: str) -> list[str]:
    # no parentheses in your data (yet), so simple split is OK
    return [p.strip() for p in s.split(sep) if p.strip()]

def parse_req_text(text: str, resolve) -> Req | None:
    """
    resolve(token:str) -> (code|None, raw_token)
    """
    if not text:
        return None
    text = normalize_text(text)

    # OR level
    if "/" in text:
        parts = split_top(text, "/")
        items = [parse_req_text(p, resolve) for p in parts]
        items = [x for x in items if x is not None]
        return ReqOr(dedupe(items))

    # AND level
    if "+" in text:
        parts = split_top(text, "+")
        items = [parse_req_text(p, resolve) for p in parts]
        items = [x for x in items if x is not None]
        return ReqAnd(dedupe(items))

    # leaf
    code, raw = resolve(text)
    return ReqLeaf(code=code, raw=raw)

def dedupe(items: list[Req]) -> list[Req]:
    seen = set()
    out = []
    for it in items:
        key = repr(it)
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out
