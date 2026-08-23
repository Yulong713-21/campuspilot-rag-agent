# EduRAG 环境跑通 Runbook

## Runtime reliability and request tracing

Every API response includes `X-Request-ID`. A valid incoming `X-Request-ID` is
reused; otherwise the API creates one. Runtime events are JSON Lines and use the
same `request_id` across request, route, retrieval, Planner and LLM events.

Use the request ID returned to the client to isolate one request:

```bash
docker logs campuspilot 2>&1 | grep '"request_id":"REQUEST_ID"'
```

Debug in this order: `/health/live`, `/health/ready`, `/health`, the response
request ID, then container logs. Collect a safe status bundle with:

```bash
scripts/ops/collect_runtime_status.sh
```

The collector prints timestamps, the Git revision, container state, health
responses, memory, disk and the final 100 application log lines. It never reads
`.env`, dumps process environment variables or prints configured API keys.

Normalized public LLM failures are `LLM_RATE_LIMITED`,
`LLM_QUOTA_EXHAUSTED`, `LLM_TIMEOUT` and `LLM_UNAVAILABLE`. Transient rate,
timeout and upstream 5xx failures retry at most twice. Authentication, quota and
invalid-request failures are never retried. Configure the bound with
`CAMPUSPILOT_OPENAI_MAX_RETRIES=2` (allowed range: 0-2).

- `LLM_RATE_LIMITED`: the provider is throttling requests; retry later.
- `LLM_QUOTA_EXHAUSTED`: the configured account has no usable quota.
- `LLM_TIMEOUT`: the provider did not complete within the configured timeout.
- `LLM_UNAVAILABLE`: the provider, model, network or response is unavailable.

The deterministic Planner remains available when the LLM is unavailable.
Responses that use a deterministic fallback explicitly include degraded status
and a normalized reason; operations with no truthful fallback return a stable
non-2xx error containing the same request ID.

日期：2026-07-08

## CampusPilot 当前向量检索环境（2026-07-31）

当前 CampusPilot 使用独立 Milvus 栈，不复用天机学堂已有容器：

```text
虚拟机: 192.168.150.101
Milvus: 192.168.150.101:19530
Milvus 健康检查: http://192.168.150.101:9091/healthz
在线 Collection: campuspilot_handbook_v2
回滚 Collection: campuspilot_handbook_v1
轻量英文模型: D:\agentdev\models\all-MiniLM-L6-v2
BGE-M3 可选模型: D:\agentdev\models\bge-m3
Compose: deploy\milvus\docker-compose.yml
```

`D:\agentdev\models\bge-m3` 是指向实际模型目录的 NTFS Junction，不复制模型
文件。使用纯 ASCII 路径是为了避免 Windows PowerShell 5 读取无 BOM 脚本时
把中文路径解码为乱码。

启动带真实向量检索的 FastAPI：

```powershell
cd D:\agentdev\edurag-agent-lab
.\scripts\run_agent_api.ps1 -EnableVectorSearch
```

首次全量建库在 CPU 上耗时明显高于查询。生产思路是离线或增量生成文档
向量，在线服务常驻加载 embedding 模型；不能在每次请求或每次服务启动时
重新向量化全部 Handbook。

### Monash Handbook 全量样本流程

当前样本覆盖 39 个项目、2024 至 2026 三个 Handbook Year，以及这些项目正文
引用的 Unit。采集、提取和建库是三个独立状态，不能把下载成功当作已经入库。

```powershell
cd D:\agentdev\edurag-agent-lab

# 发现官方 Program，并合并 Manifest
.\.venv\Scripts\python.exe scripts\expand_monash_handbook_manifest.py

# 下载 Program 页面并提取正文
.\.venv\Scripts\python.exe scripts\download_handbook_sources.py --university-id monash
.\.venv\Scripts\python.exe scripts\extract_handbook_sources.py

# 从 Program 正文发现 Unit，低频分批下载
.\.venv\Scripts\python.exe scripts\expand_monash_unit_manifest.py
.\.venv\Scripts\python.exe scripts\download_monash_units.py `
  --workers 1 --requests-per-second 0.5 --max-items 100
.\.venv\Scripts\python.exe scripts\extract_handbook_sources.py

# 构建候选索引；验收后再切换在线 Collection
.\.venv\Scripts\python.exe scripts\build_handbook_vector_index.py `
  --collection campuspilot_handbook_v2
```

