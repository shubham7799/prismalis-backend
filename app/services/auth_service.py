import uuid
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.orm import get_session
from app.core.security import create_access_token, hash_password, verify_password
from app.models.users import User


class AuthError(Exception):
    pass


class DuplicateUserError(AuthError):
    pass


class InvalidCredentialsError(AuthError):
    pass


class GoogleAuthError(AuthError):
    pass


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _user_to_dict(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "avatar_url": user.avatar_url,
        "auth_provider": user.auth_provider,
    }


class AuthService:
    async def create_email_user(self, email: str, password: str, full_name: Optional[str]) -> dict:
        user = User(
            id=str(uuid.uuid4()),
            email=_normalize_email(email),
            full_name=full_name,
            password_hash=hash_password(password),
            auth_provider="email",
        )
        try:
            async with get_session() as session:
                session.add(user)
                await session.commit()
                await session.refresh(user)
        except IntegrityError as exc:
            raise DuplicateUserError("A user with this email already exists.") from exc

        return self._create_auth_response(user)

    async def authenticate_email_user(self, email: str, password: str) -> dict:
        user = await self._get_user_by_email(email)
        if not user or not user.password_hash:
            raise InvalidCredentialsError("Invalid email or password.")
        if not verify_password(password, user.password_hash):
            raise InvalidCredentialsError("Invalid email or password.")
        return self._create_auth_response(user)

    async def authenticate_google_user(self, id_token: str) -> dict:
        google_user = await self._verify_google_id_token(id_token)
        user = await self._upsert_google_user(
            email=google_user["email"],
            google_sub=google_user["sub"],
            full_name=google_user.get("name"),
            avatar_url=google_user.get("picture"),
        )
        return self._create_auth_response(user)

    async def _verify_google_id_token(self, id_token: str) -> dict:
        settings = get_settings()
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                "https://oauth2.googleapis.com/tokeninfo",
                params={"id_token": id_token},
            )

        if response.status_code >= 400:
            raise GoogleAuthError("Google token verification failed.")

        payload = response.json()
        if payload.get("email_verified") not in ("true", True):
            raise GoogleAuthError("Google email is not verified.")
        if settings.google_client_id and payload.get("aud") != settings.google_client_id:
            raise GoogleAuthError("Google token audience does not match this application.")
        if not payload.get("email") or not payload.get("sub"):
            raise GoogleAuthError("Google token is missing required user information.")

        return payload

    async def _upsert_google_user(
        self,
        email: str,
        google_sub: str,
        full_name: Optional[str],
        avatar_url: Optional[str],
    ) -> User:
        normalized_email = _normalize_email(email)

        async with get_session() as session:
            result = await session.execute(
                select(User).where(User.email == normalized_email)
            )
            user = result.scalar_one_or_none()

            if user:
                user.google_sub = google_sub
                if full_name:
                    user.full_name = full_name
                if avatar_url:
                    user.avatar_url = avatar_url
            else:
                user = User(
                    id=str(uuid.uuid4()),
                    email=normalized_email,
                    full_name=full_name,
                    avatar_url=avatar_url,
                    google_sub=google_sub,
                    auth_provider="google",
                )
                session.add(user)

            await session.commit()
            await session.refresh(user)

        return user

    async def get_user_by_id(self, user_id: str) -> Optional[User]:
        async with get_session() as session:
            result = await session.execute(
                select(User).where(User.id == user_id, User.is_active.is_(True))
            )
            return result.scalar_one_or_none()

    async def _get_user_by_email(self, email: str) -> Optional[User]:
        async with get_session() as session:
            result = await session.execute(
                select(User).where(
                    User.email == _normalize_email(email),
                    User.is_active.is_(True),
                )
            )
            return result.scalar_one_or_none()

    def _create_auth_response(self, user: User) -> dict:
        return {
            "access_token": create_access_token(user.id),
            "token_type": "bearer",
            "user": _user_to_dict(user),
        }
