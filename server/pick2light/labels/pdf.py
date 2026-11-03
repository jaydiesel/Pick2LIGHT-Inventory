"""PDF output: one page per label, or labels placed into the cells of a sheet.

Pages are built with img2pdf, which embeds the grayscale PNG losslessly. (Pillow's own PDF
writer would re-encode 8-bit images as JPEG, which smears barcode edges.)
"""

import io

import img2pdf
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


def _png(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.convert("L").save(buf, "PNG")
    return buf.getvalue()


def _convert(pages: list[bytes], first: Image.Image, width_mm: float, height_mm: float) -> bytes:
    """Assemble pages whose pixels span exactly width_mm x height_mm (same size for all)."""
    dpi = (first.width / (width_mm / MM_PER_INCH), first.height / (height_mm / MM_PER_INCH))
    result: bytes = img2pdf.convert(pages, layout_fun=img2pdf.get_fixed_dpi_layout_fun(dpi))
    return result


def labels_pdf(
    images: list[Image.Image],
    template: LabelTemplate,
    sheet: SheetSpec | None,
    start_position: int = 0,
) -> bytes:
    """PDF bytes. Without a sheet each label is a page of the label's own size; with one,
    labels fill the sheet's cells in reading order (centred, clipped to the cell), starting
    at cell `start_position` of the first page. Raises ValueError on bad input."""
    if not images:
        raise ValueError("No labels to print")
    if sheet is None:
        return _convert([_png(i) for i in images], images[0], template.width_mm, template.height_mm)
    if not 0 <= start_position < sheet.cells:
        raise ValueError(f"start_position must be between 0 and {sheet.cells - 1}")

    dpi = template.dpi

    def to_px(mm: float) -> int:
        return round(mm * dpi / MM_PER_INCH)

    page_size = (to_px(sheet.page_w_mm), to_px(sheet.page_h_mm))
    cell_size = (to_px(sheet.label_w_mm), to_px(sheet.label_h_mm))
    pages: dict[int, Image.Image] = {}
    for offset, label in enumerate(images):
        page_no, cell = divmod(start_position + offset, sheet.cells)
        row, col = divmod(cell, sheet.cols)
        page = pages.setdefault(page_no, Image.new("L", page_size, 255))
        holder = Image.new("L", cell_size, 255)
        holder.paste(label, ((cell_size[0] - label.width) // 2, (cell_size[1] - label.height) // 2))
        page.paste(
            holder,
            (
                to_px(sheet.margin_left_mm + col * (sheet.label_w_mm + sheet.gap_x_mm)),
                to_px(sheet.margin_top_mm + row * (sheet.label_h_mm + sheet.gap_y_mm)),
            ),
        )
    ordered = [pages[n] for n in sorted(pages)]
    return _convert([_png(p) for p in ordered], ordered[0], sheet.page_w_mm, sheet.page_h_mm)