采集器对 404 记录为终态 `unavailable`，对网络抖动有限重试，遇到 403 或 429
立即熔断并取消剩余任务。需要恢复中断的建库时使用 `--resume`，脚本会先校验
Milvus 中已有 `chunk_id` 是否等于当前语料前缀，再继续编码。

## 1. 当前环境检查结果

已确认：

- 项目资料存在：`D:\BaiduNetdiskDownload\eduRAG项目资料\资料`
- 完整代码存在：`D:\BaiduNetdiskDownload\eduRAG项目资料\资料\完整代码\integrated_qa_system`
- `requirments.txt` 存在。
- Redis 正在监听：`127.0.0.1:6379`
- MySQL 正在监听：`127.0.0.1:3306` 和 `127.0.0.1:3307`
- 项目代码中 MySQL 端口硬编码为 `3307`，所以当前 `3307` 端口存在是好事。

待补齐：

- 当前只检测到 Python 3.13：`C:\Users\23524\AppData\Local\Programs\Python\Python313\python.exe`
- Docker 命令不可用。
- Milvus 没有监听：`127.0.0.1:19530` 不通。

## 2. 为什么不能直接用当前 Python 3.13

项目依赖包含：

- `torch==2.7.0`
- `transformers==4.51.3`
- `pymilvus==2.5.4`
- `sentence-transformers==4.1.0`
- `FlagEmbedding==1.3.4`
- `onnxruntime`
- `rapidocr`

这些 AI 工程依赖对 Python 版本比较敏感。课程资料里也要求 Python 3.10+，实战建议用 Python 3.10 或 3.11，避免 3.13 上出现依赖 wheel 不兼容、编译失败或运行异常。

推荐：

```text
Python 3.10.11 或 Python 3.11.x
```

## 3. 你需要先做的事

### 3.1 安装 Python 3.10 或 3.11

安装后确认：

```powershell
py -0p
```

期望看到类似：

```text
-V:3.10 ...
-V:3.13 ...
```

之后用 Python 3.10 创建虚拟环境：

```powershell
cd D:\agentdev\edurag-agent-lab
py -3.10 -m venv .venv
.\.venv\Scripts\activate
python --version
```

### 3.2 安装 Docker Desktop，或准备能跑 Milvus 的虚拟机

项目需要 Milvus，资料里提供了 Docker Compose：

```text
D:\BaiduNetdiskDownload\eduRAG项目资料\资料\milvus镜像\docker-compose.yml
```

如果用 Docker Desktop：

```powershell
cd D:\BaiduNetdiskDownload\eduRAG项目资料\资料\milvus镜像
docker load -i redis.tar
docker load -i minio.tar
docker load -i milvusdb.tar
docker load -i etcd.tar
docker compose up -d
```

启动后检查：

```powershell
docker ps
Test-NetConnection 127.0.0.1 -Port 19530
```

期望：

```text
TcpTestSucceeded : True
```

### 3.3 确认 MySQL

当前项目代码里写死：

```python
port=3307
```

所以先用 `3307` 跑，不急着改代码。

需要确认：

- MySQL root 密码是否是 `123456`
- 是否存在数据库 `subjects_kg`
- 能否创建 `jpkb` 表

后续我们会把端口硬编码改成配置项，这是一个工程清理任务。

### 3.4 确认 Redis

当前 Redis 已经在：

```text
127.0.0.1:6379
```

配置里密码是：

```text
1234
```

需要确认你的本地 Redis 是否确实设置了这个密码。如果没有密码，项目连接会失败。

## 4. Milvus 是当前最大 blocker

FAQ 路线只需要 MySQL + Redis。

完整 EduRAG 路线需要：

```text
MySQL + Redis + Milvus + DashScope API
```

没有 Milvus 时：

- FAQ/BM25 可以跑。
- RAG 知识库检索跑不了。
- `VectorStore()` 初始化会失败。
- 完整 API 启动时也可能因为初始化 `IntegratedQASystem()` 失败而启动不了。

## 4.1 使用课程虚拟机部署 Milvus

当前虚拟机信息：

```text
host: 192.168.100.128
user: root
password: 1234
```

已确认：

- Windows 到虚拟机 SSH 端口 `22` 可连通。
- `192.168.100.128:6379`、`192.168.100.128:19530`、`192.168.100.128:9091` 当前未连通，说明 Redis/Milvus 容器还没有启动，或端口没有暴露。

