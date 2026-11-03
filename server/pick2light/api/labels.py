import asyncio
import io
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.api.attachments import Root
from pick2light.api.deps import DB
from pick2light.errors import NotFound, ValidationFailed
from pick2light.labels.pdf import SHEETS, SheetSpec, fit_error, labels_pdf
from pick2light.labels.render import render_label
from pick2light.labels.templates import (
    LAYOUT_ADAPTER,
    Element,
    item_context,
    location_context,
    unit_context,
)
from pick2light.models import LabelTemplate

router = APIRouter(tags=["labels"])

TargetType = Literal["item", "unit", "location"]
Target = Literal["item", "unit", "location", "command"]
MAX_IDS = 500
MAX_COPIES = 100
MAX_LABELS = 1000  # ids x copies, so one request cannot build an enormous PDF


class TemplateBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    width_mm: float = Field(gt=0, le=1000)
    height_mm: float = Field(gt=0, le=1000)
    dpi: int = Field(default=203, ge=72, le=1200)
    target: Target


class TemplateIn(TemplateBase):
    layout: list[Element] = Field(default_factory=list, max_length=200)


class TemplatePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    width_mm: float | None = Field(default=None, gt=0, le=1000)
    height_mm: float | None = Field(default=None, gt=0, le=1000)
    dpi: int | None = Field(default=None, ge=72, le=1200)
    target: Target | None = None
    layout: list[Element] | None = Field(default=None, max_length=200)


class TemplateOut(TemplateBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    layout: list[dict[str, Any]]


class PreviewIn(BaseModel):
    template_id: int
    target_type: TargetType
    id: int


class PdfIn(BaseModel):
    template_id: int
    target_type: TargetType
    ids: list[int] = Field(min_length=1, max_length=MAX_IDS)
    copies: int = Field(default=1, ge=1, le=MAX_COPIES)
    sheet_id: str | None = None
    start_position: int = Field(default=0, ge=0)


async def _get(db: AsyncSession, template_id: int) -> LabelTemplate:
    template = await db.get(LabelTemplate, template_id)
    if template is None:
        raise NotFound(f"Label template {template_id} not found")
    return template


def _dump_layout(layout: list[Any]) -> list[dict[str, Any]]:
    dumped: list[dict[str, Any]] = LAYOUT_ADAPTER.dump_python(layout, mode="json")
    return dumped


@router.get("/label-templates")
async def list_templates(db: DB) -> list[TemplateOut]:
    rows = await db.scalars(select(LabelTemplate).order_by(LabelTemplate.name, LabelTemplate.id))
    return [TemplateOut.model_validate(r) for r in rows]


@router.post("/label-templates", status_code=201)
async def create_template(data: TemplateIn, db: DB) -> TemplateOut:
    template = LabelTemplate(
        **data.model_dump(exclude={"layout"}), layout=_dump_layout(data.layout)
    )
    db.add(template)
    await db.flush()
    return TemplateOut.model_validate(template)


@router.get("/label-templates/{template_id}")
async def get_template(template_id: int, db: DB) -> TemplateOut:
    return TemplateOut.model_validate(await _get(db, template_id))


@router.patch("/label-templates/{template_id}")
async def update_template(template_id: int, data: TemplatePatch, db: DB) -> TemplateOut:
    template = await _get(db, template_id)
    changes = data.model_dump(exclude_unset=True, exclude={"layout"})
    for name, value in changes.items():
        if value is None:
            raise ValidationFailed({name: "cannot be null"})
        setattr(template, name, value)
    if data.layout is not None:
        template.layout = _dump_layout(data.layout)
    await db.flush()
    return TemplateOut.model_validate(template)


@router.delete("/label-templates/{template_id}", status_code=204)
async def delete_template(template_id: int, db: DB) -> Response:
    # Categories pointing at it fall back to "no default" (ON DELETE SET NULL).
    await db.delete(await _get(db, template_id))
    await db.flush()
    return Response(status_code=204)


@router.get("/label-sheets")
async def list_sheets() -> list[SheetSpec]:
    return list(SHEETS.values())


async def _context(
    db: AsyncSession, target: TargetType, target_id: int, root: Path
) -> dict[str, Any]:
    if target == "item":
        return await item_context(db, target_id, attachments_root=root)
    if target == "unit":
        return await unit_context(db, target_id, attachments_root=root)
    return await location_context(db, target_id, attachments_root=root)


def _check_target(template: LabelTemplate, target: TargetType) -> None:
    if template.target != target:
        raise ValidationFailed(
            {"target_type": f"Template '{template.name}' is for {template.target} labels"}
        )


def _render(template: LabelTemplate, ctx: dict[str, Any]) -> Any:
    try:
        return render_label(template, ctx)
    except ValueError as exc:
        raise ValidationFailed({"template": str(exc)}) from None


def _preview_png(template: LabelTemplate, ctx: dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    _render(template, ctx).save(buf, "PNG", dpi=(template.dpi, template.dpi))
    return buf.getvalue()


def _build_pdf(
    template: LabelTemplate,
    contexts: list[dict[str, Any]],
    copies: int,
    sheet: SheetSpec | None,
    start_position: int,
) -> bytes:
    images: list[Any] = []
    for ctx in contexts:
        images.extend([_render(template, ctx)] * copies)
    try:
        return labels_pdf(images, template, sheet, start_position)
    except ValueError as exc:
        raise ValidationFailed({"template": str(exc)}) from None


@router.post("/labels/preview")
async def preview(data: PreviewIn, db: DB, root: Root) -> Response:
    template = await _get(db, data.template_id)
    _check_target(template, data.target_type)
    ctx = await _context(db, data.target_type, data.id, root)
    png = await asyncio.to_thread(_preview_png, template, ctx)
    return Response(png, media_type="image/png")


@router.post("/labels/pdf")
async def pdf(data: PdfIn, db: DB, root: Root) -> Response:
    template = await _get(db, data.template_id)
    _check_target(template, data.target_type)
    sheet = None
    if data.sheet_id is not None:
        sheet = SHEETS.get(data.sheet_id)
        if sheet is None:
            raise ValidationFailed({"sheet_id": f"Unknown sheet '{data.sheet_id}'"})
        if data.start_position >= sheet.cells:
            raise ValidationFailed(
                {"start_position": f"Must be between 0 and {sheet.cells - 1} for this sheet"}
            )
        problem = fit_error(template, sheet)
        if problem:
            raise ValidationFailed({"sheet_id": problem})
    if len(data.ids) * data.copies > MAX_LABELS:
        raise ValidationFailed({"copies": f"At most {MAX_LABELS} labels per request"})

    # Database reads stay on the event loop; rendering and PDF building run in a thread.
    contexts = [await _context(db, data.target_type, i, root) for i in data.ids]
    body = await asyncio.to_thread(
        _build_pdf, template, contexts, data.copies, sheet, data.start_position
    )
    return Response(
        body,
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="labels.pdf"'},
    )
