from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import models
from app.schemas.auth import UserOut, UserUpdate, UserList
from app.schemas.response import ApiResponse
from app.core.security import hash_password
from app.core.dependencies import get_db, get_admin_user

router = APIRouter(prefix="/admin", tags=["Admin"])


def _user_out(user: models.User) -> UserOut:
    return UserOut(
        id=user.id,
        name=user.name,
        email=user.email,
        role=user.role,
    )


@router.get("/users", response_model=ApiResponse[UserList])
def list_users(
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_admin_user),
):
    users = db.query(models.User).all()
    user_list = [_user_out(user) for user in users]

    return ApiResponse(
        data=UserList(
            total=len(user_list),
            users=user_list,
        ),
    )


@router.put("/users/{user_id}", response_model=ApiResponse[UserOut])
def update_user(
    user_id: str,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_admin_user),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.email and payload.email != user.email:
        existing = db.query(models.User).filter(models.User.email == payload.email).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email already in use")

    if payload.name is not None:
        user.name = payload.name
    if payload.email is not None:
        user.email = payload.email
    if payload.role is not None:
        if payload.role not in ("admin", "user"):
            raise HTTPException(status_code=400, detail="Role must be admin or user")
        user.role = payload.role
    if payload.password is not None:
        user.hashed_password = hash_password(payload.password)

    db.commit()
    db.refresh(user)

    return ApiResponse(
        message="User updated",
        data=_user_out(user),
    )


@router.delete("/users/{user_id}", response_model=ApiResponse[None])
def delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_admin_user),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    db.delete(user)
    db.commit()

    return ApiResponse(message="User deleted")
