import time
import uuid
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.database import get_pool
from app.core.security import decode_access_token


class RequestTrackingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        error_msg: str | None = None
        status_code: int | None = None

        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as exc:
            error_msg = str(exc)
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            user_id = _extract_user_id(request)

            try:
                pool = await get_pool()
                await pool.execute(
                    """
                    INSERT INTO request_logs
                        (id, timestamp, method, path, query, status_code,
                         duration_ms, user_id, ip, user_agent, error)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    """,
                    str(uuid.uuid4()),
                    datetime.now(timezone.utc),
                    request.method,
                    request.url.path,
                    request.url.query or None,
                    status_code,
                    round(duration_ms, 2),
                    user_id,
                    _client_ip(request),
                    request.headers.get("user-agent"),
                    error_msg,
                )
            except Exception:
                pass

        return response


def _extract_user_id(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    try:
        return decode_access_token(token).get("sub")
    except Exception:
        return None


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None
