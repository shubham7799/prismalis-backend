import uuid
from datetime import datetime, timezone
from typing import Optional

import asyncpg
import httpx

from app.core.config import get_settings
from app.core.database import get_connection
from app.core.security import create_access_token, hash_password, verify_password


class AuthError(Exception):
    pass


class DuplicateUserError(AuthError):
    pass


class InvalidCredentialsError(AuthError):
    pass


class GoogleAuthError(AuthError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _user_to_dict(user: asyncpg.Record) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
        "full_name": user["full_name"],
        "avatar_url": user["avatar_url"],
        "auth_provider": user["auth_provider"],
    }


class AuthService:
    async def create_email_user(self, email: str, password: str, full_name: Optional[str]) -> dict:
        user_id = str(uuid.uuid4())
        normalized_email = _normalize_email(email)
        now = _now()

        try:
            async with get_connection() as connection:
                await connection.execute(
                    """
                    INSERT INTO users (
                        id, email, full_name, password_hash, auth_provider, created_at, updated_at
                    )
                    VALUES ($1, $2, $3, $4, 'email', $5, $6)
                    """,
                    user_id,
                    normalized_email,
                    full_name,
                    hash_password(password),
                    now,
                    now,
                )
        except asyncpg.UniqueViolationError as exc:
            raise DuplicateUserError("A user with this email already exists.") from exc

        user = await self.get_user_by_id(user_id)
        return self.create_auth_response(user)

    async def authenticate_email_user(self, email: str, password: str) -> dict:
        user = await self.get_user_by_email(email)
        if not user or not user["password_hash"]:
            raise InvalidCredentialsError("Invalid email or password.")

        if not verify_password(password, user["password_hash"]):
            raise InvalidCredentialsError("Invalid email or password.")

        return self.create_auth_response(user)

    async def authenticate_google_user(self, id_token: str) -> dict:
        google_user = await self.verify_google_id_token(id_token)
        user = await self.upsert_google_user(
            email=google_user["email"],
            google_sub=google_user["sub"],
            full_name=google_user.get("name"),
            avatar_url=google_user.get("picture"),
        )
        return self.create_auth_response(user)

    async def verify_google_id_token(self, id_token: str) -> dict:
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

    async def upsert_google_user(
        self,
        email: str,
        google_sub: str,
        full_name: Optional[str],
        avatar_url: Optional[str],
    ) -> asyncpg.Record:
        normalized_email = _normalize_email(email)
        now = _now()

        async with get_connection() as connection:
            existing = await connection.fetchrow(
                "SELECT * FROM users WHERE email = $1",
                normalized_email,
            )

            if existing:
                await connection.execute(
                    """
                    UPDATE users
                    SET google_sub = $1, full_name = COALESCE($2, full_name),
                        avatar_url = COALESCE($3, avatar_url), updated_at = $4
                    WHERE id = $5
                    """,
                    google_sub,
                    full_name,
                    avatar_url,
                    now,
                    existing["id"],
                )
                return await self.get_user_by_id(existing["id"])

            user_id = str(uuid.uuid4())
            await connection.execute(
                """
                INSERT INTO users (
                    id, email, full_name, avatar_url, google_sub, auth_provider, created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, 'google', $6, $7)
                """,
                user_id,
                normalized_email,
                full_name,
                avatar_url,
                google_sub,
                now,
                now,
            )
            return await self.get_user_by_id(user_id)

    async def get_user_by_email(self, email: str) -> Optional[asyncpg.Record]:
        async with get_connection() as connection:
            return await connection.fetchrow(
                "SELECT * FROM users WHERE email = $1 AND is_active = TRUE",
                _normalize_email(email),
            )

    async def get_user_by_id(self, user_id: str) -> Optional[asyncpg.Record]:
        async with get_connection() as connection:
            return await connection.fetchrow(
                "SELECT * FROM users WHERE id = $1 AND is_active = TRUE",
                user_id,
            )

    def create_auth_response(self, user: asyncpg.Record) -> dict:
        return {
            "access_token": create_access_token(user["id"]),
            "token_type": "bearer",
            "user": _user_to_dict(user),
        }
