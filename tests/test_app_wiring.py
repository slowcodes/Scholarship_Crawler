from __future__ import annotations

from fastapi import FastAPI

from app.app import create_app
from app.routes.graphql import graphql_app


def test_create_app_returns_fastapi_with_health_route() -> None:
    app = create_app()
    assert isinstance(app, FastAPI)
    route_paths = {getattr(r, "path", None) for r in app.routes}
    assert "/health" in route_paths


def test_graphql_app_factory_returns_asgi_app() -> None:
    app = graphql_app()
    assert callable(app)
