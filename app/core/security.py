import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from app.core.config import get_settings


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 390000)
    return f"pbkdf2_sha256${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, salt_b64, digest_b64 = password_hash.split("$", 2)
    except ValueError:
        return False

    if algorithm != "pbkdf2_sha256":
        return False

    salt = base64.b64decode(salt_b64)
    expected_digest = base64.b64decode(digest_b64)
    actual_digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 390000)
    return hmac.compare_digest(actual_digest, expected_digest)


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_access_token(subject: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.access_token_expire_minutes)
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": subject,
        "iss": settings.jwt_issuer,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    signing_input = ".".join(
        [
            _b64url_encode(json.dumps(header, separators=(",", ":")).encode()),
            _b64url_encode(json.dumps(payload, separators=(",", ":")).encode()),
        ]
    )
    signature = hmac.new(
        settings.jwt_secret_key.encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{signing_input}.{_b64url_encode(signature)}"


def decode_access_token(token: str) -> Dict[str, Any]:
    settings = get_settings()
    try:
        header_b64, payload_b64, signature_b64 = token.split(".", 2)
    except ValueError as exc:
        raise ValueError("Invalid token format.") from exc

    signing_input = f"{header_b64}.{payload_b64}"
    expected_signature = hmac.new(
        settings.jwt_secret_key.encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    actual_signature = _b64url_decode(signature_b64)

    if not hmac.compare_digest(actual_signature, expected_signature):
        raise ValueError("Invalid token signature.")

    payload = json.loads(_b64url_decode(payload_b64))
    if payload.get("iss") != settings.jwt_issuer:
        raise ValueError("Invalid token issuer.")

    if int(payload.get("exp", 0)) < int(datetime.now(timezone.utc).timestamp()):
        raise ValueError("Token has expired.")

    return payload
