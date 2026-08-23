from __future__ import annotations

from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOY_ROOT = REPO_ROOT / "deploy" / "production"


class ProductionDeploymentTest(unittest.TestCase):
    def test_compose_keeps_fastapi_private_and_low_resource(self) -> None:
        compose = (DEPLOY_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn('container_name: campuspilot', compose)
        self.assertIn('restart: unless-stopped', compose)
        self.assertIn('"127.0.0.1:8010:8010"', compose)
        self.assertNotIn('"0.0.0.0:8010:8010"', compose)
        self.assertNotIn('caddy:', compose)
        self.assertNotIn('CAMPUSPILOT_RERANKER_ENABLED: "1"', compose)
        self.assertIn('max-size: "10m"', compose)
        self.assertIn('max-file: "5"', compose)

    def test_nginx_proxies_only_to_loopback(self) -> None:
        nginx = (DEPLOY_ROOT / "nginx.conf").read_text(encoding="utf-8")

        self.assertIn("proxy_pass http://127.0.0.1:8010;", nginx)
        self.assertIn("client_max_body_size 25M;", nginx)
        self.assertIn("proxy_read_timeout 120s;", nginx)

    def test_release_scripts_enforce_health_and_rollback(self) -> None:
        deploy = (DEPLOY_ROOT / "deploy.sh").read_text(encoding="utf-8")
        verify = (DEPLOY_ROOT / "verify.sh").read_text(encoding="utf-8")
        rollback = (DEPLOY_ROOT / "rollback.sh").read_text(encoding="utf-8")

        self.assertIn("git merge --ff-only origin/main", deploy)
        self.assertIn("docker build", deploy)
        self.assertIn('--build-arg "GIT_SHA=$CANDIDATE_SHA"', deploy)
        self.assertIn('cp -a "$BACKUP_DIR/logs/." "$RUNTIME_DIR/logs/"', deploy)
        self.assertIn("nginx -t", deploy)
        self.assertIn('"$SCRIPT_DIR/rollback.sh"', deploy)
        self.assertNotIn("docker system prune", deploy)
        self.assertIn("/api/plans/generate", verify)
        self.assertIn("expected three plans", verify)
        self.assertIn("official evidence links are missing", verify)
        self.assertIn('item.get("url")', verify)
        self.assertIn("PREVIOUS_IMAGE", rollback)
        self.assertIn("/health/ready", rollback)
        self.assertIn("stable cross-version contract", rollback)
        self.assertIn("/api/plans/generate", rollback)
        self.assertNotIn('"$SCRIPT_DIR/verify.sh"', rollback)

    def test_image_and_status_collection_expose_safe_revision_data(self) -> None:
        dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
        status_script = (
            REPO_ROOT / "scripts" / "ops" / "collect_runtime_status.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("ARG GIT_SHA=unknown", dockerfile)
        self.assertIn("CAMPUSPILOT_GIT_SHA=$GIT_SHA", dockerfile)
        self.assertIn("/health/live", status_script)
        self.assertIn("/health/ready", status_script)
        self.assertIn("/health", status_script)
        self.assertIn('docker logs --tail 100 "$APP_NAME"', status_script)
        self.assertNotIn("printenv", status_script)
        self.assertNotIn("docker inspect", status_script)
        self.assertNotIn(".env", status_script)


if __name__ == "__main__":
    unittest.main()
