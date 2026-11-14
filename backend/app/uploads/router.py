from typing import Annotated
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.db import get_catalog_db
from app.models.auth import AppUser
from app.models.uploads import UploadPart
from app.uploads.schemas import Sha256, UploadComplete, UploadCreate
from app.uploads.service import (
    ACTIVE_STATUSES,
    abort_upload,
    complete_upload,
    create_upload,
    get_upload,
    now,
    put_part,
)

router = APIRouter(prefix="/api/v1", tags=["uploads"])


@router.post("/uploads", status_code=201)
async def create(
    data: UploadCreate, request: Request, user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_catalog_db),
):
    actor_id = user.id
    await anyio.to_thread.run_sync(db.commit)
    return await create_upload(data, actor_id, request.app.state.policy_manager)


@router.get("/uploads/{id}")
def status(
    id: UUID, user: AppUser = Depends(get_current_user), db: Session = Depends(get_catalog_db),
):
    upload = get_upload(db, id, user.id)
    parts = db.scalars(select(UploadPart.part_number).where(
        UploadPart.upload_id == id
    ).order_by(UploadPart.part_number)).all()
    expired = upload.status in ACTIVE_STATUSES and upload.expires_at <= now()
    return {
        "status": "EXPIRED" if expired else upload.status,
        "receivedParts": parts, "totalParts": upload.total_parts,
    }


@router.put("/uploads/{id}/parts/{part_number}")
async def part(
    id: UUID, part_number: int, request: Request,
    x_part_sha256: Annotated[Sha256, Header()],
    user: AppUser = Depends(get_current_user), db: Session = Depends(get_catalog_db),
):
    actor_id = user.id
    await anyio.to_thread.run_sync(db.commit)
    return await put_part(
        id, part_number, x_part_sha256, request, actor_id, request.app.state.policy_manager
    )


@router.post("/uploads/{id}/complete", status_code=202)
async def complete(
    id: UUID, data: UploadComplete, request: Request,
    user: AppUser = Depends(get_current_user), db: Session = Depends(get_catalog_db),
):
    actor_id = user.id
    await anyio.to_thread.run_sync(db.commit)
    return await complete_upload(id, data, actor_id, request.app.state.policy_manager)


@router.delete("/uploads/{id}", status_code=204)
async def abort(
    id: UUID, request: Request, user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_catalog_db),
):
    actor_id = user.id
    await anyio.to_thread.run_sync(db.commit)
    await abort_upload(id, actor_id, request.app.state.policy_manager)
    return Response(status_code=204)
