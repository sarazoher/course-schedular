from __future__ import annotations
import re
from services.req_ir import Req, ReqLeaf, ReqAnd, ReqOr


def normalize_text(s: str) -> str:
    s = s.strip()
    s = s.replace("–", "-")
    s = re.sub(r"\s+", " ", s)
    return s

def split_top(s: str, sep: str) -> list[str]:
    # no parentheses in your data (yet), so simple split is OK
    return [p.strip() for p in s.split(sep) if p.strip()]

def _is_valid_split_item(node) -> bool:
    """
    Split is 'valid' only if the resulting subtree contains no unresolved leaves.
    External leaves are allowed.
    """
    if node is None:
        return False

    if isinstance(node, ReqLeaf):
        return (node.code is not None) or (node.kind == "external")

    if isinstance(node, (ReqAnd, ReqOr)):
        return all(_is_valid_split_item(child) for child in node.items)

    return False

def parse_req_text(text: str, resolve) -> Req | None:
    """
    resolve(token:str) -> (code|None, raw_token, kind)

         where is 'kind' is one of: "internal" | "external" | "unresolved"
    """
    if not text:
        return None
    text = normalize_text(text)

    # Fix common catalog artifacts
    text = text.replace("++C", "C++")
    text = text.replace(" + +C", " C++")  # extra defense


    # --- Normalize known tokenization artifacts BEFOREE parsing ---

    # OR level
    if "/" in text:
        parts = split_top(text, "/")
        items = [parse_req_text(p, resolve) for p in parts]

        if all(_is_valid_split_item(item) for item in items):
            return ReqOr(dedupe(items))


    # AND level
    if "+" in text:
        parts = split_top(text, "+")
        items = [parse_req_text(p, resolve) for p in parts]

        if all(_is_valid_split_item(item) for item in items):
            return ReqAnd(dedupe(items))


    # leaf
    code, raw, kind = resolve(text)

    return ReqLeaf(code=code, raw=raw, kind=kind)

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
