"""Puntuación y agrupación: decide qué es realmente importante antes de gastar un token de LLM.

La idea: una noticia vale por (a) señales duras de explotación (KEV, EPSS, CVSS, PoC),
(b) el tipo de bug (RCE pre-auth >> XSS reflejado), (c) cuánta gente seria habla de ella
(cobertura cruzada entre fuentes) y (d) la calidad de la fuente. Lo aburrido se castiga.
"""
from __future__ import annotations

import logging
import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

from .collect import HTTP, Item

log = logging.getLogger(__name__)

# (regex, puntos). Se suman todos los que calcen, con tope por grupo.
BOOSTS: list[tuple[str, float]] = [
    (r"\b(actively|in[- ]the[- ]wild|mass[- ]exploit\w*|under (active )?attack|being exploited|exploited)\b", 3.0),
    (r"\b0[- ]?day|zero[- ]day\b", 3.0),
    (r"\b(pre[- ]?auth\w*|unauthenticated|without authentication|no auth)\b", 2.5),
    (r"\b(RCE|remote code execution|code execution|command injection|arbitrary code)\b", 2.5),
    (r"\b(auth(entication)? bypass|account takeover|privilege escalation|sandbox escape|container escape)\b", 2.0),
    (r"\b(proof[- ]of[- ]concept|PoC|exploit (code|released|published|chain)|exploit chain|weaponi[sz]ed)\b", 2.0),
    (r"\b(backdoor\w*|trojani[sz]ed|compromised (package|account|maintainer)|supply[- ]chain|typosquat\w*|malicious (npm|pypi|package|extension|crate))\b", 2.5),
    (r"\b(npm|pypi|github actions?|docker hub|vs ?code extension|chrome extension)\b", 0.8),
    (r"\b(breach\w*|leak\w*|stolen|exfiltrat\w*|data theft|dumped|exposed (database|records|data))\b", 2.0),
    (r"\b(ransomware|extortion|wiper)\b", 1.5),
    (r"\b(prompt injection|jailbreak\w*|LLM|AI agent|agentic|MCP|model context protocol|copilot|chatgpt|claude|gemini|cursor)\b", 1.8),
    (r"\b(deseriali[sz]ation|SSRF|path traversal|SQL injection|SQLi|XXE|SSTI|request smuggling|type confusion|use[- ]after[- ]free|heap overflow|memory corruption)\b", 1.2),
    (r"\b(fortinet|fortigate|fortiweb|ivanti|citrix|netscaler|palo alto|pan-os|globalprotect|cisco|f5|big-?ip|sonicwall|vmware|vcenter|esxi|exchange|sharepoint|confluence|jira|gitlab|jenkins|php|wordpress|openssh|linux kernel|chrome|ios|android|windows|active directory|okta|entra|aws|azure|kubernetes|oracle|sap|veeam|moveit|zimbra)\b", 1.0),
    (r"\b(million|billion|millones|mil millones)\b", 1.0),
    (r"\b(CVSS (score )?(of )?(9\.\d|10(\.0)?))\b", 1.5),
]

PENALTIES: list[tuple[str, float]] = [
    (r"\b(ISO ?27001|ISO/IEC|compliance|cumplimiento|governance|gobernanza|regulat\w*|regulación|legislat\w*|law(s)?\b|ley\b|GDPR|NIS ?2|DORA|SEC rule|framework|policy|policies|directive|standard)\b", -4.0),
    (r"\b(webinar|podcast|event|conference|summit|keynote|award\w*|named a leader|gartner|forrester|report finds|survey|study finds|whitepaper|e-?book)\b", -3.0),
    (r"\b(funding|raises \$|series [abcd]|acquires|acquisition|merger|IPO|partnership|partners with|launches|announces|unveils|now available|general availability|pricing)\b", -3.5),
    (r"\b(week in review|weekly recap|recap|roundup|newsletter|this week in|wrap-?up|top \d+|best practices|tips|how to choose|guide to|what is|explained|career|hiring|jobs?)\b", -3.0),
    (r"\b(awareness|concientización|training|phishing simulation|board|CISO (says|role)|strategy|estrategia)\b", -2.0),
    (r"\b(sponsored|partner content|advertorial)\b", -5.0),
]

_BOOSTS = [(re.compile(p, re.I), w) for p, w in BOOSTS]
_PENALTIES = [(re.compile(p, re.I), w) for p, w in PENALTIES]
_WORD = re.compile(r"[a-z0-9][a-z0-9\-\.]{2,}")
_STOP = set("the and for with from that this into over after about your their have has are was were will new "
            "how why what who its it's you can more than just been being via says said hackers hacker "
            "security vulnerability vulnerabilities flaw flaws attack attacks exploit exploited critical "
            "patch patches update updates bug bugs using used users user data".split())


def keyword_score(text: str) -> tuple[float, list[str]]:
    score, hits = 0.0, []
    for rx, w in _BOOSTS:
        m = rx.search(text)
        if m:
            score += w
            hits.append(m.group(0).lower())
    for rx, w in _PENALTIES:
        m = rx.search(text)
        if m:
            score += w
            hits.append(f"-{m.group(0).lower()}")
    return score, hits


def tokens(title: str) -> set[str]:
    return {w for w in _WORD.findall(title.lower()) if w not in _STOP}


# ---------------------------------------------------------------- clusters