### 4.1.1 启动 Docker 服务

在虚拟机里执行：

```bash
systemctl start docker
systemctl enable docker
docker --version
docker compose version
```

如果 `docker compose version` 不可用，说明 compose 插件没有安装好，需要先安装 Docker Compose。

### 4.1.2 创建工作目录

```bash
mkdir -p /root/ai_workspace
cd /root/ai_workspace
```

### 4.1.3 上传镜像和 compose 文件

从 Windows 上传这些文件到虚拟机 `/root/ai_workspace`：

```text
D:\BaiduNetdiskDownload\eduRAG项目资料\资料\milvus镜像\redis.tar
D:\BaiduNetdiskDownload\eduRAG项目资料\资料\milvus镜像\etcd.tar
D:\BaiduNetdiskDownload\eduRAG项目资料\资料\milvus镜像\minio.tar
D:\BaiduNetdiskDownload\eduRAG项目资料\资料\milvus镜像\milvusdb.tar
D:\BaiduNetdiskDownload\eduRAG项目资料\资料\milvus镜像\docker-compose.yml
```

可以用 FinalShell / Xftp / scp 上传。

#### 方法 A：FinalShell 图形化上传

1. 打开 FinalShell。
2. 连接虚拟机：

```text
host: 192.168.100.128
user: root
password: 1234
```

3. 连接成功后，左侧或下方通常会有“文件管理器 / SFTP / 文件”面板。
4. 在远程目录输入或切换到：

```text
/root/ai_workspace
```

5. 在本机文件区找到：

```text
C:\edurag-milvus
```

如果还没有这个目录，先在 Windows PowerShell 执行：

```powershell
New-Item -ItemType Directory -Force C:\edurag-milvus
Copy-Item "D:\BaiduNetdiskDownload\eduRAG项目资料\资料\milvus镜像\redis.tar" C:\edurag-milvus\
Copy-Item "D:\BaiduNetdiskDownload\eduRAG项目资料\资料\milvus镜像\etcd.tar" C:\edurag-milvus\
Copy-Item "D:\BaiduNetdiskDownload\eduRAG项目资料\资料\milvus镜像\minio.tar" C:\edurag-milvus\
Copy-Item "D:\BaiduNetdiskDownload\eduRAG项目资料\资料\milvus镜像\milvusdb.tar" C:\edurag-milvus\
Copy-Item "D:\BaiduNetdiskDownload\eduRAG项目资料\资料\milvus镜像\docker-compose.yml" C:\edurag-milvus\
```

6. 选中 `C:\edurag-milvus` 中的 5 个文件，拖到远程目录 `/root/ai_workspace`。
7. 等待上传完成。`milvusdb.tar` 有 500MB 左右，上传会比较慢。
8. 上传完成后在虚拟机终端执行：

```bash
cd /root/ai_workspace
ls -lh
```

#### 方法 B：PowerShell 使用 scp 上传

如果 C 盘空间不足，不要复制到 `C:\edurag-milvus`。可以直接从 D 盘原路径上传：

```powershell
scp "D:\BaiduNetdiskDownload\eduRAG项目资料\资料\milvus镜像\redis.tar" root@192.168.100.128:/root/ai_workspace/
scp "D:\BaiduNetdiskDownload\eduRAG项目资料\资料\milvus镜像\etcd.tar" root@192.168.100.128:/root/ai_workspace/
scp "D:\BaiduNetdiskDownload\eduRAG项目资料\资料\milvus镜像\minio.tar" root@192.168.100.128:/root/ai_workspace/
scp "D:\BaiduNetdiskDownload\eduRAG项目资料\资料\milvus镜像\milvusdb.tar" root@192.168.100.128:/root/ai_workspace/
scp "D:\BaiduNetdiskDownload\eduRAG项目资料\资料\milvus镜像\docker-compose.yml" root@192.168.100.128:/root/ai_workspace/
```

如果工具处理中文路径不稳定，再考虑复制到 D 盘英文目录：

