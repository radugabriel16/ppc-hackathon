"""Manager-only effective policy view and audited, atomic reload."""
from datetime import datetime, timezone

import anyio
import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth.dependencies import require_role
from app.core.db import get_catalog_db
from app.core.logging import get_request_id
from app.core.policy_schema import PoliciesConfig, load_policies
from app.core.settings import get_settings
from app.models.audit import AuditEvent
from app.models.auth import AppUser
from app.models.enums import UserRole
from app.policies.service import PolicyManager

router = APIRouter(prefix="/api/v1", tags=["policies"])


@router.get(
    "/admin/policies",
    response_model=PoliciesConfig,
    dependencies=[Depends(require_role(UserRole.MANAGER))],
)
def get_policies(request: Request) -> PoliciesConfig:
    return request.app.state.policy_manager.config


@router.post("/admin/policies/reload", response_model=PoliciesConfig)
async def reload_policies(
    request: Request,
    user: AppUser = Depends(require_role(UserRole.MANAGER)),
    db: Session = Depends(get_catalog_db),
) -> PoliciesConfig:
    manager: PolicyManager = request.app.state.policy_manager
    request_id = (get_request_id() or "")[:64] or None

    def load_and_audit() -> PoliciesConfig:
        try:
            config = load_policies(get_settings().policies_path)
        except (ValueError, yaml.YAMLError) as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "INVALID_POLICIES", "message": "Policy file failed validation"},
            ) from exc
        except OSError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "POLICIES_UNAVAILABLE", "message": "Policy file cannot be read"},
                headers={"Retry-After": "1"},
            ) from exc
        db.add(
            AuditEvent(
                actor_id=user.id,
                action="POLICIES_RELOADED",
                entity_type="policies",
                occurred_at=datetime.now(timezone.utc),
                request_id=request_id,
                details={"categories": config.model_dump(mode="json", by_alias=True)["categories"]},
            )
        )
        db.commit()
        return config

    async with manager.reload_lock:
        config = await anyio.to_thread.run_sync(load_and_audit)
        manager.activate(config)
        return config
