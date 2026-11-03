import io
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from pick2light.api.deps import DB
from pick2light.errors import Conflict, NotFound, ValidationFailed
from pick2light.labels.pdf import SHEETS, SheetSpec, get_sheet, labels_pdf
from pick2light.labels.render import render_label
from pick2light.labels.templates import LabelTemplateIn, LabelTemplateOut, LabelTemplatePatch, context_for
from pick2light.models import Attachment, LabelTemplate

router = APIRouter(tags=["labels"])
MAX_LABELS = 500


class PreviewIn(BaseModel):
    template_id: int
    target_type: Literal["item", "unit", "location"]
    id: int


class PdfIn(BaseModel):
    template_id: int
    target_type: Literal["item", "unit", "location"]
    ids: list[int] = Field(min_length=1)
    copies: int = Field(default=1, ge=1, le=100)
    sheet_id: str | None = None
    start_position: int = Field(default=0, ge=0)


async def _template(db, template_id: int) -> LabelTemplate:
    t = await db.get(LabelTemplate, template_id)
    if t is None:
        raise NotFound(f"Label template {template_id} not found")
    return t


def _check_target(template: LabelTemplate, target_type: str) -> None:
    if template.target != target_type:
        raise ValidationFailed({"target_type": f"'{template.name}' is a {template.target} label"})


async def _photo(db, request: Request, ctx: dict):
    att_id = ctx.get("_photo_attachment_id")
    if not att_id:
        return None
    att = await db.get(Attachment, att_id)
    if att is None or not att.storage_path:
        return None
    return request.app.state.settings.attachments_dir / att.storage_path


async def _name_taken(db, name: str, exclude: int | None = None) -> bool:
    q = select(LabelTemplate.id).where(LabelTemplate.name == name)
    if exclude is not None:
        q = q.where(LabelTemplate.id != exclude)
    return await db.scalar(q) is not None


@router.get("/label-templates")
async def list_templates(db: DB) -> list[LabelTemplateOut]:
    rows = await db.scalars(select(LabelTemplate).order_by(LabelTemplate.target, LabelTemplate.name))
    return [LabelTemplateOut.model_validate(t) for t in rows]


@router.post("/label-templates", status_code=201)
async def create_template(data: LabelTemplateIn, db: DB) -> LabelTemplateOut:
    if await _name_taken(db, data.name):
        raise Conflict(f"A template called '{data.name}' already exists")
    t = LabelTemplate(**data.model_dump(exclude={"layout"}), layout=[el.model_dump() for el in data.layout])
    db.add(t)
    await db.flush()
    return LabelTemplateOut.model_validate(t)


@router.get("/label-templates/{template_id}")
async def get_template(template_id: int, db: DB) -> LabelTemplateOut:
    return LabelTemplateOut.model_validate(await _template(db, template_id))


@router.patch("/label-templates/{template_id}")
async def update_template(template_id: int, data: LabelTemplatePatch, db: DB) -> LabelTemplateOut:
    t = await _template(db, template_id)
    if data.name is not None and data.name != t.name:
        if await _name_taken(db, data.name, exclude=t.id):
            raise Conflict(f"A template called '{data.name}' already exists")
        t.name = data.name
    for attr in ("width_mm", "height_mm", "dpi"):
        if getattr(data, attr) is not None:
            setattr(t, attr, getattr(data, attr))
    if data.layout is not None:
        t.layout = [el.model_dump() for el in data.layout]
    await db.flush()
    return LabelTemplateOut.model_validate(t)


@router.delete("/label-templates/{template_id}", status_code=204)
async def delete_template(template_id: int, db: DB) -> Response:
    await db.delete(await _template(db, template_id))
    await db.flush()
    return Response(status_code=204)


@router.get("/label-sheets")
async def sheets() -> list[SheetSpec]:
    return SHEETS


@router.post("/labels/preview", response_class=Response, responses={200: {"content": {"image/png": {}}}})
async def preview(data: PreviewIn, request: Request, db: DB) -> Response:
    t = await _template(db, data.template_id)
    _check_target(t, data.target_type)
    ctx = await context_for(db, data.target_type, data.id)
    img = render_label(t, ctx, await _photo(db, request, ctx))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png")


@router.post("/labels/pdf", response_class=Response, responses={200: {"content": {"application/pdf": {}}}})
async def pdf(data: PdfIn, request: Request, db: DB) -> Response:
    t = await _template(db, data.template_id)
    _check_target(t, data.target_type)
    if len(data.ids) * data.copies > MAX_LABELS:
        raise ValidationFailed({"ids": f"At most {MAX_LABELS} labels per PDF"})
    sheet = None
    if data.sheet_id:
        sheet = get_sheet(data.sheet_id)
        if sheet is None:
            raise ValidationFailed({"sheet_id": "Unknown sheet"})
    images = []
    for target_id in data.ids:
        ctx = await context_for(db, data.target_type, target_id)
        img = render_label(t, ctx, await _photo(db, request, ctx))
        images.extend([img] * data.copies)
    body = labels_pdf(images, t, sheet, data.start_position)
    return Response(
        body, media_type="application/pdf", headers={"Content-Disposition": 'inline; filename="labels.pdf"'}
    )
