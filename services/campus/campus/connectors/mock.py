from datetime import UTC, datetime, timedelta

from .base import CampusItem


class MockConnector:
    async def fetch(self, access_token: str) -> list[CampusItem]:
        del access_token
        start = datetime.now(UTC).replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(days=1)
        return [
            CampusItem(external_id="demo-course-1", title="示例课程", kind="course", starts_at=start, ends_at=start + timedelta(minutes=90)),
            CampusItem(external_id="demo-task-1", title="示例作业", kind="task", due_at=start + timedelta(days=2)),
        ]

