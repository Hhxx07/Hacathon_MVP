from datetime import datetime
from typing import Protocol

from pydantic import BaseModel


class CampusItem(BaseModel):
    external_id: str
    title: str
    kind: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    due_at: datetime | None = None


class CampusConnector(Protocol):
    async def fetch(self, access_token: str) -> list[CampusItem]: ...

