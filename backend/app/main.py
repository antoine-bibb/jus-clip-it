from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.billing import router as billing_router
from app.api.routes.clips import router as clips_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.uploads import router as uploads_router
from app.core.config import settings
from app.core.db import Base, engine

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://localhost:3000', 'http://127.0.0.1:3000', 'http://localhost:3001', 'http://127.0.0.1:3001'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)
app.include_router(uploads_router)
app.include_router(clips_router)
app.include_router(jobs_router)
app.include_router(billing_router)


@app.on_event('startup')
async def startup() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@app.get('/health', tags=['health'])
async def healthcheck() -> dict[str, str]:
    return {'status': 'ok'}
