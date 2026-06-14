from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user
from app.db import models
from app.schemas.auth import UserOut
from app.schemas.response import ApiResponse

router = APIRouter(prefix="/voice", tags=["Voice"])


@router.get("/test", response_model=ApiResponse[UserOut])
def voice_test(current_user: models.User = Depends(get_current_user)):
    return ApiResponse(
        message="Voice access granted",
        data=UserOut(
            id=current_user.id,
            name=current_user.name,
            email=current_user.email,
            role=current_user.role,
        ),
    )
