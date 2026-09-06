"""add course offerings and deterministic rule indexes

Revision ID: d3a8f5c1e902
Revises: b7e4f2a91c08
Create Date: 2026-09-04 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d3a8f5c1e902"
down_revision: Union[str, Sequence[str], None] = "b7e4f2a91c08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PROGRAM_RULE_UNIQUE_INDEXES = (
    (
        "uq_requirement_groups_program_rule",
        "requirement_groups",
        ["program_version_id", "code"],
        "specialisation_id IS NULL",
    ),
    (
        "uq_prerequisite_groups_program_rule",
        "prerequisite_groups",
        ["program_version_id", "course_id", "group_index"],
        "specialisation_id IS NULL",
    ),
    (
        "uq_course_exclusions_program_rule",
        "course_exclusions",
        ["program_version_id", "course_id", "excluded_course_id"],
        "specialisation_id IS NULL",
    ),
)


def upgrade() -> None:
    """Add version-scoped offerings and NULL-safe rule identities."""
    op.create_table(
        "course_offerings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("course_version_id", sa.Integer(), nullable=False),
        sa.Column("teaching_period", sa.String(length=32), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["course_version_id"],
            ["course_versions.id"],
            name=op.f(
                "fk_course_offerings_course_version_id_course_versions"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_course_offerings")),
        sa.UniqueConstraint(
            "course_version_id",
            "teaching_period",
            name="uq_course_offerings_version_period",
        ),
    )
    op.create_index(
        "ix_prerequisite_groups_scope_course",
        "prerequisite_groups",
        ["program_version_id", "specialisation_id", "course_id"],
        unique=False,
    )

    # SQL UNIQUE treats nullable specialisation IDs differently from the
    # program-wide semantic identity. Partial indexes model both scopes, with
    # SQLite support retained for the lightweight migration tests.
    dialect = op.get_bind().dialect.name
    if dialect not in {"postgresql", "sqlite"}:
        return
    for name, table_name, columns, predicate in PROGRAM_RULE_UNIQUE_INDEXES:
        where = sa.text(predicate)
        op.create_index(
            name,
            table_name,
            columns,
            unique=True,
            postgresql_where=where,
            sqlite_where=where,
        )


def downgrade() -> None:
    """Remove Phase 2 objects in reverse dependency order."""
    dialect = op.get_bind().dialect.name
    if dialect in {"postgresql", "sqlite"}:
        for name, table_name, _, _ in reversed(
            PROGRAM_RULE_UNIQUE_INDEXES
        ):
            op.drop_index(name, table_name=table_name)

    op.drop_index(
        "ix_prerequisite_groups_scope_course",
        table_name="prerequisite_groups",
    )
    op.drop_table("course_offerings")
