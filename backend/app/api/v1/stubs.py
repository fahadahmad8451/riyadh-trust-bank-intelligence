"""Honest 501 stubs for endpoints whose sprints have not run yet.

Design section 6 lists these endpoints; Setup v0.1 does NOT fake them.
Sprint 4 implemented the last two (feedback + evaluation), so there
are NO stubs left in v0.5 — this module is kept so main.py still has
a single place that lists what, if anything, is pending.
"""
from fastapi import APIRouter

router = APIRouter()

# (method, path, sprint, summary) — empty in v0.5: everything is built.
STUBS: list[tuple[str, str, str, str]] = []
