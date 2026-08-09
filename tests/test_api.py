from datetime import UTC, datetime, timedelta


async def test_health(client):
    assert (await client.get("/health/live")).json() == {"status": "ok"}


async def test_register_duplicate(client):
    body = {"email": "moss@example.com", "password": "correct-horse-battery"}
    assert (await client.post("/api/v1/auth/register", json=body)).status_code == 201
    assert (await client.post("/api/v1/auth/register", json=body)).status_code == 409


async def test_create_and_list_event(client, auth):
    start = datetime.now(UTC) + timedelta(days=1)
    body = {"title": "高等数学", "starts_at": start.isoformat(), "ends_at": (start + timedelta(minutes=90)).isoformat(), "kind": "course"}
    assert (await client.post("/api/v1/events", json=body, headers=auth)).status_code == 201
    events = (await client.get("/api/v1/events", headers=auth)).json()
    assert len(events) == 1 and events[0]["title"] == "高等数学"


async def test_reject_invalid_event_range(client, auth):
    at = datetime.now(UTC).isoformat()
    assert (await client.post("/api/v1/events", json={"title": "bad", "starts_at": at, "ends_at": at}, headers=auth)).status_code == 422


async def test_task_focus_and_balance(client, auth):
    task = await client.post("/api/v1/tasks", json={"title": "完成报告"}, headers=auth)
    assert task.status_code == 201
    focus = await client.post("/api/v1/focus/start", json={"planned_minutes": 25}, headers=auth)
    assert focus.status_code == 201
    assert (await client.get("/api/v1/rewards/balance", headers=auth)).json() == {"balance": 0}

