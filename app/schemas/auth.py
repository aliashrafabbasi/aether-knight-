from pydantic import BaseModel


class UserCreate(BaseModel):
    name: str
    email: str
    password: str


class UserLogin(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: int
    name: str
    email: str
    role: str


class AuthToken(BaseModel):
    token: str
    type: str = "bearer"
    user: UserOut


class UserList(BaseModel):
    total: int
    users: list[UserOut]
