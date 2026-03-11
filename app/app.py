from __future__ import annotations

from fastapi import FastAPI

from app.routes.graphql import graphql_app


def create_app() -> FastAPI:
    app = FastAPI(title="Scholarship Crawler GraphQL API", version="2.0.0")

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.mount("/graphql", graphql_app())
    return app
