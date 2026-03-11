from __future__ import annotations

from ariadne import MutationType, QueryType, gql, make_executable_schema

from app.repos.scholarship_repo import fetch_scholarships
from app.services.crawler_service import crawl_and_save


type_defs = gql(
    """
    type Scholarship {
      country: String!
      university: String!
      university_website: String!
      scholarship_page: String!
      title: String!
      text_information: String
      date_published: String
      department: String
      faculty: String
      deadline: String
      discovered_at_utc: String!
      updated_at_utc: String!
    }

    type CrawlResult {
      processed_records: Int!
      inserted: Int!
      updated: Int!
      unchanged: Int!
    }

    input CrawlInput {
      country: String!
      max_pages_per_site: Int = 80
      limit_universities: Int
    }

    type Query {
      scholarships(country: String, university: String, limit: Int = 100): [Scholarship!]!
    }

    type Mutation {
      crawl(input: CrawlInput!): CrawlResult!
    }
    """
)

query = QueryType()
mutation = MutationType()


@query.field("scholarships")
def resolve_scholarships(*_args, country=None, university=None, limit=100):
    return fetch_scholarships(country=country, university=university, limit=limit)


@mutation.field("crawl")
async def resolve_crawl(*_args, input):
    processed_records, stats = await crawl_and_save(
        country=input["country"],
        max_pages_per_site=input.get("max_pages_per_site", 80),
        limit_universities=input.get("limit_universities"),
    )
    return {
        "processed_records": processed_records,
        "inserted": stats.inserted,
        "updated": stats.updated,
        "unchanged": stats.unchanged,
    }


schema = make_executable_schema(type_defs, query, mutation)
