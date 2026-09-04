import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .models import (
    CalendarEvent,
    EventKind,
    FocusSession,
    RewardLedger,
    Schedule,
    ScheduleFolder,
    ScheduleTag,
    ScheduleTagAssociation,
    Task,
    User,
)
from .schemas import (
    BalanceOut,
    CalendarEntryOut,
    EventCreate,
    EventOut,
    EventSyncOut,
    EventSyncRequest,
    EventUpdate,
    FocusOut,
    FocusStart,
    LoginRequest,
    RegisterRequest,
    ScheduleCreate,
    ScheduleFolderCreate,
    ScheduleFolderOut,
    ScheduleFolderUpdate,
    ScheduleOut,
    ScheduleStatsOut,
    ScheduleTagCreate,
    ScheduleTagOut,
    ScheduleTagUpdate,
    ScheduleUpdate,
    TagCountItem,
    TaskCreate,
    TaskOut,
    TokenResponse,
)
from .security import create_token, current_user, password_hash

router = APIRouter(prefix="/api/v1")


@router.post("/auth/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, session: AsyncSession = Depends(get_session)):
    if await session.scalar(select(User).where(User.email == body.email.lower())):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(email=body.email.lower(), password_hash=password_hash.hash(body.password))
    session.add(user)
    await session.commit()
    return TokenResponse(access_token=create_token(user.id))


@router.post("/auth/login", response_model=TokenResponse)
async def login(body: LoginRequest, session: AsyncSession = Depends(get_session)):
    user = await session.scalar(select(User).where(User.email == body.email.lower()))
    if not user or not password_hash.verify(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    return TokenResponse(access_token=create_token(user.id))


@router.get("/events", response_model=list[EventOut])
async def list_events(
    start_date: datetime | None = Query(None, description="开始时间（含）"),
    end_date: datetime | None = Query(None, description="结束时间（不含）"),
    kind: str | None = Query(None, description="event/course/deadline"),
    source: str | None = Query(None),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    """List imported calendar events owned by the current user.

    Date filters use half-open intervals, which makes adjacent calendar
    windows safe to page through without duplicating events.
    """
    if start_date is not None and end_date is not None and end_date <= start_date:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "end_date must be after start_date")
    query = select(CalendarEvent).where(CalendarEvent.user_id == user.id)
    if start_date is not None:
        query = query.where(CalendarEvent.ends_at > start_date)
    if end_date is not None:
        query = query.where(CalendarEvent.starts_at < end_date)
    if kind is not None:
        try:
            query = query.where(CalendarEvent.kind == EventKind(kind.lower()))
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid event kind") from exc
    if source is not None:
        query = query.where(CalendarEvent.source == source)
    result = await session.scalars(query.order_by(CalendarEvent.starts_at, CalendarEvent.id))
    return list(result)


@router.post("/events/sync", response_model=EventSyncOut)
async def sync_events(
    body: EventSyncRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    # _sync_events is defined below; lookup happens when a request is served.
    return await _sync_events(body, user, session)


@router.get("/events/{event_id}", response_model=EventOut)
async def get_event(
    event_id: uuid.UUID,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    event = await session.scalar(
        select(CalendarEvent).where(CalendarEvent.id == event_id, CalendarEvent.user_id == user.id)
    )
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    return event


@router.post("/events", response_model=EventOut, status_code=status.HTTP_201_CREATED)
async def create_event(
    body: EventCreate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    event = CalendarEvent(user_id=user.id, **body.model_dump())
    session.add(event)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Event with this external_id already exists") from exc
    await session.refresh(event)
    return event


@router.put("/events/{event_id}", response_model=EventOut)
async def update_event(
    event_id: uuid.UUID,
    body: EventUpdate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    event = await session.scalar(
        select(CalendarEvent).where(CalendarEvent.id == event_id, CalendarEvent.user_id == user.id)
    )
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    values = body.model_dump(exclude_unset=True)
    for field, value in values.items():
        setattr(event, field, value)
    starts_at = event.starts_at
    ends_at = event.ends_at
    if ends_at <= starts_at:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ends_at must be after starts_at")
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Event with this external_id already exists") from exc
    await session.refresh(event)
    return event


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: uuid.UUID,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    event = await session.scalar(
        select(CalendarEvent).where(CalendarEvent.id == event_id, CalendarEvent.user_id == user.id)
    )
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    await session.delete(event)
    await session.commit()
    return None


async def _sync_events(
    body: EventSyncRequest, user: User, session: AsyncSession
) -> EventSyncOut:
    """Idempotently upsert connector output using (user, source, external_id)."""
    # A connector may accidentally emit an item twice; last occurrence wins
    # and must not violate the calendar uniqueness constraint.
    items = list({item.external_id: item for item in body.items}.values())
    external_ids = [item.external_id for item in items]
    if external_ids:
        existing_rows = (
            await session.scalars(
                select(CalendarEvent).where(
                    CalendarEvent.user_id == user.id,
                    CalendarEvent.source == body.source,
                    CalendarEvent.external_id.in_(external_ids),
                )
            )
        ).all()
    else:
        existing_rows = []
    existing = {event.external_id: event for event in existing_rows}
    created = updated = 0
    result: list[CalendarEvent] = []
    for item in items:
        event = existing.get(item.external_id)
        values = {
            "title": item.title,
            "description": item.description,
            "starts_at": item.starts_at,
            "ends_at": item.ends_at,
            "kind": item.kind,
        }
        if event is None:
            event = CalendarEvent(
                user_id=user.id,
                source=body.source,
                external_id=item.external_id,
                **values,
            )
            session.add(event)
            existing[item.external_id] = event
            created += 1
        else:
            for field, value in values.items():
                setattr(event, field, value)
            updated += 1
        result.append(event)
    await session.commit()
    for event in result:
        await session.refresh(event)
    return EventSyncOut(
        source=body.source,
        created=created,
        updated=updated,
        total=len(result),
        events=[EventOut.model_validate(event) for event in result],
    )


async def _calendar_entries(
    start_date: datetime | None,
    end_date: datetime | None,
    kind: EventKind | None,
    source: str | None,
    user: User,
    session: AsyncSession,
) -> list[CalendarEntryOut]:
    """Read both imported calendar events and personal schedules uniformly."""
    event_query = select(CalendarEvent).where(CalendarEvent.user_id == user.id)
    schedule_query = select(Schedule).where(Schedule.user_id == user.id)
    task_query = select(Task).where(Task.user_id == user.id, Task.due_at.is_not(None))
    if start_date is not None:
        event_query = event_query.where(CalendarEvent.ends_at > start_date)
        schedule_query = schedule_query.where(Schedule.ends_at > start_date)
        task_query = task_query.where(Task.due_at >= start_date)
    if end_date is not None:
        event_query = event_query.where(CalendarEvent.starts_at < end_date)
        schedule_query = schedule_query.where(Schedule.starts_at < end_date)
        task_query = task_query.where(Task.due_at < end_date)
    if kind is not None:
        if kind in (EventKind.COURSE, EventKind.DEADLINE, EventKind.EVENT):
            event_query = event_query.where(CalendarEvent.kind == kind)
            # Schedules are normal events and tasks are deadlines.
            if kind != EventKind.EVENT:
                schedule_query = schedule_query.where(False)
            if kind != EventKind.DEADLINE:
                task_query = task_query.where(False)
    if source is not None:
        event_query = event_query.where(CalendarEvent.source == source)
        if source != "schedule":
            schedule_query = schedule_query.where(False)
            task_query = task_query.where(Task.source == source)
        else:
            task_query = task_query.where(False)
    events = list(await session.scalars(event_query))
    schedules = list(await session.scalars(schedule_query))
    tasks = list(await session.scalars(task_query))
    entries = [CalendarEntryOut.model_validate(event) for event in events]
    for schedule in schedules:
        schedule_out = await _schedule_to_out(schedule, session)
        entries.append(
            CalendarEntryOut(
                id=schedule.id,
                title=schedule.title,
                description=schedule.description,
                starts_at=schedule.starts_at,
                ends_at=schedule.ends_at,
                kind=EventKind.EVENT,
                source="schedule",
                external_id=str(schedule.id),
                is_completed=schedule.is_completed,
                schedule_id=schedule.id,
                folder_id=schedule.folder_id,
                tags=schedule_out.tags,
            )
        )
    for task in tasks:
        # Tasks remain their own aggregate, but a due date is rendered as a
        # one-minute deadline in the unified calendar projection.
        due_at = task.due_at
        assert due_at is not None
        entries.append(
            CalendarEntryOut(
                id=task.id,
                title=task.title,
                description=task.details,
                starts_at=due_at,
                ends_at=due_at + timedelta(minutes=1),
                kind=EventKind.DEADLINE,
                source=task.source,
                external_id=task.external_id or str(task.id),
                is_completed=task.status.value == "done",
            )
        )
    entries.sort(key=lambda item: (item.starts_at, str(item.id)))
    return entries


@router.get("/calendar", response_model=list[CalendarEntryOut])
@router.get("/calendar/events", response_model=list[CalendarEntryOut], include_in_schema=False)
async def list_calendar(
    start_date: datetime | None = Query(None, description="开始时间（含）"),
    end_date: datetime | None = Query(None, description="结束时间（不含）"),
    kind: str | None = Query(None, description="event/course/deadline"),
    source: str | None = Query(None),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    if start_date is not None and end_date is not None and end_date <= start_date:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "end_date must be after start_date")
    parsed_kind = None
    if kind is not None:
        try:
            parsed_kind = EventKind(kind.lower())
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid event kind") from exc
    return await _calendar_entries(start_date, end_date, parsed_kind, source, user, session)


@router.post("/calendar/sync", response_model=EventSyncOut)
async def sync_calendar(
    body: EventSyncRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    return await _sync_events(body, user, session)


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    result = await session.scalars(select(Task).where(Task.user_id == user.id).order_by(Task.due_at))
    return list(result)


@router.post("/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(body: TaskCreate, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    task = Task(user_id=user.id, **body.model_dump())
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


@router.post("/focus/start", response_model=FocusOut, status_code=status.HTTP_201_CREATED)
async def start_focus(body: FocusStart, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    focus = FocusSession(user_id=user.id, planned_minutes=body.planned_minutes)
    session.add(focus)
    await session.commit()
    await session.refresh(focus)
    return focus


@router.post("/focus/{focus_id}/finish", response_model=FocusOut)
async def finish_focus(focus_id: uuid.UUID, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    focus = await session.scalar(
        select(FocusSession).where(FocusSession.id == focus_id, FocusSession.user_id == user.id)
    )
    if not focus:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Focus session not found")
    if focus.finished_at is None:
        focus.finished_at = datetime.now(UTC)
        elapsed = (focus.finished_at - focus.started_at).total_seconds()
        if elapsed >= focus.planned_minutes * 60 * 0.8:
            session.add(RewardLedger(user_id=user.id, amount=focus.planned_minutes, reason="focus_completed", reference_id=f"focus:{focus.id}"))
        await session.commit()
        await session.refresh(focus)
    return focus


@router.get("/rewards/balance", response_model=BalanceOut)
async def reward_balance(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    balance = await session.scalar(select(func.coalesce(func.sum(RewardLedger.amount), 0)).where(RewardLedger.user_id == user.id))
    return BalanceOut(balance=balance or 0)


# ──────────────── Schedule Folder APIs ────────────────


@router.get("/schedule-folders", response_model=list[ScheduleFolderOut])
async def list_folders(
    user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    result = await session.scalars(
        select(ScheduleFolder)
        .where(ScheduleFolder.user_id == user.id)
        .order_by(ScheduleFolder.created_at)
    )
    return list(result)


@router.post("/schedule-folders", response_model=ScheduleFolderOut, status_code=status.HTTP_201_CREATED)
async def create_folder(
    body: ScheduleFolderCreate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    existing = await session.scalar(
        select(ScheduleFolder).where(
            ScheduleFolder.user_id == user.id, ScheduleFolder.name == body.name
        )
    )
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Folder name already exists")
    folder = ScheduleFolder(user_id=user.id, name=body.name)
    session.add(folder)
    await session.commit()
    await session.refresh(folder)
    return folder


@router.put("/schedule-folders/{folder_id}", response_model=ScheduleFolderOut)
async def update_folder(
    folder_id: uuid.UUID,
    body: ScheduleFolderUpdate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    folder = await session.scalar(
        select(ScheduleFolder).where(
            ScheduleFolder.id == folder_id, ScheduleFolder.user_id == user.id
        )
    )
    if not folder:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Folder not found")
    conflict = await session.scalar(
        select(ScheduleFolder).where(
            ScheduleFolder.user_id == user.id,
            ScheduleFolder.name == body.name,
            ScheduleFolder.id != folder_id,
        )
    )
    if conflict:
        raise HTTPException(status.HTTP_409_CONFLICT, "Folder name already exists")
    folder.name = body.name
    await session.commit()
    await session.refresh(folder)
    return folder


@router.delete("/schedule-folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(
    folder_id: uuid.UUID,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    folder = await session.scalar(
        select(ScheduleFolder).where(
            ScheduleFolder.id == folder_id, ScheduleFolder.user_id == user.id
        )
    )
    if not folder:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Folder not found")
    # 将属于该文件夹的日程设为无文件夹
    schedules = (await session.scalars(
        select(Schedule).where(Schedule.folder_id == folder_id)
    )).all()
    for s in schedules:
        s.folder_id = None
    await session.delete(folder)
    await session.commit()
    return None


# ──────────────── Schedule Tag APIs ────────────────


@router.get("/schedule-tags", response_model=list[ScheduleTagOut])
async def list_tags(
    user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    result = await session.scalars(
        select(ScheduleTag)
        .where(ScheduleTag.user_id == user.id)
        .order_by(ScheduleTag.created_at)
    )
    return list(result)


@router.post("/schedule-tags", response_model=ScheduleTagOut, status_code=status.HTTP_201_CREATED)
async def create_tag(
    body: ScheduleTagCreate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    existing = await session.scalar(
        select(ScheduleTag).where(
            ScheduleTag.user_id == user.id, ScheduleTag.name == body.name
        )
    )
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Tag name already exists")
    tag = ScheduleTag(user_id=user.id, name=body.name, color=body.color)
    session.add(tag)
    await session.commit()
    await session.refresh(tag)
    return tag


@router.put("/schedule-tags/{tag_id}", response_model=ScheduleTagOut)
async def update_tag(
    tag_id: uuid.UUID,
    body: ScheduleTagUpdate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    tag = await session.scalar(
        select(ScheduleTag).where(
            ScheduleTag.id == tag_id, ScheduleTag.user_id == user.id
        )
    )
    if not tag:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tag not found")
    if body.name is not None:
        conflict = await session.scalar(
            select(ScheduleTag).where(
                ScheduleTag.user_id == user.id,
                ScheduleTag.name == body.name,
                ScheduleTag.id != tag_id,
            )
        )
        if conflict:
            raise HTTPException(status.HTTP_409_CONFLICT, "Tag name already exists")
        tag.name = body.name
    if body.color is not None:
        tag.color = body.color
    await session.commit()
    await session.refresh(tag)
    return tag


@router.delete("/schedule-tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(
    tag_id: uuid.UUID,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    tag = await session.scalar(
        select(ScheduleTag).where(
            ScheduleTag.id == tag_id, ScheduleTag.user_id == user.id
        )
    )
    if not tag:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tag not found")
    await session.delete(tag)
    await session.commit()
    return None


# ──────────────── Schedule (日程) APIs ────────────────


async def _schedule_to_out(schedule: Schedule, session: AsyncSession) -> ScheduleOut:
    """将 Schedule ORM 对象转为 ScheduleOut，包含关联的 tags。"""
    assoc_result = await session.scalars(
        select(ScheduleTagAssociation).where(
            ScheduleTagAssociation.schedule_id == schedule.id
        )
    )
    assocs = list(assoc_result)
    tag_ids = [a.tag_id for a in assocs]
    tags: list[ScheduleTagOut] = []
    if tag_ids:
        tag_result = await session.scalars(
            select(ScheduleTag).where(ScheduleTag.id.in_(tag_ids))
        )
        tags = [
            ScheduleTagOut.model_validate(t) for t in tag_result
        ]
    return ScheduleOut(
        id=schedule.id,
        folder_id=schedule.folder_id,
        title=schedule.title,
        description=schedule.description,
        starts_at=schedule.starts_at,
        ends_at=schedule.ends_at,
        is_completed=schedule.is_completed,
        tags=tags,
        created_at=schedule.created_at,
    )


async def _set_schedule_tags(
    schedule_id: uuid.UUID, tag_ids: list[uuid.UUID], session: AsyncSession
) -> None:
    """设置日程的标签（先删后建）。"""
    existing = (await session.scalars(
        select(ScheduleTagAssociation).where(
            ScheduleTagAssociation.schedule_id == schedule_id
        )
    )).all()
    for assoc in existing:
        await session.delete(assoc)
    # 先执行删除，避免与后续插入的新关联发生 (schedule_id, tag_id) 唯一约束冲突
    await session.flush()
    # 去重，防止传入重复 tag_id 导致唯一约束冲突
    for tag_id in dict.fromkeys(tag_ids):
        session.add(ScheduleTagAssociation(schedule_id=schedule_id, tag_id=tag_id))


@router.get("/schedules", response_model=list[ScheduleOut])
async def list_schedules(
    folder_id: uuid.UUID | None = Query(None, description="按文件夹筛选"),
    tag_id: uuid.UUID | None = Query(None, description="按标签筛选"),
    start_date: datetime | None = Query(None, description="开始日期筛选（含）"),
    end_date: datetime | None = Query(None, description="结束日期筛选（含）"),
    is_completed: bool | None = Query(None, description="按完成状态筛选"),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    query = select(Schedule).where(Schedule.user_id == user.id)

    if folder_id is not None:
        query = query.where(Schedule.folder_id == folder_id)
    if start_date is not None:
        query = query.where(Schedule.starts_at >= start_date)
    if end_date is not None:
        query = query.where(Schedule.ends_at <= end_date)
    if is_completed is not None:
        query = query.where(Schedule.is_completed == is_completed)

    # tag filter: join via association table
    if tag_id is not None:
        query = query.where(
            Schedule.id.in_(
                select(ScheduleTagAssociation.schedule_id).where(
                    ScheduleTagAssociation.tag_id == tag_id
                )
            )
        )

    query = query.order_by(Schedule.starts_at)
    result = await session.scalars(query)
    schedules = list(result)
    return [await _schedule_to_out(s, session) for s in schedules]


# ──────────────── Schedule Statistics APIs ────────────────


@router.get("/schedules/stats", response_model=ScheduleStatsOut)
async def schedule_stats(
    period: str = Query("month", pattern=r"^(day|week|month|year)$"),
    date: str | None = Query(None, description="基准日期 ISO 格式，默认今天"),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    """按天/周/月/年 统计已完成日程数量和标签分布（饼状图数据）。"""
    base_date = datetime.now(UTC) if date is None else datetime.fromisoformat(date)

    if period == "day":
        start = base_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
    elif period == "week":
        start = base_date.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            days=base_date.weekday()
        )
        end = start + timedelta(days=7)
    elif period == "month":
        start = base_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if base_date.month == 12:
            end = base_date.replace(year=base_date.year + 1, month=1, day=1)
        else:
            end = base_date.replace(month=base_date.month + 1, day=1)
    else:  # year
        start = base_date.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        end = base_date.replace(year=base_date.year + 1, month=1, day=1)

    # 查询该时间段内已完成的日程
    schedules = (
        await session.scalars(
            select(Schedule).where(
                Schedule.user_id == user.id,
                Schedule.is_completed == True,
                Schedule.starts_at >= start,
                Schedule.starts_at < end,
            )
        )
    ).all()

    total_completed = len(schedules)

    # 按标签统计
    tag_count_map: dict[str, dict] = {}  # tag_id -> {tag_name, tag_color, count}
    untagged_count = 0

    for s in schedules:
        assocs = (
            await session.scalars(
                select(ScheduleTagAssociation).where(
                    ScheduleTagAssociation.schedule_id == s.id
                )
            )
        ).all()
        if not assocs:
            untagged_count += 1
        else:
            tag_ids = [a.tag_id for a in assocs]
            tags = (
                await session.scalars(
                    select(ScheduleTag).where(ScheduleTag.id.in_(tag_ids))
                )
            ).all()
            for t in tags:
                key = str(t.id)
                if key not in tag_count_map:
                    tag_count_map[key] = {
                        "tag_id": t.id,
                        "tag_name": t.name,
                        "tag_color": t.color,
                        "count": 0,
                    }
                tag_count_map[key]["count"] += 1

    tag_counts: list[TagCountItem] = []
    for item in tag_count_map.values():
        tag_counts.append(
            TagCountItem(
                tag_id=item["tag_id"],
                tag_name=item["tag_name"],
                tag_color=item["tag_color"],
                count=item["count"],
            )
        )
    if untagged_count > 0:
        tag_counts.append(
            TagCountItem(tag_id=None, tag_name="未分类", tag_color=None, count=untagged_count)
        )

    return ScheduleStatsOut(
        period=period,
        total_completed=total_completed,
        tag_counts=tag_counts,
    )


@router.get("/schedules/{schedule_id}", response_model=ScheduleOut)
async def get_schedule(
    schedule_id: uuid.UUID,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    schedule = await session.scalar(
        select(Schedule).where(
            Schedule.id == schedule_id, Schedule.user_id == user.id
        )
    )
    if not schedule:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found")
    return await _schedule_to_out(schedule, session)


@router.post("/schedules", response_model=ScheduleOut, status_code=status.HTTP_201_CREATED)
async def create_schedule(
    body: ScheduleCreate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    # validate folder belongs to user if provided
    if body.folder_id:
        folder = await session.scalar(
            select(ScheduleFolder).where(
                ScheduleFolder.id == body.folder_id,
                ScheduleFolder.user_id == user.id,
            )
        )
        if not folder:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Folder not found")

    tag_ids = body.tag_ids
    schedule = Schedule(
        user_id=user.id,
        folder_id=body.folder_id,
        title=body.title,
        description=body.description,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
    )
    session.add(schedule)
    await session.flush()  # get schedule.id

    await _set_schedule_tags(schedule.id, tag_ids, session)
    await session.commit()
    await session.refresh(schedule)
    return await _schedule_to_out(schedule, session)


@router.put("/schedules/{schedule_id}", response_model=ScheduleOut)
async def update_schedule(
    schedule_id: uuid.UUID,
    body: ScheduleUpdate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    schedule = await session.scalar(
        select(Schedule).where(
            Schedule.id == schedule_id, Schedule.user_id == user.id
        )
    )
    if not schedule:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found")

    if body.folder_id is not None:
        if body.folder_id != schedule.folder_id:
            # 允许设为 None（移除文件夹）
            if body.folder_id is not None:
                folder = await session.scalar(
                    select(ScheduleFolder).where(
                        ScheduleFolder.id == body.folder_id,
                        ScheduleFolder.user_id == user.id,
                    )
                )
                if not folder:
                    raise HTTPException(status.HTTP_404_NOT_FOUND, "Folder not found")
            schedule.folder_id = body.folder_id

    update_fields = ("title", "description", "starts_at", "ends_at", "is_completed")
    for field in update_fields:
        value = getattr(body, field, None)
        if value is not None:
            setattr(schedule, field, value)

    # 验证时间区间
    if schedule.ends_at <= schedule.starts_at:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ends_at must be after starts_at")

    if body.tag_ids is not None:
        await _set_schedule_tags(schedule.id, body.tag_ids, session)

    await session.commit()
    await session.refresh(schedule)
    return await _schedule_to_out(schedule, session)


@router.delete("/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    schedule_id: uuid.UUID,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    schedule = await session.scalar(
        select(Schedule).where(
            Schedule.id == schedule_id, Schedule.user_id == user.id
        )
    )
    if not schedule:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found")
    await session.delete(schedule)
    await session.commit()
    return None


@router.get("/media/tracks")
async def media_tracks(_: User = Depends(current_user)):
    return {"items": [{"id": "white-noise", "title": "White noise", "kind": "builtin", "url": None}]}

