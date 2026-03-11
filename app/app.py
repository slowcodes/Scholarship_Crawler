from __future__ import annotations

from fastapi import FastAPI

from app.routes.scholarships import router as scholarships_router


def create_app() -> FastAPI:
    app = FastAPI(title="Scholarship Crawler API", version="1.0.0")

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(scholarships_router)
    return app
