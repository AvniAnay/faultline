from fastapi import APIRouter, Depends

from app.api.schemas import Me
from app.auth import CurrentUser, require_role

router = APIRouter()


@router.get("/me", response_model=Me)
def me(user: CurrentUser = Depends(require_role("viewer"))) -> Me:
    return Me(id=user.id, email=user.email, display_name=user.display_name, role=user.role)
