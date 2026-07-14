from fastapi import FastAPI

from app.api.routes.auth import router as auth_router
from app.api.routes.us import router as us_router
from app.api.routes.watchlist import router as watchlist_router
from app.core.config import get_settings
from app.core.orm import create_orm_tables, dispose_engine
from app.core.tracking import RequestTrackingMiddleware

settings = get_settings()

app = FastAPI(title=settings.app_name)
app.add_middleware(RequestTrackingMiddleware)


@app.on_event("startup")
async def startup():
    await create_orm_tables()


@app.on_event("shutdown")
async def shutdown():
    await dispose_engine()


@app.get("/")
def read_root():
    return {"message": "FastAPI is running"}


@app.get("/health")
def health_check():
    return {"status": "ok"}


app.include_router(auth_router, prefix="/api")
app.include_router(us_router, prefix="/api")
app.include_router(watchlist_router, prefix="/api")
