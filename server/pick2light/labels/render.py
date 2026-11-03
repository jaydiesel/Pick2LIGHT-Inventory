"""Draw a label template onto a grayscale Pillow image at the template's DPI."""

from functools import lru_cache
from pathlib import Path
from typing import Any

import barcode
import barcode.errors
import segno
from PIL import Image, ImageDraw, ImageFont, ImageOps
from pylibdmtx import pylibdmtx

from pick2light.labels.templates import (
    LAYOUT_ADAPTER,
    BarcodeEl,
    BoxEl,
    ImageEl,
    LineEl,
    TextEl,
    resolve,
)
from pick2light.models import LabelTemplate

FONT_DIR = Path(__file__).parent / "fonts"
MIN_FONT_PT = 6.0
FONT_STEP_PT = 0.5
ELLIPSIS = "…"
BLACK, WHITE = 0, 255
DMTX_MODULE_PX = 5  # pylibdmtx draws every module as 5x5 pixels


def _px(mm: float, dpi: int) -> int:
    return round(mm * dpi / 25.4)


@lru_cache(maxsize=64)
def _font(bold: bool, px: float) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(str(FONT_DIR / name), px)


# --------------------------------------------------------------------------- text


def _width(font: ImageFont.FreeTypeFont, text: str) -> float:
    return font.getlength(text)


def _split_word(font: ImageFont.FreeTypeFont, word: str, max_w: float) -> list[str]:
    """Break a word wider than `max_w` into pieces that each fit."""
    pieces, current = [], ""
    for char in word:
        if current and _width(font, current + char) > max_w:
            pieces.append(current)
            current = char
        else:
            current += char
    return [*pieces, current] if current else pieces


def _wrap(font: ImageFont.FreeTypeFont, text: str, max_w: float) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        current = ""
        for word in paragraph.split():
            candidate = f"{current} {word}" if current else word
            if _width(font, candidate) <= max_w:
                current = candidate
                continue
            if current:
                lines.append(current)
            *whole, current = _split_word(font, word, max_w)
            lines.extend(whole)
        lines.append(current)
    return lines


def _ellipsize(font: ImageFont.FreeTypeFont, line: str, max_w: float) -> str:
    line = line.rstrip()
    while line and _width(font, line + ELLIPSIS) > max_w:
        line = line[:-1].rstrip()
    return line + ELLIPSIS


