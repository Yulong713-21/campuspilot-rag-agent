# CampusPilot 轻量服务器部署

> 当前可直接执行的 GitHub Actions、GHCR、Docker Compose、Caddy HTTPS、运行数据打包、验收和
> 回滚步骤见 [`CAMPUSPILOT_GITHUB_PRODUCTION_DEPLOYMENT.md`](CAMPUSPILOT_GITHUB_PRODUCTION_DEPLOYMENT.md)。

## 推荐拓扑

演示环境采用同域反向代理：Nginx 提供 Vue 静态文件，并将 `/api` 转发到
Java Gateway；Gateway 再访问 campus-service，campus-service 通过
`CAMPUSPILOT_AGENT_BASE_URL` 调用 Python Agent。Milvus、MySQL 和 Redis 可先
放在同一台演示服务器，数据增大后再拆分。

```text
Browser -> Nginx -> Java Gateway -> campus-service -> Python Agent
                                      |                 |
                                   MySQL/Redis        Milvus/LLM API
```

## Agent 配置接口

1. 从 `.env.server.example` 创建服务器私密配置，API Key 不进入 Git。
2. 使用 `CAMPUSPILOT_CORS_ORIGINS` 设置允许访问的前端域名，多个域名用逗号分隔。
3. 使用 `CAMPUSPILOT_AGENT_BASE_URL` 配置 Java 到 Python Agent 的地址。
4. 前端构建时通过 `VITE_API_BASE_URL` 配置 API 前缀；同域部署推荐 `/api`。

启动 Agent：

```powershell
.\scripts\run_agent_api.ps1 -BindHost 0.0.0.0 -Port 8010
```

Linux 上等价命令：

```bash
python -m uvicorn agent_runtime.api:app --app-dir src --host 0.0.0.0 --port 8010
```

## 健康检查

- `GET /health/live`：只判断进程是否存活，供容器或进程管理器探测。
- `GET /health/ready`：判断目录和检索器是否完成初始化，供负载均衡器决定是否接流量。
- `GET /health`：展示当前数据、检索和目标理解模式，供演示排障。

生产环境不要把 8010、8090、10010、19530、3306 和 6379 直接暴露到公网；
公网只开放 Nginx 的 80/443，内部服务通过安全组或本机网络互访。

## 最小资源

- LLM 使用第三方 API、Milvus 同机：建议至少 4 vCPU、8 GB 内存、100 GB SSD。
- Milvus 独立或使用托管向量库：应用机可从 2 vCPU、4 GB 起步。
- 本地运行 7B 模型不属于低成本演示部署，建议继续使用兼容 API。

上线前还需要补 TLS、域名、日志轮转、自动备份和密钥管理。中国大陆服务器绑定
公网域名通常还涉及备案；个人演示可先选择中国香港节点或只做临时 IP 验收。
