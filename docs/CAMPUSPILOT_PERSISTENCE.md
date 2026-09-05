# CampusPilot deterministic persistence

## Responsibility boundary

- PostgreSQL is the authoritative store for versioned programs, courses,
  prerequisites, offerings, requirement groups, course roles, exclusions, and
  reviewed structured metadata.
- The deterministic Rule Engine reads those structured records through
  `DegreeAuditService`.
- RAG retrieves official source text for evidence and explanation. RAG cannot
  override a deterministic rule.
- Handbook raw text and embeddings do not belong in the rule database.

SQLite remains supported for unit tests and lightweight local checks. PyMySQL
remains installed only for legacy deployments. New production examples use
PostgreSQL through `DATABASE_URL`; `CAMPUSPILOT_DATABASE_URL` is the fallback
legacy alias.

## Version and stream scope

`ProgramVersion` owns `handbook_year`. `CourseVersion` owns both unit credit
points and the Handbook year used by `CourseOffering`. The existing
`Specialisation` model is the current study-stream equivalent.

For a selected specialisation, rule queries load:

1. program-wide rows where `specialisation_id IS NULL`;
2. rows where `specialisation_id` equals the selected specialisation.

Rows belonging to other specialisations are never included.

## Indexes and uniqueness

- Existing unique constraints on `(program_id, handbook_year)` and
  `(course_id, handbook_year)` support exact version lookup. Separate duplicate
  indexes were intentionally not added.
- `uq_course_offerings_version_period` both enforces offering identity and
  supports `(course_version_id, teaching_period)` lookup.
- `ix_prerequisite_groups_scope_course` supports prerequisite lookup by program
  version, specialisation, and target course.
- Existing `ix_requirement_groups_version_scope` supports program-wide plus
  specialisation-specific requirement loading.
- PostgreSQL and SQLite partial unique indexes cover program-wide requirement,
  prerequisite, and exclusion rows where `specialisation_id IS NULL`. Existing
  composite unique constraints continue to protect specialisation-specific
  rows where the ID is non-null.

This split fixes the SQL `NULL` uniqueness gap without replacing null with a
sentinel or changing rule meaning.
