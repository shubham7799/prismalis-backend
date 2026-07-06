from fastapi import FastAPI

from app.api.routes.auth import router as auth_router
from app.api.routes.us import router as us_router
from app.core.config import get_settings
from app.core.database import close_db_pool, init_db
from app.core.orm import create_orm_tables, dispose_engine

settings = get_settings()

app = FastAPI(title=settings.app_name)


@app.on_event("startup")
async def startup():
    await init_db()
    await create_orm_tables()


@app.on_event("shutdown")
async def shutdown():
    await close_db_pool()
    await dispose_engine()


@app.get("/")
def read_root():
    return {"message": "FastAPI is running"}


@app.get("/health")
def health_check():
    return {"status": "ok"}


app.include_router(auth_router, prefix="/api")
app.include_router(us_router, prefix="/api")