```powershell
New-Item -ItemType Directory -Force D:\edurag-milvus
Copy-Item "D:\BaiduNetdiskDownload\eduRAG项目资料\资料\milvus镜像\redis.tar" D:\edurag-milvus\
Copy-Item "D:\BaiduNetdiskDownload\eduRAG项目资料\资料\milvus镜像\etcd.tar" D:\edurag-milvus\
Copy-Item "D:\BaiduNetdiskDownload\eduRAG项目资料\资料\milvus镜像\minio.tar" D:\edurag-milvus\
Copy-Item "D:\BaiduNetdiskDownload\eduRAG项目资料\资料\milvus镜像\milvusdb.tar" D:\edurag-milvus\
Copy-Item "D:\BaiduNetdiskDownload\eduRAG项目资料\资料\milvus镜像\docker-compose.yml" D:\edurag-milvus\
```

然后上传：

```powershell
scp D:\edurag-milvus\redis.tar root@192.168.100.128:/root/ai_workspace/
scp D:\edurag-milvus\etcd.tar root@192.168.100.128:/root/ai_workspace/
scp D:\edurag-milvus\minio.tar root@192.168.100.128:/root/ai_workspace/
scp D:\edurag-milvus\milvusdb.tar root@192.168.100.128:/root/ai_workspace/
scp D:\edurag-milvus\docker-compose.yml root@192.168.100.128:/root/ai_workspace/
```

如果提示：

```text
Are you sure you want to continue connecting?
```

输入：

```text
yes
```

密码输入：

```text
1234
```

如果出现：

```text
Host key verification failed
```

先执行：

```powershell
ssh-keygen -R 192.168.100.128
```

再重新执行 `scp`。

### 4.1.4 加载 Docker 镜像

加载前一定先确认文件已经在虚拟机当前目录：

```bash
cd /root/ai_workspace
pwd
ls -lh
```

目录中必须能看到：

```text
redis.tar
etcd.tar
minio.tar
milvusdb.tar
docker-compose.yml
```

如果 `ls -lh` 看不到这些文件，说明还没有上传成功，继续执行 `docker load` 一定会报：

```text
open redis.tar: no such file or directory
```

注意：不要使用这种写法：

```bash
docker load -i redis.tar | docker load -i etcd.tar | docker load -i minio.tar | docker load -i milvusdb.tar
```

`|` 是管道，会把前一个命令的输出传给后一个命令，不适合这里。

推荐逐条执行：

```bash
docker load -i redis.tar
docker load -i etcd.tar
docker load -i minio.tar
docker load -i milvusdb.tar
```

或者：

```bash
docker load -i redis.tar && \
docker load -i etcd.tar && \
docker load -i minio.tar && \
docker load -i milvusdb.tar
```

命令中 `load` 和 `-i` 之间必须有空格，不能写成：

```bash
docker load_-i redis.tar
```

检查镜像：

```bash
docker images
```

### 4.1.5 启动 Milvus 和 Redis

确认 `/root/ai_workspace/docker-compose.yml` 存在后：

```bash
cd /root/ai_workspace
docker compose up -d
docker ps
```

正常情况下应看到：

```text
milvus-etcd
milvus-minio
milvus-standalone
milvus-redis
```

### 4.1.6 在 Windows 上检查端口

回到 Windows PowerShell 执行：

```powershell
Test-NetConnection 192.168.100.128 -Port 6379
Test-NetConnection 192.168.100.128 -Port 19530
Test-NetConnection 192.168.100.128 -Port 9091
```

期望：

```text
TcpTestSucceeded : True
```

如果虚拟机内 `docker ps` 正常，但 Windows 仍无法连接端口，检查：

- 虚拟机防火墙。
- VMware 网络模式。
- Docker compose 是否映射了端口。

临时关闭 CentOS 防火墙可执行：

```bash
systemctl stop firewalld
systemctl disable firewalld
```

生产环境不建议直接关闭防火墙，课程本地环境可以先这样排查。

## 5. 后续我们会做的动作

等 Python 3.10/3.11 和 Milvus 就绪后：

1. 复制完整项目代码到 `D:\agentdev\edurag-agent-lab\src\integrated_qa_system`
2. 创建虚拟环境。
3. 安装依赖。
4. 修正 `config.ini`：

```ini
[mysql]
host = 127.0.0.1
user = root
password = 123456
database = subjects_kg

[redis]
host = 127.0.0.1
port = 6379
password = 1234
db = 0

[milvus]
host = 127.0.0.1
port = 19530
database_name = itcast
collection_name = edurag_final
```

5. 配置 DashScope API Key。
6. 初始化 MySQL FAQ。
7. 初始化 Milvus 知识库。
8. 启动 FastAPI。
9. 测试 FAQ 和 RAG 两条链路。

