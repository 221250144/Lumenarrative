"""Accounts, explicit legacy ownership, and project deletion markers."""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("username", sa.String(32), nullable=False),
        sa.Column("password_hash", sa.String(256), nullable=False))
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_table("auth_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.Float(), nullable=False))
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_token_hash", "auth_sessions", ["token_hash"], unique=True)
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    # ADD nullable REFERENCES is supported without rebuilding SQLite's parent
    # table, preserving the many existing foreign keys to projects.
    if op.get_bind().dialect.name == "sqlite":
        op.execute("ALTER TABLE projects ADD COLUMN owner_id VARCHAR(36) REFERENCES users(id)")
    else:
        op.add_column("projects", sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", name="fk_projects_owner_id_users"), nullable=True))
    op.add_column("projects", sa.Column("deleted_at", sa.String(), nullable=True))
    op.create_index("ix_projects_owner_id", "projects", ["owner_id"])


def downgrade():
    raise RuntimeError("账号隔离迁移不可自动回退；请恢复迁移前数据库备份")
