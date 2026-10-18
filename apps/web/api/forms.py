"""Local inbox for validated public form submissions."""

from fastapi import APIRouter, Depends, Query
from tortoise import fields
from tortoise.models import Model

from .permissions import require_permission


router = APIRouter()


class FormSubmission(Model):
    id = fields.IntField(primary_key=True)
    form_name = fields.CharField(max_length=64)
    payload = fields.JSONField()
    created_at = fields.DatetimeField(auto_now_add=True)


async def save_submission(form_name: str, payload: dict[str, str]) -> None:
    """Persist first; a future delivery service can run after this succeeds."""
    await FormSubmission.create(form_name=form_name, payload=payload)


@router.get(
    "/api/forms/{form_name}/submissions",
    dependencies=[Depends(require_permission("inbox"))],
)
async def list_submissions(
    form_name: str,
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return await (
        FormSubmission.filter(form_name=form_name)
        .order_by("-id")
        .offset(offset)
        .limit(limit)
        .values("id", "form_name", "payload", "created_at")
    )
