"""Attorney-only X-Ray routes. Nothing here is reachable through /api/provider/*."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import service

router = APIRouter(prefix="/api/attorney/xray", tags=["xray"])


def _get(as_of: Optional[str] = None) -> dict:
    try:
        return service.get(as_of)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("")
def xray(as_of: Optional[str] = None):
    x = _get(as_of)
    x["stress"] = None if as_of else service.cached_stress()
    return x


@router.get("/graph")
def xray_graph(as_of: Optional[str] = None):
    return _get(as_of)["graph"]


@router.get("/issues")
def issues(as_of: Optional[str] = None):
    return _get(as_of)["issues"]


@router.get("/issues/{issue_id}")
def issue(issue_id: str):
    i = next((i for i in _get()["issues"] if i["id"] == issue_id), None)
    if not i:
        raise HTTPException(404, "Issue not found")
    return i


class ActionIn(BaseModel):
    action_type: str
    content: Optional[str] = None


@router.post("/issues/{issue_id}/actions")
def action(issue_id: str, inp: ActionIn):
    try:
        return service.add_action(issue_id, inp.action_type, inp.content)
    except KeyError:
        raise HTTPException(404, "Issue not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/stress-test")
def stress(force: bool = False):
    try:
        return service.stress(force)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/rebuild")
def rebuild():
    """Recompute X-Ray for the current digest (e.g. after detector changes). May call the LLM once (cached)."""
    from ..digest import load_digest

    d = load_digest()
    if not d:
        raise HTTPException(404, "No digest yet")
    x = service.build(d, force=True)
    return {"content_hash": x["content_hash"], "total": x["total"], "counts": x["counts"]}
