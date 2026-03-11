from __future__ import annotations

from ariadne.asgi import GraphQL

from app.graphql.schema import schema


def graphql_app() -> GraphQL:
    return GraphQL(schema, debug=True)
