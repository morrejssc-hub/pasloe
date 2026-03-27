"""add domain detail tables

Revision ID: 9f5c2d1b7a44
Revises: 4d7e6f5a2c11
Create Date: 2026-03-26 12:30:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9f5c2d1b7a44"
down_revision: Union[str, Sequence[str], None] = "4d7e6f5a2c11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid_type(dialect_name: str):
    if dialect_name == "postgresql":
        from sqlalchemy.dialects import postgresql

        return postgresql.UUID(as_uuid=False)
    return sa.String()


def upgrade() -> None:
    dialect_name = op.get_bind().dialect.name
    uuid_type = _uuid_type(dialect_name)

    op.create_table(
        "detail_jobs",
        sa.Column("event_id", uuid_type, sa.ForeignKey("events.id"), primary_key=True),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=True),
        sa.Column("role", sa.String(), nullable=True),
        sa.Column("team", sa.String(), nullable=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("code", sa.String(), nullable=True),
        sa.Column("summary", sa.String(), nullable=True),
        sa.Column("git_ref", sa.String(), nullable=True),
    )
    op.create_index("idx_detail_jobs_job_id", "detail_jobs", ["job_id"], unique=False)
    op.create_index("idx_detail_jobs_task_id", "detail_jobs", ["task_id"], unique=False)
    op.create_index("idx_detail_jobs_role", "detail_jobs", ["role"], unique=False)
    op.create_index("idx_detail_jobs_team", "detail_jobs", ["team"], unique=False)
    op.create_index("idx_detail_jobs_state", "detail_jobs", ["state"], unique=False)

    op.create_table(
        "detail_tasks",
        sa.Column("event_id", uuid_type, sa.ForeignKey("events.id"), primary_key=True),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("parent_id", sa.String(), nullable=True),
        sa.Column("goal", sa.String(), nullable=True),
        sa.Column("team", sa.String(), nullable=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
    )
    op.create_index("idx_detail_tasks_task_id", "detail_tasks", ["task_id"], unique=False)
    op.create_index("idx_detail_tasks_team", "detail_tasks", ["team"], unique=False)
    op.create_index("idx_detail_tasks_state", "detail_tasks", ["state"], unique=False)

    op.create_table(
        "detail_llm",
        sa.Column("event_id", uuid_type, sa.ForeignKey("events.id"), primary_key=True),
        sa.Column("job_id", sa.String(), nullable=True),
        sa.Column("task_id", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=True),
        sa.Column("finish_reason", sa.String(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("cost_estimate", sa.Float(), nullable=True),
    )
    op.create_index("idx_detail_llm_job_id", "detail_llm", ["job_id"], unique=False)
    op.create_index("idx_detail_llm_task_id", "detail_llm", ["task_id"], unique=False)
    op.create_index("idx_detail_llm_model", "detail_llm", ["model"], unique=False)
    op.create_index("idx_detail_llm_state", "detail_llm", ["state"], unique=False)

    op.create_table(
        "detail_tools",
        sa.Column("event_id", uuid_type, sa.ForeignKey("events.id"), primary_key=True),
        sa.Column("job_id", sa.String(), nullable=True),
        sa.Column("task_id", sa.String(), nullable=True),
        sa.Column("tool_name", sa.String(), nullable=True),
        sa.Column("tool_call_id", sa.String(), nullable=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
    )
    op.create_index("idx_detail_tools_job_id", "detail_tools", ["job_id"], unique=False)
    op.create_index("idx_detail_tools_task_id", "detail_tools", ["task_id"], unique=False)
    op.create_index("idx_detail_tools_tool_name", "detail_tools", ["tool_name"], unique=False)
    op.create_index("idx_detail_tools_tool_call_id", "detail_tools", ["tool_call_id"], unique=False)
    op.create_index("idx_detail_tools_state", "detail_tools", ["state"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_detail_tools_state", table_name="detail_tools")
    op.drop_index("idx_detail_tools_tool_call_id", table_name="detail_tools")
    op.drop_index("idx_detail_tools_tool_name", table_name="detail_tools")
    op.drop_index("idx_detail_tools_task_id", table_name="detail_tools")
    op.drop_index("idx_detail_tools_job_id", table_name="detail_tools")
    op.drop_table("detail_tools")

    op.drop_index("idx_detail_llm_state", table_name="detail_llm")
    op.drop_index("idx_detail_llm_model", table_name="detail_llm")
    op.drop_index("idx_detail_llm_task_id", table_name="detail_llm")
    op.drop_index("idx_detail_llm_job_id", table_name="detail_llm")
    op.drop_table("detail_llm")

    op.drop_index("idx_detail_tasks_state", table_name="detail_tasks")
    op.drop_index("idx_detail_tasks_team", table_name="detail_tasks")
    op.drop_index("idx_detail_tasks_task_id", table_name="detail_tasks")
    op.drop_table("detail_tasks")

    op.drop_index("idx_detail_jobs_state", table_name="detail_jobs")
    op.drop_index("idx_detail_jobs_team", table_name="detail_jobs")
    op.drop_index("idx_detail_jobs_role", table_name="detail_jobs")
    op.drop_index("idx_detail_jobs_task_id", table_name="detail_jobs")
    op.drop_index("idx_detail_jobs_job_id", table_name="detail_jobs")
    op.drop_table("detail_jobs")
