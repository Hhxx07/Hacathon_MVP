"""Initial schema."""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("users", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("email", sa.String(320), nullable=False), sa.Column("password_hash", sa.String(255), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("email"))
    op.create_index("ix_users_email", "users", ["email"])
    op.create_table("calendar_events", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("title", sa.String(200), nullable=False), sa.Column("description", sa.Text()), sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False), sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False), sa.Column("kind", sa.Enum("EVENT", "COURSE", "DEADLINE", name="eventkind"), nullable=False), sa.Column("source", sa.String(50), nullable=False), sa.Column("external_id", sa.String(255)), sa.UniqueConstraint("user_id", "source", "external_id"))
    op.create_index("ix_calendar_events_user_id", "calendar_events", ["user_id"])
    op.create_index("ix_calendar_events_starts_at", "calendar_events", ["starts_at"])
    op.create_table("tasks", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("title", sa.String(200), nullable=False), sa.Column("details", sa.Text()), sa.Column("due_at", sa.DateTime(timezone=True)), sa.Column("status", sa.Enum("TODO", "DONE", name="taskstatus"), nullable=False), sa.Column("source", sa.String(50), nullable=False), sa.Column("external_id", sa.String(255)))
    op.create_index("ix_tasks_user_id", "tasks", ["user_id"])
    op.create_index("ix_tasks_due_at", "tasks", ["due_at"])
    op.create_table("focus_sessions", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("planned_minutes", sa.Integer(), nullable=False), sa.Column("started_at", sa.DateTime(timezone=True), nullable=False), sa.Column("finished_at", sa.DateTime(timezone=True)))
    op.create_index("ix_focus_sessions_user_id", "focus_sessions", ["user_id"])
    op.create_table("reward_ledger", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("amount", sa.Integer(), nullable=False), sa.Column("reason", sa.String(100), nullable=False), sa.Column("reference_id", sa.String(255), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("user_id", "reference_id"))
    op.create_index("ix_reward_ledger_user_id", "reward_ledger", ["user_id"])


def downgrade():
    for table in ("reward_ledger", "focus_sessions", "tasks", "calendar_events", "users"):
        op.drop_table(table)

