from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.core.security import decode_access_token
from app.schemas.auth import AuthResponse, GoogleLogin, UserCreate, UserLogin, UserPublic
from app.services.auth_service import (
    AuthService,
    DuplicateUserError,
    GoogleAuthError,
    InvalidCredentialsError,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def get_auth_service() -> AuthService:
    return AuthService()


async def get_current_user(
    authorization: str = Header(default=""),
    auth_service: AuthService = Depends(get_auth_service),
) -> dict:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
        )

    try:
        payload = decode_access_token(token)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    user = await auth_service.get_user_by_id(payload["sub"])
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists.",
        )

    return {
        "id": user["id"],
        "email": user["email"],
        "full_name": user["full_name"],
        "avatar_url": user["avatar_url"],
        "auth_provider": user["auth_provider"],
    }


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, auth_service: AuthService = Depends(get_auth_service)):
    try:
        return await auth_service.create_email_user(
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
        )
    except DuplicateUserError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/login", response_model=AuthResponse)
async def login(payload: UserLogin, auth_service: AuthService = Depends(get_auth_service)):
    try:
        return await auth_service.authenticate_email_user(
            email=payload.email,
            password=payload.password,
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.post("/google", response_model=AuthResponse)
async def google_login(payload: GoogleLogin, auth_service: AuthService = Depends(get_auth_service)):
    try:
        return await auth_service.authenticate_google_user(payload.id_token)
    except GoogleAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.get("/me", response_model=UserPublic)
def me(current_user: dict = Depends(get_current_user)):
    return current_user
