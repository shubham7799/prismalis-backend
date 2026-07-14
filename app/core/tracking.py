import time
import uuid
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.orm import get_session
from app.core.security import decode_access_token
from app.models.request_log import RequestLog


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

            try:
                log = RequestLog(
                    id=str(uuid.uuid4()),
                    timestamp=datetime.now(timezone.utc),
                    method=request.method,
                    path=request.url.path,
                    query=request.url.query or None,
                    status_code=status_code,
                    duration_ms=round(duration_ms, 2),
                    user_id=_extract_user_id(request),
                    ip=_client_ip(request),
                    user_agent=request.headers.get("user-agent"),
                    error=error_msg,
                )
                async with get_session() as session:
                    session.add(log)
                    await session.commit()
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
