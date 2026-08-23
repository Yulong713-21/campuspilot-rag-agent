# CampusPilot 公网 Demo 部署

当前目标是单台 Ubuntu 24.04 服务器上的低资源、可回滚 HTTP Demo：

```text
Internet :80
  -> Nginx
  -> 127.0.0.1:8010
  -> one-worker FastAPI container
  -> structured catalog / SQLite
  -> optional Milvus Lite
  -> optional cloud LLM
```

FastAPI、SQLite 和 Milvus 不直接暴露公网。当前阶段不配置域名、HTTPS、Caddy 或额外中间件。

## 服务器布局

```text
/opt/campuspilot/
├── campuspilot-rag-agent/          # Git 仓库
│   ├── .env                        # 私密配置，不进入 Git
│   └── deploy/production/
│       └── runtime-data/           # ignored bind mounts
└── deploy-state/
    ├── previous.env                # 上一镜像与回滚元数据
    └── backups/<timestamp>/        # 日志与 Nginx 备份
```

## 首次准备

服务器仓库必须位于 `/opt/campuspilot/campuspilot-rag-agent`，处于干净的 `main` 分支。

```bash
cd /opt/campuspilot/campuspilot-rag-agent
cp .env.server.example .env
chmod 600 .env
```

编辑 `.env` 中的真实模型配置。部署脚本只检查变量名是否存在，不覆盖或打印值。

2 GB 内存服务器首次部署建议保持：

```env
CAMPUSPILOT_RETRIEVAL_MODE=catalog_bm25
CAMPUSPILOT_VECTOR_SEARCH_ENABLED=0
CAMPUSPILOT_RERANKER_ENABLED=0
```

此模式是明确的 degraded deployment：Planner、BM25 和 Evidence 可用，但 Milvus 与 reranker
未上线。只有准备好 Milvus Lite DB 与 MiniLM 模型并通过 smoke test 后才能启用 vector。

## 部署

```bash
cd /opt/campuspilot/campuspilot-rag-agent
sudo ./deploy/production/deploy.sh
```

脚本会：

1. 拒绝 dirty worktree 和非 `main` 分支；
2. 检查 `.env` 必需变量名；
3. fetch 并只允许 fast-forward；
4. 记录当前 SHA、镜像、日志与 Nginx 配置；
5. 构建 `campuspilot:<full-git-sha>` 和 `campuspilot:latest`；
6. 以单 worker、`127.0.0.1:8010`、日志轮转和 bind mounts 启动容器；
7. 验证 live、ready、health、前端、三套 Planner 方案和 Evidence；
8. 仅在 `nginx -t` 成功后 reload；
9. 验证本机 Nginx 与公网 IP。

公网失败不会破坏已经健康的应用和 Nginx。此时脚本会报告可能的云安全组问题，不修改 UFW、
SSH 或云厂商控制台。

## 手动验证

```bash
./deploy/production/verify.sh http://127.0.0.1:8010
./deploy/production/verify.sh http://127.0.0.1
./deploy/production/verify.sh http://43.108.32.225
```

Vector 关闭时输出 `WARN vector retrieval disabled`。Vector 开启时，readiness 必须为 true，
且 `/health` 的 retrieval mode 必须包含 `milvus`。

## 回滚

部署脚本在容器启动、live、ready 或 Planner 门禁失败后自动调用回滚。也可以手工执行：

```bash
sudo ./deploy/production/rollback.sh
```

回滚使用 `/opt/campuspilot/deploy-state/previous.env` 中记录的不可变旧镜像，恢复 Nginx 备份，
并重新验证应用与 Nginx。脚本不删除 Docker volume、旧镜像、数据库或备份。

## 诊断

```bash
docker ps -a
docker logs --tail 100 campuspilot
free -h
df -h /
nginx -t
```

不要把 `.env`、日志、数据库、Milvus 文件或模型权重提交到 Git。
