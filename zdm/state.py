"""Historial de lo publicado (data/history.json), versionado en el propio repo."""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HISTORY = ROOT / "data" / "history.json"


def load() -> list[dict]:
    if HISTORY.exists():
        return json.loads(HISTORY.read_text(encoding="utf-8"))
    return []


def save(entries: list[dict]) -> None:
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    HISTORY.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def posted_keys(entries: list[dict]) -> tuple[set[str], set[str]]:
    keys, links = set(), set()
    for e in entries:
        keys.add(e.get("key", ""))
        keys.update(e.get("cves", []))
        links.update(e.get("links", []))
    keys.discard("")
    return keys, links


def already_posted_this_week(entries: list[dict], today: date) -> bool:
    week = today.isocalendar()[:2]
    for e in entries:
        if e.get("urn") and datetime.fromisoformat(e["date"]).date().isocalendar()[:2] == week:
            return True
    return False
