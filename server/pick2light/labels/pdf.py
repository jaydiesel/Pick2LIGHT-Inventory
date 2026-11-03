"""PDF output: one page per label, or labels placed on A4/Letter sticker sheets (spec §8.2)."""

import io
import math

from PIL import Image
from pydantic import BaseModel

from pick2light.labels.render import mm_to_px
from pick2light.models import LabelTemplate


class SheetSpec(BaseModel):
    id: str
    name: str
    page_w_mm: float
    page_h_mm: float
    cols: int
    rows: int
    label_w_mm: float
    label_h_mm: float
    margin_left_mm: float
    margin_top_mm: float
    gap_x_mm: float
    gap_y_mm: float


SHEETS = [
    SheetSpec(
        id="a4-3x8",
        name="A4 3×8 (70×37 mm)",
        page_w_mm=210,
        page_h_mm=297,
        cols=3,
        rows=8,
        label_w_mm=70,
        label_h_mm=37,
        margin_left_mm=0,
        margin_top_mm=0.5,
        gap_x_mm=0,
        gap_y_mm=0,
    ),
    SheetSpec(
        id="letter-3x10",
        name="Letter 3×10 (66.7×25.4 mm)",
        page_w_mm=215.9,
        page_h_mm=279.4,
        cols=3,
        rows=10,
        label_w_mm=66.7,
        label_h_mm=25.4,
        margin_left_mm=4.8,
        margin_top_mm=12.7,
        gap_x_mm=3.2,
        gap_y_mm=0,
    ),
]


def get_sheet(sheet_id: str) -> SheetSpec | None:
    return next((s for s in SHEETS if s.id == sheet_id), None)


def labels_pdf(
    images: list[Image.Image], template: LabelTemplate, sheet: SheetSpec | None, start_position: int = 0
) -> bytes:
    dpi = template.dpi or 203
    pages: list[Image.Image]
    if sheet is None:
        pages = [img.convert("L") for img in images] or [
            Image.new("L", (mm_to_px(template.width_mm, dpi), mm_to_px(template.height_mm, dpi)), 255)
        ]
    else:
        per_page = sheet.cols * sheet.rows
        start = max(0, start_position) % per_page
        count = max(1, math.ceil((start + len(images)) / per_page))
        pages = [
            Image.new("L", (mm_to_px(sheet.page_w_mm, dpi), mm_to_px(sheet.page_h_mm, dpi)), 255)
            for _ in range(count)
        ]
        for i, img in enumerate(images):
            slot = start + i
            page, cell = divmod(slot, per_page)
            row, col = divmod(cell, sheet.cols)
            cell_x = sheet.margin_left_mm + col * (sheet.label_w_mm + sheet.gap_x_mm)
            cell_y = sheet.margin_top_mm + row * (sheet.label_h_mm + sheet.gap_y_mm)
            x = mm_to_px(cell_x, dpi) + (mm_to_px(sheet.label_w_mm, dpi) - img.width) // 2
            y = mm_to_px(cell_y, dpi) + (mm_to_px(sheet.label_h_mm, dpi) - img.height) // 2
            pages[page].paste(img.convert("L"), (max(x, 0), max(y, 0)))
    buf = io.BytesIO()
    pages[0].save(buf, "PDF", save_all=True, append_images=pages[1:], resolution=dpi)
    return buf.getvalue()