def _fit_text(el: TextEl, text: str, dpi: int) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Largest font (down to 6 pt) whose wrapped text fits w x h in `max_lines`; else clip."""
    max_w, max_h = _px(el.w, dpi), _px(el.h, dpi)
    size = el.font_size
    while True:
        font = _font(el.bold, max(size, 1) * dpi / 72)
        ascent, descent = font.getmetrics()
        line_h = ascent + descent
        lines = _wrap(font, text, max_w)
        if len(lines) <= el.max_lines and len(lines) * line_h <= max_h:
            return font, lines
        if size <= MIN_FONT_PT:
            break
        size = max(MIN_FONT_PT, size - FONT_STEP_PT)
    room = max(1, min(el.max_lines, max_h // line_h))
    shown = lines[:room]
    if len(lines) > room or _width(font, shown[-1]) > max_w:
        shown[-1] = _ellipsize(font, shown[-1], max_w)
    return font, shown


def _draw_text(img: Image.Image, el: TextEl, ctx: dict[str, Any], dpi: int) -> None:
    text = resolve(el.value, ctx).strip()
    if not text:
        return
    font, lines = _fit_text(el, text, dpi)
    ascent, descent = font.getmetrics()
    draw = ImageDraw.Draw(img)
    x0, y = _px(el.x, dpi), _px(el.y, dpi)
    box_w = _px(el.w, dpi)
    for line in lines:
        width = _width(font, line)
        offset = {"left": 0, "center": (box_w - width) / 2, "right": box_w - width}[el.align]
        draw.text((x0 + offset, y), line, font=font, fill=BLACK)
        y += ascent + descent


# --------------------------------------------------------------------------- barcodes


def _modules_to_image(rows: list[bytes | bytearray], box_px: int) -> Image.Image:
    """Dark modules (truthy) of a square matrix, scaled by a whole factor to fit `box_px`."""
    n = len(rows)
    flat = bytes(BLACK if v else WHITE for row in rows for v in row)
    small = Image.frombytes("L", (n, n), flat)
    scale = max(1, box_px // n)
    out = small.resize((n * scale, n * scale), Image.Resampling.NEAREST)
    if out.width > box_px:  # box smaller than the symbol: degrade rather than overflow
        out = out.resize((box_px, box_px), Image.Resampling.NEAREST)
    return out


def _qr(value: str, box_px: int) -> Image.Image:
    code = segno.make(value, error="m", micro=False)
    return _modules_to_image([bytearray(row) for row in code.matrix], box_px)


def _datamatrix(value: str, box_px: int) -> Image.Image:
    encoded = pylibdmtx.encode(value.encode("utf-8"))
    image = Image.frombytes("RGB", (encoded.width, encoded.height), encoded.pixels).convert("L")
    bbox = image.point(lambda p: 255 if p < 128 else 0).getbbox()
    if bbox is None:
        raise ValueError("Data Matrix encoding produced an empty symbol")
    symbol = image.crop(bbox)
    n = max(1, round(symbol.width / DMTX_MODULE_PX))
    modules = symbol.resize((n, n), Image.Resampling.NEAREST)
    pixels = modules.tobytes()
    return _modules_to_image(
        [bytes(1 if pixels[r * n + c] < 128 else 0 for c in range(n)) for r in range(n)], box_px
    )


def _bars(value: str, symbology: str, width_px: int, height_px: int) -> Image.Image:
    try:
        cls = barcode.get_barcode_class(symbology)
        pattern = cls(value).build()[0]
    except (barcode.errors.BarcodeError, ValueError) as exc:
        raise ValueError(f"Cannot encode {value!r} as {symbology}: {exc}") from exc
    n = len(pattern)
    scale = max(1, width_px // n)
    strip = Image.frombytes("L", (n, 1), bytes(BLACK if c == "1" else WHITE for c in pattern))
    out = strip.resize((n * scale, max(1, height_px)), Image.Resampling.NEAREST)
    if out.width > width_px:
        out = out.resize((max(1, width_px), out.height), Image.Resampling.NEAREST)
    return out


def _draw_barcode(
    img: Image.Image,
    el: BarcodeEl,
    ctx: dict[str, Any],
    dpi: int,
    width_mm: float,
    height_mm: float,
) -> None:
    value = resolve(el.value, ctx).strip()
    if not value:
        return
    x, y = _px(el.x, dpi), _px(el.y, dpi)
    if el.symbology in ("qr", "datamatrix"):
        size = el.size or min(el.width or 1e9, el.height or 1e9, width_mm - el.x, height_mm - el.y)
        box = max(1, _px(size, dpi))
        code = _qr(value, box) if el.symbology == "qr" else _datamatrix(value, box)
        img.paste(code, (x + (box - code.width) // 2, y + (box - code.height) // 2))
        return
    width = _px(el.width or (width_mm - el.x), dpi)
    height = _px(el.height or (height_mm - el.y), dpi)
    code = _bars(value, el.symbology, width, height)
    img.paste(code, (x + (width - code.width) // 2, y))


# --------------------------------------------------------------------------- other elements


def _draw_image(img: Image.Image, el: ImageEl, ctx: dict[str, Any], dpi: int) -> None:
    photo = (ctx.get("_images") or {}).get(el.source)
    if photo is None:
        return
    w, h = max(1, _px(el.w, dpi)), max(1, _px(el.h, dpi))
    fitted = ImageOps.contain(photo.convert("L"), (w, h), Image.Resampling.LANCZOS)
    img.paste(
        fitted,
        (_px(el.x, dpi) + (w - fitted.width) // 2, _px(el.y, dpi) + (h - fitted.height) // 2),
    )


def _draw_shape(img: Image.Image, el: LineEl | BoxEl, dpi: int) -> None:
    draw = ImageDraw.Draw(img)
    x0, y0 = _px(el.x, dpi), _px(el.y, dpi)
    x1, y1 = _px(el.x + el.w, dpi), _px(el.y + el.h, dpi)
    thickness = max(1, _px(el.thickness, dpi))
    if isinstance(el, LineEl):
        draw.line((x0, y0, x1, y1), fill=BLACK, width=thickness)
    else:
        draw.rectangle((x0, y0, x1, y1), outline=BLACK, width=thickness)


def render_label(template: LabelTemplate, ctx: dict[str, Any]) -> Image.Image:
    """Render to a white 8-bit grayscale image of the template's size at its DPI.

    Raises ValueError when a barcode value cannot be encoded in its symbology.
    """
    dpi = template.dpi
    img = Image.new("L", (_px(template.width_mm, dpi), _px(template.height_mm, dpi)), WHITE)
    for el in LAYOUT_ADAPTER.validate_python(template.layout):
        if isinstance(el, BarcodeEl):
            _draw_barcode(img, el, ctx, dpi, template.width_mm, template.height_mm)
        elif isinstance(el, TextEl):
            _draw_text(img, el, ctx, dpi)
        elif isinstance(el, ImageEl):
            _draw_image(img, el, ctx, dpi)
        else:
            _draw_shape(img, el, dpi)
    return img
