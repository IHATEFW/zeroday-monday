"""Zero-Day Monday: el post semanal de seguridad ofensiva.

    python -m zdm candidates          # ver el ranking de la semana (no usa LLM ni publica)
    python -m zdm run --dry-run       # genera post + imagen en posts/, sin publicar
    python -m zdm run                 # genera y publica en LinkedIn
    python -m zdm run --scheduled     # igual, pero respeta la hora local y "una vez por semana"
    python -m zdm card-demo           # renderiza una imagen de ejemplo
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from . import card, state
from .collect import collect
from .score import score_stories, cluster

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("zdm")


def load_cfg() -> tuple[dict, dict]:
    sources = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    settings = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))
    return sources, settings


def gh_output(key: str, value: str) -> None:
    if path := os.getenv("GITHUB_OUTPUT"):
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")


def gh_summary(md: str) -> None:
    if path := os.getenv("GITHUB_STEP_SUMMARY"):
        with open(path, "a", encoding="utf-8") as f:
            f.write(md + "\n")


def ranked(sources: dict, history: list[dict]):
    items, kev = collect(sources)
    log.info("total: %d items de %d fuentes", len(items), len({i.source for i in items}))
    keys, links = state.posted_keys(history)
    apis = sources.get("apis", {})
    return score_stories(cluster(items), kev, use_epss=apis.get("epss", True), use_nvd=apis.get("nvd", True),
                         nvd_key=os.getenv("NVD_API_KEY"), posted_keys=keys, posted_links=links)


def candidates_table(stories, n: int = 25) -> str:
    rows = ["| # | Puntaje | Noticia | Fuentes | Señales |", "|---|---|---|---|---|"]
    for i, s in enumerate(stories[:n], 1):
        sig = ", ".join(f"{k}={v}" for k, v in s.signals.items() if k not in ("age_days",))
        title = s.lead.title.replace("|", "/")[:110]
        rows.append(f"| {i} | {s.score:.1f} | [{title}]({s.lead.link}) | {len(s.sources)} | {sig} |")
    return "\n".join(rows)


def cmd_candidates(_args) -> int:
    sources, _ = load_cfg()
    stories = ranked(sources, state.load())
    table = candidates_table(stories)
    print(table)
    gh_summary("## Candidatos de la semana\n\n" + table)
    return 0


def token_check() -> None:
    exp = os.getenv("LINKEDIN_TOKEN_EXPIRES_AT", "").strip()
    if not exp:
        return
    try:
        days = (datetime.fromisoformat(exp).date() - date.today()).days
    except ValueError:
        return
    if days <= 10:
        print(f"::warning::El token de LinkedIn vence en {days} días ({exp}). Corre scripts/linkedin_auth.py")
        gh_output("token_expiring", "true")
        gh_output("token_days", str(days))


def cmd_run(args) -> int:
    sources, settings = load_cfg()
    tz = ZoneInfo(settings.get("timezone", "America/Santiago"))
    now_local = datetime.now(timezone.utc).astimezone(tz)
    history = state.load()

    if args.scheduled and not args.force:
        # GitHub Actions trabaja en UTC y Chile cambia de horario: el cron dispara dos veces y aquí
        # decidimos cuál de las dos es "las 07:30 locales". También evitamos doble publicación.
        hour = int(settings.get("publish_hour", 7))
        if now_local.weekday() != 0 or not (hour <= now_local.hour < hour + 3):
            log.info("fuera de la ventana de publicación (%s), nada que hacer", now_local.isoformat())
            return 0
        if state.already_posted_this_week(history, now_local.date()):
            log.info("ya se publicó esta semana, nada que hacer")
            return 0

    token_check()
    stories = ranked(sources, history)
    shortlist = [s for s in stories if not s.signals.get("already_posted")][: int(settings.get("shortlist_size", 18))]
    if not shortlist:
        log.error("no hay candidatos esta semana")
        return 1

    from .writer import write_post  # import tardío: `candidates` no necesita la API key

    data, by_id = write_post(shortlist, settings, [h.get("title", "") for h in history])
    chosen = by_id[data["chosen_id"]]
    post_cfg = settings.get("post", {})

    text = data["post_text"].strip()
    first_comment = data["first_comment"].strip()
    sources_in_comment = post_cfg.get("link_in_first_comment", True) and bool(first_comment)
    if sources_in_comment:
        text += "\n\nFuentes en el primer comentario 👇"
    else:
        text += f"\n\n🔗 Fuente: {chosen.lead.link}"

    edition = len([h for h in history if h.get("urn")]) + 1
    day = now_local.date()
    outdir = ROOT / "posts" / day.isoformat()
    brand = settings.get("brand", {})
    png = card.render(data["card"], outdir / "card.png", edition=edition, day=day,
                      series=brand.get("series", "ZERO-DAY MONDAY"), handle=brand.get("handle", ""))

    hashtags = data["hashtags"][: int(post_cfg.get("hashtags", 3))]
    preview = (f"{text}\n\n" + " ".join("#" + h.lstrip('#') for h in hashtags)
               + (f"\n\n---\n**Primer comentario:**\n\n{first_comment}" if sources_in_comment else ""))
    (outdir / "post.md").write_text(preview + "\n", encoding="utf-8")
    meta = {
        "date": now_local.isoformat(), "title": chosen.lead.title, "key": chosen.key,
        "cves": sorted(chosen.cves), "links": [i.link for i in chosen.items], "sources": chosen.sources,
        "signals": chosen.signals, "why": data["why_chosen"], "radar": [by_id[i].lead.title for i in data["radar_ids"] if i in by_id],
        "chars": len(text), "card": data["card"], "urn": None,
    }

    print("\n" + "=" * 70 + f"\n{preview}\n" + "=" * 70)
    print(f"\nPor qué esta: {data['why_chosen']}\nImagen: {png}")
    gh_summary(f"## Post de la semana ({len(text)} caracteres)\n\n> {data['why_chosen']}\n\n```text\n{preview}\n```\n\n"
               f"## Shortlist\n\n{candidates_table(shortlist, 18)}")

    if args.dry_run:
        (outdir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        log.info("dry-run: no se publicó nada")
        return 0

    from .linkedin import LinkedIn

    li = LinkedIn(os.environ["LINKEDIN_ACCESS_TOKEN"], os.environ["LINKEDIN_PERSON_URN"])
    image_urn = None
    try:
        image_urn = li.upload_image(png.read_bytes())
    except Exception as e:  # sin imagen igual publicamos: mejor un post de texto que ninguno
        log.warning("no se pudo subir la imagen, publicando solo texto: %s", e)
    urn = li.post(text, hashtags, image_urn, alt=data.get("alt_text", ""))
    meta["urn"] = urn
    meta["url"] = LinkedIn.url_for(urn)
    if sources_in_comment:
        try:
            li.comment(urn, first_comment)  # requiere Community Management API; con la app básica da 403
        except Exception as e:
            log.info("no se pudo comentar por API (%s); queda para pegarlo a mano", e)
            (outdir / "comment.md").write_text(
                f"Post publicado: {meta['url']}\n\nPega esto como **primer comentario**:\n\n```text\n{first_comment}\n```\n\n"
                "Cierra este issue cuando lo hayas pegado.\n", encoding="utf-8")
            gh_output("comment_file", str(outdir / "comment.md"))
            gh_output("comment_date", day.isoformat())
    (outdir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    history.append({k: meta[k] for k in ("date", "title", "key", "cves", "links", "urn", "url")})
    state.save(history)
    gh_summary(f"\n✅ Publicado: {meta['url']}")
    print(f"\n✅ Publicado: {meta['url']}")
    return 0


def cmd_card_demo(_args) -> int:
    out = card.render({
        "kicker": "EXPLOTADA ACTIVAMENTE",
        "headline": "Un request sin autenticar y tienes shell en el firewall",
        "subject": "FortiWeb · CVE-2025-64446",
        "category": "exploit",
        "stats": [{"label": "CVSS", "value": "9.8"}, {"label": "EPSS", "value": "94%"}, {"label": "CISA KEV", "value": "SÍ"}],
    }, ROOT / "assets" / "example-card.png", edition=1, handle="github.com/IHATEFW")
    print(out)
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="zdm", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("candidates").set_defaults(fn=cmd_candidates)
    r = sub.add_parser("run")
    r.add_argument("--dry-run", action="store_true", help="genera todo pero no publica")
    r.add_argument("--scheduled", action="store_true", help="solo publica en la ventana del lunes 07:30 local")
    r.add_argument("--force", action="store_true", help="ignora la ventana horaria")
    r.set_defaults(fn=cmd_run)
    sub.add_parser("card-demo").set_defaults(fn=cmd_card_demo)
    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
