"""Genera la imagen del post: una tarjeta tipográfica 1080x1350 (formato vertical, el que más ocupa el feed).

Sin IA generativa: texto nítido, legible en el celular y con los datos duros a la vista.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
W, H = 1080, 1350
PAD = 84
BG = (9, 12, 17)
FG = (240, 242, 245)
MUTED = (125, 135, 150)
GRID = (22, 28, 36)
# Color por tipo de noticia: el feed se ve variado y el color anticipa el tema.
ACCENT = {
    "exploit": (255, 59, 70),        # 0-days, RCE, bypass, vulnerabilidades explotadas
    "ai": (168, 85, 247),            # IA ofensiva, ataques a LLMs y agentes
    "breach": (245, 166, 35),        # brechas y filtraciones de datos
    "supply_chain": (34, 211, 138),  # paquetes troyanizados, CI/CD comprometido
}
MESES = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"]


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt, width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        test = f"{line} {word}".strip()
        if draw.textlength(test, font=fnt) <= width:
            line = test
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def fit_headline(draw, text: str, width: int, max_h: int) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    for size in range(96, 47, -4):
        fnt = font("Inter-ExtraBold.ttf", size)
        lines = wrap(draw, text, fnt, width)
        lh = int(size * 1.12)
        if len(lines) * lh <= max_h and len(lines) <= 5:
            return fnt, lines, lh
    fnt = font("Inter-ExtraBold.ttf", 48)
    return fnt, wrap(draw, text, fnt, width)[:6], 54


def render(card: dict, out: Path, edition: int | None = None, day: date | None = None,
           series: str = "ZERO-DAY MONDAY", handle: str = "") -> Path:
    day = day or date.today()
    accent = ACCENT.get(card.get("category", "exploit"), ACCENT["exploit"])

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # Fondo: grilla de puntos + resplandor del color de severidad.
    for x in range(0, W, 36):
        for y in range(0, H, 36):
            d.point((x, y), fill=GRID)
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    ImageDraw.Draw(glow).ellipse((W - 520, -380, W + 380, 420), fill=tuple(int(c * 0.55) for c in accent))
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    img = ImageChops.lighter(img, glow)
    d = ImageDraw.Draw(img)

    mono = font("JetBrainsMono-Bold.ttf", 30)
    mono_r = font("JetBrainsMono-Regular.ttf", 28)

    # Barra superior.
    y = PAD
    d.rectangle((PAD, y + 4, PAD + 10, y + 34), fill=accent)
    d.text((PAD + 28, y), series, font=mono, fill=FG)
    right = f"{day.day:02d} {MESES[day.month - 1]} {day.year}" + (f"  ·  #{edition:02d}" if edition else "")
    d.text((W - PAD - d.textlength(right, font=mono_r), y + 2), right, font=mono_r, fill=MUTED)

    # Kicker (píldora).
    y += 130
    kicker = card.get("kicker", "").upper()[:26]
    kf = font("JetBrainsMono-Bold.ttf", 32)
    kw = d.textlength(kicker, font=kf)
    d.rounded_rectangle((PAD, y, PAD + kw + 44, y + 62), radius=10, fill=accent)
    d.text((PAD + 22, y + 11), kicker, font=kf, fill=BG)

    # Titular.
    y += 110
    stats = card.get("stats", [])[:3]
    stats_top = H - PAD - 120 - 210
    # Espacio del titular = hasta los stats (o el pie), dejando lugar para la línea del sujeto.
    max_h = (stats_top if stats else H - PAD - 160) - y - 130
    hf, lines, lh = fit_headline(d, card.get("headline", ""), W - 2 * PAD, max_h)
    for line in lines:
        d.text((PAD, y), line, font=hf, fill=FG)
        y += lh

    # Sujeto (producto / CVE) estilo prompt.
    y += 34
    sf = font("JetBrainsMono-Bold.ttf", 36)
    d.text((PAD, y), ">", font=sf, fill=accent)
    d.text((PAD + 40, y), card.get("subject", "")[:44], font=sf, fill=FG)

    # Stats.
    if stats:
        top = stats_top
        gap = 24
        bw = (W - 2 * PAD - gap * (len(stats) - 1)) // len(stats)
        vf_size = 76 if len(stats) < 3 else 64
        for i, s in enumerate(stats):
            x0 = PAD + i * (bw + gap)
            d.rounded_rectangle((x0, top, x0 + bw, top + 190), radius=18, outline=(44, 52, 64), width=2, fill=(14, 18, 25))
            d.rectangle((x0, top + 24, x0 + 5, top + 166), fill=accent)
            value = str(s.get("value", ""))[:10]
            vf = font("Inter-ExtraBold.ttf", vf_size)
            while d.textlength(value, font=vf) > bw - 56 and vf.size > 34:
                vf = font("Inter-ExtraBold.ttf", vf.size - 4)
            d.text((x0 + 32, top + 28), value, font=vf, fill=FG)
            lf = font("JetBrainsMono-Regular.ttf", 24)
            label = str(s.get("label", "")).upper()[:22]
            d.text((x0 + 32, top + 190 - 52), label, font=lf, fill=MUTED)

    # Pie.
    fy = H - PAD - 34
    d.line((PAD, fy - 34, W - PAD, fy - 34), fill=(36, 42, 52), width=2)
    d.text((PAD, fy), "$ patch --now", font=mono_r, fill=accent)
    if handle:
        d.text((W - PAD - d.textlength(handle, font=mono_r), fy), handle, font=mono_r, fill=MUTED)

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)
    return out
