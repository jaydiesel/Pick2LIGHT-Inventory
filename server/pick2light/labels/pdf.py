"""PDF output: one page per label, or labels placed into the cells of a sheet.

Pillow's PDF writer stores 8-bit images as JPEG, which smears barcode edges, so pages are
converted to 1-bit first (thresholded, no dithering); those are written as lossless CCITT.
"""

import io

from PIL import Image
from pydantic import BaseModel

from pick2light.models import LabelTemplate

MM_PER_INCH = 25.4


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

    @property
    def cells(self) -> int:
        return self.cols * self.rows


SHEETS: dict[str, SheetSpec] = {
    s.id: s
    for s in (
        SheetSpec(
            id="a4-3x8",
            name="A4, 3 x 8 (70 x 37 mm)",
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
            name="Letter, 3 x 10 (66.7 x 25.4 mm)",
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
    )
}


def _one_bit(image: Image.Image) -> Image.Image:
    """Hard threshold, no dithering; Pillow writes mode "1" as lossless CCITT G4."""
    return image.convert("L").point(lambda p: 255 if p >= 128 else 0, mode="1")


def _save(pages: list[Image.Image], width_mm: float, height_mm: float) -> bytes:
    """Multi-page PDF whose pages span exactly width_mm x height_mm (same size for all)."""
    first = pages[0]
    resolution = first.width / (width_mm / MM_PER_INCH)
    buf = io.BytesIO()
    first.save(buf, "PDF", save_all=True, append_images=pages[1:], resolution=resolution)
    return buf.getvalue()


def _px(mm: float, dpi: int) -> int:
    return round(mm * dpi / MM_PER_INCH)


def fit_error(template: LabelTemplate, sheet: SheetSpec) -> str | None:
    """Message when the label is bigger than a sheet cell (1 px of slack), else None."""
    dpi = template.dpi
    if (
        _px(template.width_mm, dpi) > _px(sheet.label_w_mm, dpi) + 1
        or _px(template.height_mm, dpi) > _px(sheet.label_h_mm, dpi) + 1
    ):
        return (
            f"Label ({template.width_mm:g}×{template.height_mm:g} mm) is larger than "
            f"this sheet's cells ({sheet.label_w_mm:g}×{sheet.label_h_mm:g} mm)"
        )
    return None


def labels_pdf(
    images: list[Image.Image],
    template: LabelTemplate,
    sheet: SheetSpec | None,
    start_position: int = 0,
) -> bytes:
    """PDF bytes. Without a sheet each label is a page of the label's own size; with one,
    labels fill the sheet's cells in reading order (centred), starting at cell
    `start_position` of the first page. Pages are 1-bit. Raises ValueError on bad input,
    including a label larger than a cell (it is never scaled or clipped)."""
    if not images:
        raise ValueError("No labels to print")
    converted: dict[int, Image.Image] = {}  # copies share one image object

    def bits(image: Image.Image) -> Image.Image:
        return converted.setdefault(id(image), _one_bit(image))

    if sheet is None:
        return _save([bits(i) for i in images], template.width_mm, template.height_mm)
    problem = fit_error(template, sheet)
    if problem:
        raise ValueError(problem)
    if not 0 <= start_position < sheet.cells:
        raise ValueError(f"start_position must be between 0 and {sheet.cells - 1}")

    dpi = template.dpi
    page_size = (_px(sheet.page_w_mm, dpi), _px(sheet.page_h_mm, dpi))
    cell_w, cell_h = _px(sheet.label_w_mm, dpi), _px(sheet.label_h_mm, dpi)
    pages: dict[int, Image.Image] = {}
    for offset, label in enumerate(images):
        page_no, cell = divmod(start_position + offset, sheet.cells)
        row, col = divmod(cell, sheet.cols)
        page = pages.setdefault(page_no, Image.new("1", page_size, 1))
        one = bits(label)
        x = _px(sheet.margin_left_mm + col * (sheet.label_w_mm + sheet.gap_x_mm), dpi)
        y = _px(sheet.margin_top_mm + row * (sheet.label_h_mm + sheet.gap_y_mm), dpi)
        page.paste(one, (x + (cell_w - one.width) // 2, y + (cell_h - one.height) // 2))
    return _save([pages[n] for n in sorted(pages)], sheet.page_w_mm, sheet.page_h_mm)
