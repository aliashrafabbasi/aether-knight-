from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.db.database import engine
from app.db import models
from app.schemas.auth import UserCreate, UserLogin, UserOut, AuthToken, UserList
from app.schemas.response import ApiResponse
from app.core.security import hash_password, verify_password, create_access_token, decode_token
from app.core.dependencies import get_db, get_current_user, get_admin_user, bearer_scheme

models.Base.metadata.create_all(bind=engine)

router = APIRouter(prefix="/auth", tags=["Auth"])


def _user_out(user: models.User) -> UserOut:
    return UserOut(
        id=user.id,
        name=user.name,
        email=user.email,
        role=user.role,
    )


@router.post("/register", response_model=ApiResponse[UserOut])
def register(user: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(models.User).filter(models.User.email == user.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    new_user = models.User(
        name=user.name,
        email=user.email,
        hashed_password=hash_password(user.password),
        role="user",
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return ApiResponse(
        message="Account created",
        data=_user_out(new_user),
    )


@router.post("/login", response_model=ApiResponse[AuthToken])
def login(user: UserLogin, db: Session = Depends(get_db)):
    db_user = db.query(models.User).filter(models.User.email == user.email).first()

    if not db_user or not verify_password(user.password, db_user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token({
        "sub": db_user.email,
        "role": db_user.role,
    })

    return ApiResponse(
        message="Login successful",
        data=AuthToken(
            token=token,
            user=_user_out(db_user),
        ),
    )


@router.get("/me", response_model=ApiResponse[UserOut])
def me(current_user: models.User = Depends(get_current_user)):
    return ApiResponse(data=_user_out(current_user))


@router.post("/logout", response_model=ApiResponse[None])
def logout(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    payload = decode_token(credentials.credentials)
    jti = payload.get("jti") if payload else None

    if jti:
        existing = db.query(models.RevokedToken).filter(
            models.RevokedToken.jti == jti
        ).first()
        if not existing:
            db.add(models.RevokedToken(jti=jti))
            db.commit()

    return ApiResponse(message="Logged out")


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