## 6. 当前待办

- [x] 确认课程虚拟机可用：`192.168.100.128`。
- [x] 上传 Milvus/Redis 镜像到虚拟机。
- [x] 启动 Docker Compose 服务。
- [x] 项目正常运行。
- [x] 测试正常通过。
- [ ] 记录一次完整启动命令和测试命令。
- [ ] 进入 Tool Calling 改造阶段。

## 7. 环境跑通记录

当前状态：

```text
EduRAG 原项目已正常运行，测试已正常通过。
```

当前实际运行路径：

```text
D:\agentdev\integrated_qa_system
```

当前服务地址：

```text
http://127.0.0.1:8000/
```

当前外部服务：

```text
Milvus: 192.168.100.128:19530
Redis: 192.168.100.128:6379
MySQL: 192.168.100.128:3306
```

Agent 学习仓库虚拟环境：

```text
D:\agentdev\edurag-agent-lab\.venv
```

LangGraph 兼容版本：

```text
langchain==0.3.24
langchain-core==0.3.55
langgraph==0.3.34
langgraph-checkpoint-sqlite==2.0.11
```

注意：不要直接安装最新版 `langgraph`，它可能把 `langchain-core` 升级到 1.x，导致当前 LangChain 0.3.x 依赖冲突。

安装本地持久化实验依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-persistence.txt
```

当前项目的 LangGraph 要求 `langgraph-checkpoint<3.0.0`。不要直接安装
`langgraph-checkpoint-sqlite==3.1.0`，它会引入 checkpoint 4.x；整体升级需要
单独建立迁移分支并执行全量回归。

Ollama 本地模型：

```text
Ollama exe: C:\Users\23524\AppData\Local\Programs\Ollama\ollama.exe
OLLAMA_MODELS: D:\ollama-models
model: qwen3.5:0.8b
```

检查：

```powershell
& "C:\Users\23524\AppData\Local\Programs\Ollama\ollama.exe" list
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

从 D 盘模型目录启动 Ollama：

```powershell
.\scripts\start_ollama_d.ps1
```

也可以在 Windows 命令提示符中运行：

```cmd
scripts\start_ollama_d.cmd
```

启用 LangGraph 本地 LLM 生成：

```powershell
$env:EDURAG_USE_OLLAMA="1"
$env:EDURAG_OLLAMA_MODEL="qwen3.5:0.8b"
```

本地部署注意：

- Qwen3.5 支持 thinking，API 调用时使用 `think=false` 只要最终答案。
- 如果出现 KV cache / out-of-memory，降低 `num_ctx`。当前代码使用 `num_ctx=2048`。
- 如果 Ollama 读不到模型目录，重启 Ollama 进程，确保服务进程能读到 `OLLAMA_MODELS`。
- 修改用户级环境变量不会自动刷新已经运行的 Ollama 服务，必须重启服务进程。
- `qwen3.5:0.8b` 适合本地教学实验，不代表足以承担高风险生产门禁。

下一阶段不再优先处理环境问题，转入 Agent 化改造：

```text
FAQ/RAG 固定流程
  -> 工具封装
  -> Tool Calling Agent
  -> LangGraph 状态图
  -> Skills / MCP
```

## 最终本地小程序

安装：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-app.txt
```

启动：

```powershell
.\scripts\run_agent_api.ps1
```

地址：

```text
API: http://127.0.0.1:8010
Swagger: http://127.0.0.1:8010/docs
Health: http://127.0.0.1:8010/health
```

运行授权验收：

```powershell
.\.venv\Scripts\python.exe experiments\langgraph_minimal\fastapi_thread_authorization_demo.py `
  --thread-id acceptance-001
```

运行全部检查：

```powershell
.\scripts\run_project_checks.ps1
```

静态演示 token 只用于本地，生产环境必须替换为真实 OAuth2/OIDC/JWT 验证。
## 用户工作台

启动服务后访问：

```text
用户工作台：http://127.0.0.1:8010/
Swagger：http://127.0.0.1:8010/docs
健康检查：http://127.0.0.1:8010/health
```

根路径现在返回面向用户的审批页面，不再自动跳转 Swagger。

## CampusPilot 学期建议 Agent

推荐本地模型：

```powershell
ollama pull qwen3.5:2b-q4_K_M
```

同时启用混合检索和学期建议：

