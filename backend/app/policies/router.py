"""Read-only manager policy view; reload and storage resolution follow in Step 5."""
from fastapi import APIRouter, Depends, Request

from app.auth.dependencies import require_role
from app.core.policy_schema import PoliciesConfig
from app.models.enums import UserRole

router = APIRouter(prefix="/api/v1", tags=["policies"])


@router.get(
    "/admin/policies",
    response_model=PoliciesConfig,
    dependencies=[Depends(require_role(UserRole.MANAGER))],
)
def get_policies(request: Request) -> PoliciesConfig:
    return request.app.state.policies
