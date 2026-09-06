# Production deployment assets

- `docker-compose.yml` keeps PostgreSQL and Elasticsearch on the private
  Compose network and binds only `campuspilot` to `127.0.0.1:8010`.
- `deploy.sh` performs a fast-forward release, database migration, seed/rule
  smoke, lexical indexing, Standard verification, and automatic rollback.
- The active Nginx configuration is backed up and verified but not replaced.
- `verify.sh` validates health, frontend, the C6001 golden path, validation and evidence.
- `rollback.sh` restores the recorded immutable image and previous Nginx configuration.

After Standard passes, rebuild the semantic subset into the bind-mounted
Milvus Lite database, change the server-only `.env` to the Full profile, and
replace only the agent container. Milvus Lite is the lightweight single-server
choice, not a standalone Milvus Server.

The scripts use the repository-root `.env` without printing or overwriting it. See
[`docs/CAMPUSPILOT_SERVER_DEPLOYMENT.md`](../../docs/CAMPUSPILOT_SERVER_DEPLOYMENT.md).

