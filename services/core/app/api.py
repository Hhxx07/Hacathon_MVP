import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .models import CalendarEvent, FocusSession, RewardLedger, Task, User
from .schemas import (
    BalanceOut,
    EventCreate,
    EventOut,
    FocusOut,
    FocusStart,
    LoginRequest,
    RegisterRequest,
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
async def list_events(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    result = await session.scalars(
        select(CalendarEvent).where(CalendarEvent.user_id == user.id).order_by(CalendarEvent.starts_at)
    )
    return list(result)


@router.post("/events", response_model=EventOut, status_code=status.HTTP_201_CREATED)
async def create_event(body: EventCreate, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    event = CalendarEvent(user_id=user.id, **body.model_dump())
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return event


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


@router.get("/media/tracks")
async def media_tracks(_: User = Depends(current_user)):
    return {"items": [{"id": "white-noise", "title": "White noise", "kind": "builtin", "url": None}]}

