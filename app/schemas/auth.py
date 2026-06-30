from typing import Optional

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    full_name: Optional[str] = Field(default=None, max_length=120)


class UserLogin(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str


class GoogleLogin(BaseModel):
    id_token: str = Field(min_length=20)


class UserPublic(BaseModel):
    id: str
    email: str
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    auth_provider: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic
