from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from pick2light.db import get_db

DB = Annotated[AsyncSession, Depends(get_db, scope="function")]
