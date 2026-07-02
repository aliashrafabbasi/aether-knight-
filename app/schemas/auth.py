from typing import Optional

from pydantic import BaseModel


class UserCreate(BaseModel):
    name: str
    email: str
    password: str
    role: Optional[str] = "user"


class UserLogin(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: str
    name: str
    email: str
    role: str


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None


class AuthToken(BaseModel):
    token: str
    type: str = "bearer"
    user: UserOut


class UserList(BaseModel):
    total: int
    users: list[UserOut]