```powershell
.\scripts\run_agent_api.ps1 -EnableVectorSearch -EnableLlm
```

启动后不要只固定等待若干秒。BGE-M3 首次加载时间会随机器状态变化，应循环检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8010/health
```

返回 `status=ok` 后再启动联调请求。学期建议接口为
`POST /api/plans/semesters/explain`，Java 网关路径为
`POST /cps/plans/semesters/explain`。

## 阿里云百炼目标理解

复制 `.env.example` 为本机 `.env`，填写重置后的新 Key。不要把 Key 写进命令、
源码、截图、日志或 Git：

```dotenv
CAMPUSPILOT_CLOUD_LLM_ENABLED=1
CAMPUSPILOT_OPENAI_API_KEY=
CAMPUSPILOT_OPENAI_BASE_URL=https://工作空间ID.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
CAMPUSPILOT_OPENAI_MODEL=qwen-plus
```

## CampusPilot 本地管理后台

本地管理后台用于维护 OpenAI 兼容模型配置、检索开关和运行保护参数。默认关闭，
不会随公开 Demo 自动暴露。先在本地 `.env` 增加：

```dotenv
CAMPUSPILOT_ADMIN_ENABLED=1
CAMPUSPILOT_ADMIN_LOCAL_ONLY=1
CAMPUSPILOT_ADMIN_TOKEN=请替换为随机管理员Token
CAMPUSPILOT_ENV_FILE=.env
```

可以用 Python 生成随机 Token：

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

启动 FastAPI 后打开：

```text
http://127.0.0.1:8010/admin
```

安全边界：

- 管理 API 必须携带独立的 `X-CampusPilot-Admin-Token`；
- `CAMPUSPILOT_ADMIN_LOCAL_ONLY=1` 时只接受回环地址访问；
- API Key 仅允许覆盖写入，读取接口只返回“是否配置”和末四位提示；
- `.env` 使用临时文件加原子替换，保留注释和非管理字段；
- 管理页面只把管理员 Token 放在 `sessionStorage`，关闭会话后失效；
- 公网服务器默认保持 `CAMPUSPILOT_ADMIN_ENABLED=0`。

生效范围：

```text
API Key / Base URL / 模型名称 / 模型超时
  -> 已存在云模型客户端时立即热更新

LLM 开关 / 检索模式 / 向量检索 / Reranker / 限流 / 上传大小
  -> 写入 .env，重启服务后重新装配组件
```

“连接测试”会使用已保存的模型配置发送一条最小请求，并展示模型名称、耗时、输入
Token 和输出 Token。该操作会真实消耗模型额度；额度耗尽时页面会显示上游错误，
不会自动连续重试。

Key 与 Base URL 必须属于同一个百炼工作空间和计费计划。单独验证：

```powershell
.\scripts\run_agent_api.ps1
.\.venv\Scripts\python.exe scripts\check_cloud_llm.py
```

健康检查中的 `goal_interpreter` 为 `cloud_openai_compatible` 表示已启用；
认证失败、超时或返回格式错误时，对话 Agent 自动回退确定性路由。

## Monash Unit Guide 增量采集

刷新 2026 年演示课程：

```powershell
.\.venv\Scripts\python.exe scripts\collect_monash_unit_details.py --year 2026 --refresh
```

原始页面保存在被 Git 忽略的 `data/unit_sources`，结构化结果写入
`data/campuspilot_unit_assessments_2026.json`。采集器解析页面中的
`__NEXT_DATA__`，保存来源、时间和 SHA256；页面缺少出勤规则时必须保留
`UNKNOWN`。

## 完整能力启动检查

直接运行 `uvicorn` 时，进程不会自动读取项目根目录的 `.env`。手动启动完整 CampusPilot API 应使用：

```powershell
.\.venv\Scripts\python.exe -m uvicorn agent_runtime.api:app `
  --app-dir D:\agentdev\edurag-agent-lab\src `
  --host 127.0.0.1 `
  --port 8010 `
  --env-file .env
```

启动后不能只检查端口，应读取：

```powershell
Invoke-RestMethod http://127.0.0.1:8010/health/ready
```

完整 Agent 演示至少确认：

```text
vector_search_enabled = true
cloud_llm_enabled = true
```

如果两项为 `false`，页面仍可能正常打开，确定性规则接口也仍可运行，但 Handbook 向量检索与云端自然语言生成实际处于降级状态。
