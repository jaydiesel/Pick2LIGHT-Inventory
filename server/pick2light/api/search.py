from typing import Annotated

from fastapi import APIRouter, Query

from pick2light.api.deps import DB
from pick2light.core import search as svc
from pick2light.core.search import SearchPage, SearchQuery

router = APIRouter(prefix="/search", tags=["search"])


@router.post("")
async def search_post(query: SearchQuery, db: DB) -> SearchPage:
    return await svc.search(db, query)


@router.get("")
async def search_get(
    db: DB,
    q: str = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SearchPage:
    return await svc.search(db, SearchQuery(q=q, limit=limit, offset=offset))
