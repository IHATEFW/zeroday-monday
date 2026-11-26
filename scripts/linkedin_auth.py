#!/usr/bin/env python3
"""Obtiene (o renueva) el token de LinkedIn y lo guarda como secret del repo.

LinkedIn entrega tokens de 60 días sin refresh token para apps comunes, así que
esto se corre en tu máquina cada ~2 meses (el workflow abre un issue cuando falta poco).

Uso:
    export LINKEDIN_CLIENT_ID=...  LINKEDIN_CLIENT_SECRET=...
    python scripts/linkedin_auth.py            # guarda secrets con `gh` en el repo actual
    python scripts/linkedin_auth.py --print    # solo muestra los valores, no toca GitHub

Requisitos de la app en https://www.linkedin.com/developers/apps :
  - Productos: "Share on LinkedIn" y "Sign In with LinkedIn using OpenID Connect"
  - Authorized redirect URL: http://localhost:8765/callback
"""
from __future__ import annotations

import argparse
import http.server
import os
import secrets
import subprocess
import sys
import urllib.parse
import webbrowser
from datetime import date, timedelta

import requests

REDIRECT = "http://localhost:8765/callback"
SCOPES = "openid profile w_member_social"


def wait_for_code(state: str) -> str:
    result: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            ok = q.get("state", [""])[0] == state and "code" in q
            result["code"] = q.get("code", [""])[0] if ok else ""
            result["error"] = q.get("error_description", [""])[0]
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = "Listo, ya puedes cerrar esta pestaña." if ok else "Algo falló, revisa la terminal."
            self.wfile.write(f"<h2>{msg}</h2>".encode())

        def log_message(self, *_):
            pass

    with http.server.HTTPServer(("127.0.0.1", 8765), Handler) as srv:
        while "code" not in result:
            srv.handle_request()
    if not result["code"]:
        sys.exit(f"Autorización rechazada: {result.get('error') or 'state inválido'}")
    return result["code"]


def gh_set(kind: str, name: str, value: str) -> None:
    subprocess.run(["gh", kind, "set", name, "--body", value], check=True, capture_output=True)
    print(f"  ✓ {kind} {name}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", action="store_true", help="mostrar valores en vez de guardarlos con gh")
    args = ap.parse_args()

    cid, csecret = os.getenv("LINKEDIN_CLIENT_ID"), os.getenv("LINKEDIN_CLIENT_SECRET")
    if not cid or not csecret:
        sys.exit("Define LINKEDIN_CLIENT_ID y LINKEDIN_CLIENT_SECRET (pestaña Auth de tu app de LinkedIn).")

    state = secrets.token_urlsafe(24)
    url = "https://www.linkedin.com/oauth/v2/authorization?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": cid, "redirect_uri": REDIRECT, "scope": SCOPES, "state": state})
    print("Abriendo LinkedIn para autorizar la app...\nSi no se abre, entra a:\n" + url)
    webbrowser.open(url)
    code = wait_for_code(state)

    tok = requests.post("https://www.linkedin.com/oauth/v2/accessToken", timeout=30, data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
        "client_id": cid, "client_secret": csecret})
    if tok.status_code != 200:
        sys.exit(f"Error al canjear el código: {tok.status_code} {tok.text}")
    payload = tok.json()
    access = payload["access_token"]
    expires = date.today() + timedelta(seconds=int(payload.get("expires_in", 5184000)))

    me = requests.get("https://api.linkedin.com/v2/userinfo", timeout=30, headers={"Authorization": f"Bearer {access}"})
    me.raise_for_status()
    info = me.json()
    urn = f"urn:li:person:{info['sub']}"
    print(f"\nAutorizado como {info.get('name', '?')} ({urn}). El token vence el {expires}.")

    if args.print:
        print(f"\nLINKEDIN_PERSON_URN={urn}\nLINKEDIN_TOKEN_EXPIRES_AT={expires}\nLINKEDIN_ACCESS_TOKEN={access}")
        return
    print("\nGuardando en GitHub (repo actual):")
    gh_set("secret", "LINKEDIN_ACCESS_TOKEN", access)
    gh_set("secret", "LINKEDIN_PERSON_URN", urn)
    gh_set("variable", "LINKEDIN_TOKEN_EXPIRES_AT", expires.isoformat())


if __name__ == "__main__":
    main()
