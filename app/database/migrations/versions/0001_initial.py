"""initial schema

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

BIG = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table("settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_table("application_preferences",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False))
    op.create_table("bot_accounts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("bot_id", sa.BigInteger(), nullable=True),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_table("channels",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.String(100), nullable=False, unique=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("categories", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("status_detail", sa.Text(), nullable=False),
        sa.Column("last_checked", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_table("authorized_users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("blocked", sa.Boolean(), nullable=False),
        sa.Column("daily_quota_mb", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_table("download_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("url_hash", sa.String(64), nullable=True),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("requester_id", sa.BigInteger(), nullable=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("filename", sa.Text(), nullable=True),
        sa.Column("category", sa.String(20), nullable=True),
        sa.Column("mime", sa.String(120), nullable=True),
        sa.Column("size_total", sa.BigInteger(), nullable=False),
        sa.Column("size_done", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(60), nullable=True),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("destinations", sa.Text(), nullable=False),
        sa.Column("caption_override", sa.Text(), nullable=True),
        sa.Column("awaiting_approval", sa.Boolean(), nullable=False),
        sa.Column("cleanup_status", sa.String(30), nullable=True),
        sa.Column("result", sa.String(60), nullable=True),
        sa.Column("meta", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True))
    op.create_index("ix_download_jobs_url_hash", "download_jobs", ["url_hash"])
    op.create_index("ix_download_jobs_status", "download_jobs", ["status"])
    op.create_index("ix_download_jobs_created_at", "download_jobs", ["created_at"])
    op.create_table("download_queue",
        sa.Column("job_id", sa.String(36), sa.ForeignKey("download_jobs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("enqueued_at", sa.DateTime(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(), nullable=True))
    op.create_table("publish_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("download_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_id", sa.Integer(), sa.ForeignKey("channels.id", ondelete="SET NULL"), nullable=True),
        sa.Column("channel_label", sa.String(200), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("method", sa.String(30), nullable=True),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("filetype", sa.String(20), nullable=True),
        sa.Column("filename", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=False))
    op.create_index("ix_publish_history_job_id", "publish_history", ["job_id"])
    op.create_index("ix_publish_history_sent_at", "publish_history", ["sent_at"])
    op.create_index("ix_publish_history_status", "publish_history", ["status"])
    op.create_table("content_fingerprints",
        sa.Column("sha256", sa.String(64), primary_key=True),
        sa.Column("channel_id", sa.Integer(), primary_key=True),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("first_seen", sa.DateTime(), nullable=False))
    op.create_table("activity_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(), nullable=False),
        sa.Column("actor_id", sa.BigInteger(), nullable=True),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False))
    op.create_index("ix_activity_logs_ts", "activity_logs", ["ts"])
    op.create_table("error_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(), nullable=False),
        sa.Column("component", sa.String(100), nullable=False),
        sa.Column("level", sa.String(20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False))
    op.create_index("ix_error_logs_ts", "error_logs", ["ts"])
    op.create_table("caption_templates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("template", sa.Text(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False))
    op.create_table("cleanup_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(36), nullable=True),
        sa.Column("ts", sa.DateTime(), nullable=False),
        sa.Column("reason", sa.String(30), nullable=False),
        sa.Column("files_removed", sa.Integer(), nullable=False),
        sa.Column("bytes_freed", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("note", sa.Text(), nullable=False))
    op.create_index("ix_cleanup_history_job_id", "cleanup_history", ["job_id"])
    op.create_index("ix_cleanup_history_ts", "cleanup_history", ["ts"])


def downgrade() -> None:
    for t in ("cleanup_history", "caption_templates", "error_logs", "activity_logs", "content_fingerprints",
              "publish_history", "download_queue", "download_jobs", "authorized_users", "channels",
              "bot_accounts", "application_preferences", "settings"):
        op.drop_table(t)
