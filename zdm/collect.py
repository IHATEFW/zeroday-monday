"""Recolección de noticias desde feeds RSS/Atom y APIs estructuradas."""
from __future__ import annotations

import concurrent.futures as cf
import html
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import feedparser
import requests

log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (X11; Linux x86_64) zeroday-monday/1.0 (+https://github.com/IHATEFW/zeroday-monday)"
HTTP = requests.Session()
HTTP.headers["User-Agent"] = UA

CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.I)
TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class Item:
    title: str
    link: str
    source: str
    kind: str
    weight: float
    published: datetime
    summary: str = ""
    cves: set[str] = field(default_factory=set)
    extra: dict = field(default_factory=dict)  # señales específicas de la fuente (pwn_count, points, ...)

    @property
    def text(self) -> str:
        return f"{self.title} {self.summary}"


def clean(text: str, limit: int = 600) -> str:
    text = html.unescape(TAG_RE.sub(" ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _date(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        t = entry.get(key)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None


def fetch_feed(src: dict, since: datetime) -> list[Item]:
    try:
        r = HTTP.get(src["url"], timeout=25)
        r.raise_for_status()
    except requests.RequestException as e:
        log.warning("feed caído: %s (%s)", src["name"], e)
        return []
    parsed = feedparser.parse(r.content)
    out = []
    for e in parsed.entries:
        published = _date(e)
        if not published or published < since:
            continue
        title = clean(e.get("title", ""), 300)
        summary = clean(e.get("summary", "") or e.get("description", ""))
        if not title or not e.get("link"):
            continue
        out.append(Item(
            title=title, link=e["link"], source=src["name"], kind=src.get("kind", "news"),
            weight=float(src.get("weight", 1.0)), published=published, summary=summary,
            cves={c.upper() for c in CVE_RE.findall(f"{title} {summary}")},
        ))
    log.info("%-32s %3d items", src["name"], len(out))
    return out


# ---------------------------------------------------------------- APIs

def fetch_kev() -> dict[str, dict]:
    """Catálogo completo de CISA KEV indexado por CVE."""
    try:
        r = HTTP.get("https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json", timeout=40)
        r.raise_for_status()
        return {v["cveID"].upper(): v for v in r.json()["vulnerabilities"]}
    except (requests.RequestException, ValueError, KeyError) as e:
        log.warning("KEV no disponible: %s", e)
        return {}


def kev_items(kev: dict[str, dict], since: datetime) -> list[Item]:
    """Cada CVE agregado al KEV esta semana es un candidato por sí mismo."""
    out = []
    for cve, v in kev.items():
        try:
            added = datetime.fromisoformat(v["dateAdded"]).replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        if added < since:
            continue
        out.append(Item(
            title=f"{v.get('vendorProject', '')} {v.get('product', '')}: {v.get('vulnerabilityName', cve)}".strip(),
            link=f"https://nvd.nist.gov/vuln/detail/{cve}",
            source="CISA KEV", kind="advisory", weight=1.2, published=added,
            summary=clean(v.get("shortDescription", "")), cves={cve},
            extra={"ransomware": v.get("knownRansomwareCampaignUse") == "Known",
                   "product_key": f"{v.get('vendorProject', '')} {v.get('product', '')}".lower().strip()},
        ))
    log.info("%-32s %3d items", "CISA KEV (nuevos)", len(out))
    return out


def hibp_items(since: datetime) -> list[Item]:
    """Brechas recién cargadas en Have I Been Pwned (API pública, sin key)."""
    try:
        r = HTTP.get("https://haveibeenpwned.com/api/v3/breaches", timeout=30)
        r.raise_for_status()
        breaches = r.json()
    except (requests.RequestException, ValueError) as e:
        log.warning("HIBP no disponible: %s", e)
        return []
    out = []
    for b in breaches:
        try:
            added = datetime.fromisoformat(b["AddedDate"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if added < since or b.get("IsSpamList") or b.get("IsFabricated"):
            continue
        n = int(b.get("PwnCount", 0))
        out.append(Item(
            title=f"Brecha de {b['Title']}: {n:,} cuentas expuestas".replace(",", "."),
            link=f"https://haveibeenpwned.com/Breach/{b['Name']}",
            source="Have I Been Pwned", kind="breach", weight=1.0, published=added,
            summary=clean(b.get("Description", "")) + " Datos: " + ", ".join(b.get("DataClasses", [])),
            extra={"pwn_count": n},
        ))
    log.info("%-32s %3d items", "Have I Been Pwned", len(out))
    return out


HN_QUERIES = ["vulnerability", "exploit", "RCE", "zero-day", "breach", "hacked", "prompt injection",
              "backdoor", "CVE", "leaked", "malware", "supply chain attack", "jailbreak"]


def hn_items(since: datetime) -> list[Item]:
    """Historias de seguridad con tracción real en Hacker News (>=80 puntos)."""
    seen, out = set(), []
    ts = int(since.timestamp())
    for q in HN_QUERIES:
        try:
            r = HTTP.get("https://hn.algolia.com/api/v1/search", timeout=20, params={
                "query": q, "tags": "story", "numericFilters": f"created_at_i>{ts},points>=80", "hitsPerPage": 20})
            r.raise_for_status()
            hits = r.json().get("hits", [])
        except (requests.RequestException, ValueError):
            continue
        for h in hits:
            url = h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}"
            if h["objectID"] in seen:
                continue
            seen.add(h["objectID"])
            title = clean(h.get("title", ""), 300)
            out.append(Item(
                title=title, link=url, source="Hacker News", kind="news", weight=0.9,
                published=datetime.fromtimestamp(h["created_at_i"], tz=timezone.utc),
                summary=f"{h.get('points', 0)} puntos y {h.get('num_comments', 0)} comentarios en Hacker News.",
                cves={c.upper() for c in CVE_RE.findall(title)},
                extra={"hn_points": h.get("points", 0)},
            ))
    log.info("%-32s %3d items", "Hacker News", len(out))
    return out


def ghsa_items(since: datetime) -> list[Item]:
    """GitHub Security Advisories críticos revisados de la semana."""
    try:
        r = HTTP.get("https://api.github.com/advisories", timeout=25, params={
            "severity": "critical", "type": "reviewed", "per_page": 50,
            "published": f">={since.date().isoformat()}"},
            headers={"Accept": "application/vnd.github+json"})
        r.raise_for_status()
        advisories = r.json()
    except (requests.RequestException, ValueError) as e:
        log.warning("GHSA no disponible: %s", e)
        return []
    out = []
    for a in advisories:
        pkgs = ", ".join(sorted({v["package"]["name"] for v in a.get("vulnerabilities", []) if v.get("package")}))
        out.append(Item(
            title=clean(a.get("summary", ""), 300) + (f" ({pkgs})" if pkgs else ""),
            link=a.get("html_url", ""), source="GitHub Advisories", kind="advisory", weight=0.8,
            published=datetime.fromisoformat(a["published_at"].replace("Z", "+00:00")),
            summary=clean(a.get("description", "")),
            cves={a["cve_id"].upper()} if a.get("cve_id") else set(),
        ))
    log.info("%-32s %3d items", "GitHub Advisories", len(out))
    return out


def collect(cfg: dict) -> tuple[list[Item], dict[str, dict]]:
    since = datetime.now(timezone.utc) - timedelta(days=int(cfg.get("lookback_days", 8)))
    apis = cfg.get("apis", {})
    items: list[Item] = []
    kev: dict[str, dict] = {}
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        futs = [ex.submit(fetch_feed, src, since) for src in cfg.get("feeds", [])]
        kev_f = ex.submit(fetch_kev) if apis.get("cisa_kev", True) else None
        if apis.get("hibp", True):
            futs.append(ex.submit(hibp_items, since))
        if apis.get("hacker_news", True):
            futs.append(ex.submit(hn_items, since))
        if apis.get("github_advisories", True):
            futs.append(ex.submit(ghsa_items, since))
        for f in futs:
            items.extend(f.result())
        if kev_f:
            kev = kev_f.result()
            items.extend(kev_items(kev, since))
    return items, kev
