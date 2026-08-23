# Production deployment assets

- `docker-compose.yml` runs one `campuspilot` container bound to `127.0.0.1:8010`.
- `nginx.conf` is installed as `/etc/nginx/sites-available/campuspilot` only after backup.
- `deploy.sh` performs a fast-forward release with automatic runtime rollback.
- `verify.sh` validates health, frontend, the C6001 golden path, validation and evidence.
- `rollback.sh` restores the recorded immutable image and previous Nginx configuration.

The scripts use the repository-root `.env` without printing or overwriting it. See
[`docs/CAMPUSPILOT_SERVER_DEPLOYMENT.md`](../../docs/CAMPUSPILOT_SERVER_DEPLOYMENT.md).