@dataclass
class Story:
    items: list[Item]
    cves: set[str] = field(default_factory=set)
    score: float = 0.0
    signals: dict = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    @property
    def lead(self) -> Item:
        # Preferimos como "nota principal" la fuente de investigación con más peso.
        order = {"research": 0, "ai": 0, "breach": 1, "exploit": 2, "advisory": 2, "news": 3}
        return sorted(self.items, key=lambda i: (order.get(i.kind, 3), -i.weight))[0]

    @property
    def sources(self) -> list[str]:
        return sorted({i.source for i in self.items})

    @property
    def key(self) -> str:
        if self.cves:
            return sorted(self.cves)[0]
        return " ".join(sorted(tokens(self.lead.title)))[:120]


def cluster(items: list[Item]) -> list[Story]:
    """Agrupa la misma noticia contada por varias fuentes (por CVE o por similitud de título)."""
    stories: list[Story] = []
    for it in sorted(items, key=lambda i: -i.weight):
        toks = tokens(it.title)
        match = None
        pk = it.extra.get("product_key")
        for st in stories:
            if it.cves and st.cves & it.cves:
                match = st
                break
            if pk and any(pk == i.extra.get("product_key") for i in st.items):
                match = st
                break
            st_toks = tokens(st.lead.title)
            if toks and st_toks:
                jac = len(toks & st_toks) / len(toks | st_toks)
                if jac >= 0.45 or (len(toks & st_toks) >= 4 and jac >= 0.3):
                    match = st
                    break
        if match:
            match.items.append(it)
            match.cves |= it.cves
        else:
            stories.append(Story(items=[it], cves=set(it.cves)))
    return stories


# ---------------------------------------------------------------- enrichment

def epss(cves: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for i in range(0, len(cves), 80):
        chunk = cves[i:i + 80]
        try:
            r = HTTP.get("https://api.first.org/data/v1/epss", params={"cve": ",".join(chunk)}, timeout=20)
            r.raise_for_status()
            for row in r.json().get("data", []):
                out[row["cve"].upper()] = float(row["epss"])
        except (requests.RequestException, ValueError, KeyError):
            log.warning("EPSS no disponible para un bloque de CVEs")
    return out


def cvss(cve: str, api_key: str | None = None) -> float | None:
    try:
        r = HTTP.get("https://services.nvd.nist.gov/rest/json/cves/2.0", params={"cveId": cve}, timeout=20,
                     headers={"apiKey": api_key} if api_key else {})
        r.raise_for_status()
        vulns = r.json().get("vulnerabilities", [])
        if not vulns:
            return None
        metrics = vulns[0]["cve"].get("metrics", {})
        for key in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30"):
            if metrics.get(key):
                return float(metrics[key][0]["cvssData"]["baseScore"])
    except (requests.RequestException, ValueError, KeyError, IndexError):
        return None
    return None


def score_stories(stories: list[Story], kev: dict[str, dict], *, use_epss=True, use_nvd=True,
                  nvd_key: str | None = None, posted_keys: set[str] = frozenset(),
                  posted_links: set[str] = frozenset()) -> list[Story]:
    now = datetime.now(timezone.utc)

    # 1) Puntaje base (sin red) para decidir a cuáles vale la pena enriquecer.
    for st in stories:
        text = " ".join(i.text for i in st.items)
        kw, hits = keyword_score(text)
        best_weight = max(i.weight for i in st.items)
        coverage = len(st.sources)
        newest = max(i.published for i in st.items)
        age_days = max((now - newest).total_seconds() / 86400, 0)

        st.score = kw * best_weight
        st.score += 3.5 * math.log2(coverage)  # cobertura cruzada: 2 fuentes +3.5, 4 fuentes +7
        st.score -= 0.25 * age_days  # frescura: el lunes queremos lo de esta semana
        st.signals = {"coverage": coverage, "age_days": round(age_days, 1)}
        st.reasons = hits[:8]

        hn = max((i.extra.get("hn_points", 0) for i in st.items), default=0)
        if hn:
            st.score += min(hn / 200, 5.0)
            st.signals["hn_points"] = hn
        pwn = max((i.extra.get("pwn_count", 0) for i in st.items), default=0)
        if pwn:
            st.score += min(math.log10(max(pwn, 1)) - 4, 4.0) if pwn > 10_000 else -2
            st.signals["pwn_count"] = pwn
        if any(i.extra.get("ransomware") for i in st.items):
            st.score += 1.5
            st.signals["ransomware"] = True

        # KEV es la señal más fuerte que existe de "esto se está explotando ahora".
        in_kev = [c for c in st.cves if c in kev]
        if in_kev:
            st.score += 5.0
            st.signals["kev"] = in_kev
            if any(kev[c].get("knownRansomwareCampaignUse") == "Known" for c in in_kev):
                st.score += 1.5
                st.signals["ransomware"] = True

        # Penalizar lo ya publicado en semanas anteriores.
        if st.key in posted_keys or any(c in posted_keys for c in st.cves) or any(i.link in posted_links for i in st.items):
            st.score -= 100
            st.signals["already_posted"] = True

    stories.sort(key=lambda s: -s.score)

    # 2) Enriquecer solo el top con EPSS/CVSS (APIs con límites de tasa).
    top = [s for s in stories[:40] if s.cves]
    if use_epss and top:
        scores = epss(sorted({c for s in top for c in s.cves}))
        for st in top:
            best = max((scores.get(c, 0.0) for c in st.cves), default=0.0)
            if best:
                st.signals["epss"] = round(best, 3)
                st.score += 4.0 * best
    if use_nvd:
        for n, st in enumerate(top[:10]):
            if n and not nvd_key:
                time.sleep(6.5)  # NVD sin API key: 5 peticiones cada 30 s
            best = max((v for v in (cvss(c, nvd_key) for c in sorted(st.cves)[:2]) if v), default=None)
            if best:
                st.signals["cvss"] = best
                st.score += max(best - 7.0, 0) * 1.0

    stories.sort(key=lambda s: -s.score)
    return stories
