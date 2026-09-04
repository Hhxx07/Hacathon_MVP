import uuid
from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from .models import EventKind, TaskStatus


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class EventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    starts_at: datetime
    ends_at: datetime
    kind: EventKind = EventKind.EVENT
    # source/external_id are used by campus connectors for idempotent upserts.
    # They remain optional so manually-created events keep the original API.
    source: str = Field(default="manual", min_length=1, max_length=50)
    external_id: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_range(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class EventOut(EventCreate, ORMModel):
    id: uuid.UUID


class EventUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    kind: EventKind | None = None
    source: str | None = Field(default=None, min_length=1, max_length=50)
    external_id: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_range(self):
        if self.starts_at is not None and self.ends_at is not None and self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class EventSyncItem(BaseModel):
    """An item produced by a campus connector.

    Campus connectors use ``task`` for deadlines, while the core calendar
    stores the normalized ``deadline`` enum value.
    """

    external_id: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    kind: EventKind | str = EventKind.EVENT
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    due_at: datetime | None = None

    @model_validator(mode="after")
    def normalize_and_validate(self):
        if isinstance(self.kind, str):
            value = self.kind.lower()
            if value == "task":
                self.kind = EventKind.DEADLINE
            else:
                try:
                    self.kind = EventKind(value)
                except ValueError as exc:
                    raise ValueError("kind must be event, course, deadline, or task") from exc
        if self.starts_at is None and self.due_at is not None:
            self.kind = EventKind.DEADLINE
            self.starts_at = self.due_at
        if self.ends_at is None and self.starts_at is not None:
            # A point-in-time deadline still needs a valid interval in the DB.
            self.ends_at = self.starts_at + timedelta(minutes=1)
        if self.starts_at is None or self.ends_at is None:
            raise ValueError("starts_at and ends_at (or due_at) are required")
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class EventSyncRequest(BaseModel):
    source: str = Field(default="campus", min_length=1, max_length=50)
    items: list[EventSyncItem] = Field(default_factory=list)


class EventSyncOut(BaseModel):
    source: str
    created: int
    updated: int
    total: int
    events: list[EventOut]


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    details: str | None = None
    due_at: datetime | None = None


class TaskOut(TaskCreate, ORMModel):
    id: uuid.UUID
    status: TaskStatus
    source: str


class FocusStart(BaseModel):
    planned_minutes: int = Field(default=25, ge=1, le=180)


class FocusOut(ORMModel):
    id: uuid.UUID
    planned_minutes: int
    started_at: datetime
    finished_at: datetime | None


class BalanceOut(BaseModel):
    balance: int


# ──────────────── Schedule Folder Schemas ────────────────


class ScheduleFolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ScheduleFolderUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ScheduleFolderOut(ORMModel):
    id: uuid.UUID
    name: str
    created_at: datetime


# ──────────────── Schedule Tag Schemas ────────────────


class ScheduleTagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class ScheduleTagUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class ScheduleTagOut(ORMModel):
    id: uuid.UUID
    name: str
    color: str | None
    created_at: datetime


# ──────────────── Schedule (日程) Schemas ────────────────


class ScheduleCreate(BaseModel):
    folder_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    starts_at: datetime
    ends_at: datetime
    tag_ids: list[uuid.UUID] = []

    @model_validator(mode="after")
    def validate_range(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class ScheduleUpdate(BaseModel):
    folder_id: uuid.UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    is_completed: bool | None = None
    tag_ids: list[uuid.UUID] | None = None

    @model_validator(mode="after")
    def validate_range(self):
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class ScheduleOut(ORMModel):
    id: uuid.UUID
    folder_id: uuid.UUID | None
    title: str
    description: str | None
    starts_at: datetime
    ends_at: datetime
    is_completed: bool
    tags: list[ScheduleTagOut] = []
    created_at: datetime


class CalendarEntryOut(EventOut):
    """Unified calendar representation for events and personal schedules."""

    is_completed: bool | None = None
    schedule_id: uuid.UUID | None = None
    folder_id: uuid.UUID | None = None
    tags: list[ScheduleTagOut] = []


# ──────────────── Schedule Stats Schemas ────────────────


class TagCountItem(BaseModel):
    tag_id: uuid.UUID | None = None  # None = 无标签
    tag_name: str
    tag_color: str | None = None
    count: int


class ScheduleStatsOut(BaseModel):
    period: str  # day / week / month / year
    total_completed: int
    tag_counts: list[TagCountItem]

