"""Cliente mínimo de la API REST de LinkedIn (Posts API + Images API + Comments)."""
from __future__ import annotations

import logging
import os
import re
from datetime import date
from urllib.parse import quote

import requests

log = logging.getLogger(__name__)
API = "https://api.linkedin.com/rest"

# El campo "commentary" usa el formato "little text": estos caracteres deben escaparse
# o LinkedIn corta el post en silencio (el clásico bug de los paréntesis).
_RESERVED = re.compile(r"([\\|{}@\[\]()<>#*_~])")


def escape(text: str) -> str:
    return _RESERVED.sub(r"\\\1", text)


def hashtag(tag: str) -> str:
    tag = re.sub(r"[^\w]", "", tag.lstrip("#"))
    return "{hashtag|\\#|" + tag + "}"


def api_version() -> str:
    """LinkedIn versiona por mes (YYYYMM) y retira versiones a ~1 año. Usamos la de hace 2 meses."""
    if v := os.getenv("LINKEDIN_VERSION"):
        return v
    t = date.today()
    y, m = (t.year, t.month - 2) if t.month > 2 else (t.year - 1, t.month + 10)
    return f"{y}{m:02d}"


class LinkedIn:
    def __init__(self, token: str, person_urn: str):
        if not person_urn.startswith("urn:li:"):
            person_urn = f"urn:li:person:{person_urn}"
        self.author = person_urn
        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": f"Bearer {token}",
            "LinkedIn-Version": api_version(),
            "X-Restli-Protocol-Version": "2.0.0",
        })

    def _check(self, r: requests.Response, what: str) -> requests.Response:
        if r.status_code >= 400:
            raise RuntimeError(f"LinkedIn {what} falló: HTTP {r.status_code} {r.text[:500]}")
        return r

    def upload_image(self, png: bytes) -> str:
        r = self._check(self.s.post(f"{API}/images?action=initializeUpload", timeout=30,
                                    json={"initializeUploadRequest": {"owner": self.author}}), "initializeUpload")
        value = r.json()["value"]
        up = requests.put(value["uploadUrl"], data=png, timeout=60,
                          headers={"Authorization": self.s.headers["Authorization"], "Content-Type": "image/png"})
        self._check(up, "subida de imagen")
        return value["image"]

    def post(self, text: str, hashtags: list[str], image_urn: str | None = None, alt: str = "") -> str:
        commentary = escape(text.strip())
        if hashtags:
            commentary += "\n\n" + " ".join(hashtag(h) for h in hashtags)
        body = {
            "author": self.author,
            "commentary": commentary,
            "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        if image_urn:
            body["content"] = {"media": {"id": image_urn, "altText": alt[:4000]}}
        r = self._check(self.s.post(f"{API}/posts", json=body, timeout=30), "publicación")
        urn = r.headers.get("x-restli-id") or r.headers.get("x-linkedin-id", "")
        log.info("publicado: %s", urn)
        return urn

    def comment(self, post_urn: str, text: str) -> None:
        r = self.s.post(f"{API}/socialActions/{quote(post_urn, safe='')}/comments", timeout=30, json={
            "actor": self.author, "object": post_urn, "message": {"text": text}})
        self._check(r, "comentario")

    @staticmethod
    def url_for(post_urn: str) -> str:
        return f"https://www.linkedin.com/feed/update/{post_urn}/"
