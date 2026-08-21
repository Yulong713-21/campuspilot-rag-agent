"""add admission criteria

Revision ID: 9c2d771a4fd1
Revises: 49badc8f2e42
Create Date: 2026-08-01 17:45:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9c2d771a4fd1"
down_revision: Union[str, Sequence[str], None] = "49badc8f2e42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admission_criteria",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("program_version_id", sa.Integer(), nullable=False),
        sa.Column("pathway_code", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("duration_months", sa.Integer(), nullable=True),
        sa.Column("credits_to_complete", sa.Integer(), nullable=True),
        sa.Column("minimum_average_percent", sa.Float(), nullable=True),
        sa.Column("criteria_text", sa.Text(), nullable=False),
        sa.Column("requirements", sa.JSON(), nullable=False),
        sa.Column("alternative_pathways", sa.JSON(), nullable=False),
        sa.Column("available_intakes", sa.JSON(), nullable=False),
        sa.Column("source_url", sa.String(length=512), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "credits_to_complete IS NULL OR credits_to_complete > 0",
            name=op.f("ck_admission_criteria_positive_admission_credits"),
        ),
        sa.CheckConstraint(
            "duration_months IS NULL OR duration_months > 0",
            name=op.f("ck_admission_criteria_positive_admission_duration"),
        ),
        sa.ForeignKeyConstraint(
            ["program_version_id"],
            ["program_versions.id"],
            name=op.f("fk_admission_criteria_program_version_id_program_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admission_criteria")),
        sa.UniqueConstraint(
            "program_version_id",
            "pathway_code",
            name="uq_admission_criteria_version_pathway",
        ),
    )
    op.create_index(
        op.f("ix_admission_criteria_program_version_id"),
        "admission_criteria",
        ["program_version_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_admission_criteria_program_version_id"),
        table_name="admission_criteria",
    )
    op.drop_table("admission_criteria")
