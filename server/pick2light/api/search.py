from fastapi import APIRouter

from pick2light.api.deps import DB
from pick2light.core.search import SearchPage, SearchQuery, search

router = APIRouter(tags=["search"])


@router.post("/search")
async def search_post(query: SearchQuery, db: DB) -> SearchPage:
    return await search(db, query)


@router.get("/search")
async def search_get(db: DB, q: str = "", limit: int = 50, offset: int = 0) -> SearchPage:
    return await search(db, SearchQuery(q=q or None, limit=limit, offset=offset))
