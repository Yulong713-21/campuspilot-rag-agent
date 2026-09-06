# CampusPilot local PostgreSQL

This service contains only PostgreSQL. It is independent from Milvus and does
not require Elasticsearch or an LLM.

```powershell
docker compose -f deploy/postgres/docker-compose.yml up -d
$env:DATABASE_URL="postgresql+psycopg://campuspilot:campuspilot@localhost:5432/campuspilot"
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe scripts\seed_campuspilot_domain.py
$env:VECTOR_SEARCH="0"
.\.venv\Scripts\python.exe scripts\smoke_postgres_rules.py
```

Run the seed command again to verify that the known fixture is detected and no
duplicate records are inserted.
