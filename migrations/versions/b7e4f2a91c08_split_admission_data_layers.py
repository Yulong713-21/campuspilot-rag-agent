"""split admission data layers

Revision ID: b7e4f2a91c08
Revises: 9c2d771a4fd1
Create Date: 2026-08-01 18:20:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7e4f2a91c08"
down_revision: Union[str, Sequence[str], None] = "9c2d771a4fd1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admission_evidence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_key", sa.String(length=160), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("source_url", sa.String(length=512), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("applicable_year", sa.Integer(), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("evidence_grade", sa.String(length=24), nullable=False),
        sa.Column("review_status", sa.String(length=32), nullable=False),
        sa.Column("hard_decision_allowed", sa.Boolean(), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admission_evidence")),
        sa.UniqueConstraint(
            "source_key",
            name=op.f("uq_admission_evidence_source_key"),
        ),
    )
    op.create_table(
        "program_catalog_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("program_version_id", sa.Integer(), nullable=False),
        sa.Column("faculty_name", sa.String(length=255), nullable=True),
        sa.Column("display_name_zh", sa.String(length=255), nullable=True),
        sa.Column("discipline_id", sa.String(length=64), nullable=False),
        sa.Column("coursework_master", sa.Boolean(), nullable=False),
        sa.Column("duration_months_min", sa.Integer(), nullable=True),
        sa.Column("duration_months_max", sa.Integer(), nullable=True),
        sa.Column("available_intakes", sa.JSON(), nullable=False),
        sa.Column("official_url", sa.String(length=512), nullable=False),
        sa.Column("release_stage", sa.String(length=40), nullable=False),
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
            ["program_version_id"],
            ["program_versions.id"],
            name=op.f(
                "fk_program_catalog_profiles_program_version_id_program_versions"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_program_catalog_profiles")),
        sa.UniqueConstraint(
            "program_version_id",
            name=op.f("uq_program_catalog_profiles_program_version_id"),
        ),
    )
    op.create_index(
        op.f("ix_program_catalog_profiles_program_version_id"),
        "program_catalog_profiles",
        ["program_version_id"],
        unique=True,
    )
    op.create_table(
        "admission_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("criterion_id", sa.Integer(), nullable=False),
        sa.Column("evidence_id", sa.Integer(), nullable=False),
        sa.Column("rule_code", sa.String(length=80), nullable=False),
        sa.Column("applicant_condition", sa.JSON(), nullable=False),
        sa.Column("metric_type", sa.String(length=40), nullable=False),
        sa.Column("minimum_value", sa.Float(), nullable=True),
        sa.Column("scale_max", sa.Float(), nullable=True),
        sa.Column("applicable_intakes", sa.JSON(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
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
            "minimum_value IS NULL OR minimum_value >= 0",
            name=op.f("ck_admission_rules_non_negative_admission_minimum"),
        ),
        sa.ForeignKeyConstraint(
            ["criterion_id"],
            ["admission_criteria.id"],
            name=op.f("fk_admission_rules_criterion_id_admission_criteria"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["admission_evidence.id"],
            name=op.f("fk_admission_rules_evidence_id_admission_evidence"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admission_rules")),
        sa.UniqueConstraint(
            "criterion_id",
            "rule_code",
            name=op.f("uq_admission_rules_criterion_id"),
        ),
    )
    op.create_index(
        op.f("ix_admission_rules_criterion_id"),
        "admission_rules",
        ["criterion_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admission_rules_evidence_id"),
        "admission_rules",
        ["evidence_id"],
        unique=False,
    )
    op.create_table(
        "alternative_admission_pathways",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("program_version_id", sa.Integer(), nullable=False),
        sa.Column("evidence_id", sa.Integer(), nullable=False),
        sa.Column("pathway_code", sa.String(length=80), nullable=False),
        sa.Column("pathway_type", sa.String(length=48), nullable=False),
        sa.Column("official_compensation", sa.Boolean(), nullable=False),
        sa.Column("duration_months", sa.Integer(), nullable=True),
        sa.Column("tuition_amount", sa.Float(), nullable=True),
        sa.Column("tuition_currency", sa.String(length=3), nullable=True),
        sa.Column("progression_conditions", sa.JSON(), nullable=False),
        sa.Column("applicable_intakes", sa.JSON(), nullable=False),
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
            ["evidence_id"],
            ["admission_evidence.id"],
            name=op.f(
                "fk_alternative_admission_pathways_evidence_id_admission_evidence"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["program_version_id"],
            ["program_versions.id"],
            name=op.f(
                "fk_alternative_admission_pathways_program_version_id_program_versions"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_alternative_admission_pathways"),
        ),
        sa.UniqueConstraint(
            "program_version_id",
            "pathway_code",
            name=op.f("uq_alternative_admission_pathways_program_version_id"),
        ),
    )
    op.create_index(
        op.f("ix_alternative_admission_pathways_evidence_id"),
        "alternative_admission_pathways",
        ["evidence_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_alternative_admission_pathways_program_version_id"),
        "alternative_admission_pathways",
        ["program_version_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_alternative_admission_pathways_program_version_id"),
        table_name="alternative_admission_pathways",
    )
    op.drop_index(
        op.f("ix_alternative_admission_pathways_evidence_id"),
        table_name="alternative_admission_pathways",
    )
    op.drop_table("alternative_admission_pathways")
    op.drop_index(
        op.f("ix_admission_rules_evidence_id"),
        table_name="admission_rules",
    )
    op.drop_index(
        op.f("ix_admission_rules_criterion_id"),
        table_name="admission_rules",
    )
    op.drop_table("admission_rules")
    op.drop_index(
        op.f("ix_program_catalog_profiles_program_version_id"),
        table_name="program_catalog_profiles",
    )
    op.drop_table("program_catalog_profiles")
    op.drop_table("admission_evidence")
