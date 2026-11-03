"""Render a label template to a Pillow image (spec §8.2)."""

from pathlib import Path

import barcode
import segno
from barcode.writer import ImageWriter
from PIL import Image, ImageDraw, ImageFont
from pylibdmtx import pylibdmtx as dmtx

from pick2light.labels.templates import BarcodeEl, BoxEl, ImageEl, LineEl, TextEl, parse_layout, resolve
from pick2light.models import LabelTemplate

FONT_DIR = Path(__file__).resolve().parent / "fonts"
MIN_PT = 6.0


def mm_to_px(mm: float, dpi: int) -> int:
    return round(mm / 25.4 * dpi)


def _font(px: int, bold: bool) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(str(FONT_DIR / name), max(px, 1))


def _matrix_image(rows: list[list[int]], size_px: int, border: int = 1) -> Image.Image:
    n = len(rows) + 2 * border
    img = Image.new("L", (n, n), 255)
    for y, row in enumerate(rows):
        for x, dark in enumerate(row):
            if dark:
                img.putpixel((x + border, y + border), 0)
    return img.resize((size_px, size_px), Image.Resampling.NEAREST)


def _barcode(el: BarcodeEl, value: str, dpi: int) -> Image.Image | None:
    if not value:
        return None
    if el.symbology == "qr":
        qr = segno.make(value, error="m")
        size = mm_to_px(el.size or min(el.width or 20, el.height or 20), dpi)
        return _matrix_image([list(r) for r in qr.matrix], size)
    if el.symbology == "datamatrix":
        enc = dmtx.encode(value.encode("utf-8"))
        img = Image.frombytes("RGB", (enc.width, enc.height), enc.pixels).convert("L")
        size = mm_to_px(el.size or min(el.width or 12, el.height or 12), dpi)
        return img.resize((size, size), Image.Resampling.NEAREST)
    symbology = "ean13" if el.symbology == "ean13" else "code128"
    code = barcode.get(symbology, value, writer=ImageWriter())
    img = code.render({"write_text": False, "quiet_zone": 1, "module_height": 10, "dpi": dpi}).convert("L")
    w = mm_to_px(el.width or el.size or 40, dpi)
    h = mm_to_px(el.height or (el.size or 10), dpi)
    return img.resize((w, h), Image.Resampling.NEAREST)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words, line = paragraph.split(), ""
        for word in words:
            candidate = f"{line} {word}".strip()
            if draw.textlength(candidate, font=font) <= width or not line:
                line = candidate
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def _ellipsize(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> str:
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text + "…"


def _text(draw: ImageDraw.ImageDraw, el: TextEl, value: str, dpi: int) -> None:
    if not value:
        return
    x, y, w, h = (mm_to_px(v, dpi) for v in (el.x, el.y, el.w, el.h))
    pt = el.font_size
    while True:
        font = _font(round(pt / 72 * dpi), el.bold)
        line_h = font.getbbox("Ag")[3] + max(1, round(pt / 72 * dpi * 0.15))
        lines = _wrap(draw, value, font, w)
        fits_lines = len(lines) <= el.max_lines and line_h * len(lines) <= h
        fits_width = all(draw.textlength(line, font=font) <= w for line in lines)
        if (fits_lines and fits_width) or pt <= MIN_PT:
            break
        pt = max(MIN_PT, pt - 0.5)
    max_lines = int(max(1, min(el.max_lines, h // max(line_h, 1))))
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1] + "…"
    lines = [_ellipsize(draw, line, font, w) for line in lines]
    for i, line in enumerate(lines):
        lw = draw.textlength(line, font=font)
        dx = {"left": 0, "center": (w - lw) / 2, "right": w - lw}[el.align]
        draw.text((x + dx, y + i * line_h), line, fill=0, font=font)


def render_label(template: LabelTemplate, ctx: dict, photo_path: Path | None = None) -> Image.Image:
    dpi = template.dpi or 203
    img = Image.new("L", (mm_to_px(template.width_mm, dpi), mm_to_px(template.height_mm, dpi)), 255)
    draw = ImageDraw.Draw(img)
    for el in parse_layout(template.layout or []):
        if isinstance(el, BarcodeEl):
            code = _barcode(el, resolve(el.value, ctx).strip(), dpi)
            if code is not None:
                img.paste(code, (mm_to_px(el.x, dpi), mm_to_px(el.y, dpi)))
        elif isinstance(el, TextEl):
            _text(draw, el, resolve(el.value, ctx).strip(), dpi)
        elif isinstance(el, ImageEl):
            if photo_path is not None and photo_path.exists():
                with Image.open(photo_path) as photo:
                    thumb = photo.convert("L")
                    thumb.thumbnail((mm_to_px(el.w, dpi), mm_to_px(el.h, dpi)))
                    img.paste(thumb, (mm_to_px(el.x, dpi), mm_to_px(el.y, dpi)))
        elif isinstance(el, LineEl):
            x, y = mm_to_px(el.x, dpi), mm_to_px(el.y, dpi)
            draw.line(
                [(x, y), (x + mm_to_px(el.w, dpi), y + mm_to_px(el.h, dpi))],
                fill=0,
                width=max(1, mm_to_px(el.thickness, dpi)),
            )
        elif isinstance(el, BoxEl):
            x, y = mm_to_px(el.x, dpi), mm_to_px(el.y, dpi)
            draw.rectangle(
                [(x, y), (x + mm_to_px(el.w, dpi), y + mm_to_px(el.h, dpi))],
                outline=0,
                width=max(1, mm_to_px(el.thickness, dpi)),
            )
    return img
