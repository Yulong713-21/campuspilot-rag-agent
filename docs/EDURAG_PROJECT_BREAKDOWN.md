# EduRAG 项目拆解与完成路线

资料来源：

- 项目资料目录：`D:\BaiduNetdiskDownload\eduRAG项目资料\资料`
- 完整代码目录：`D:\BaiduNetdiskDownload\eduRAG项目资料\资料\完整代码\integrated_qa_system`
- 讲义目录：`D:\agentdev\EduRAG课件（讲义）`

这个项目不是单纯的“大模型聊天项目”，而是一个“FAQ 精确问答 + RAG 知识库问答 + API/WebUI”的教育问答系统。你完成它时，优先目标不是训练大模型，而是把数据、检索、向量库、问答链路和接口跑通。

## 1. 项目一句话目标

构建一个面向 IT 教育课程资料的智能问答系统：

- 用户问的是高频固定问题时，优先从 MySQL FAQ 表中查答案。
- FAQ 命中率不够时，回退到 Milvus 知识库检索。
- RAG 检索出相关课程资料后，调用大模型生成回答。
- 系统支持多轮对话历史、学科过滤、流式输出、API 和 WebUI。
- 最后用 RAGAS 对回答质量做评估。

## 2. 你手里的资料分别有什么用

| 目录/文件 | 作用 |
| --- | --- |
| `完整代码/integrated_qa_system` | 主项目代码，直接从这里开始跑 |
| `数据集/data/ai_data` | RAG 知识库原始资料，包含课程大纲和 PDF |
| `数据集/data/rag_evaluate_data.json` | RAG 评估数据集 |
| `数据集/data/model_generic_1000.json` | 查询分类模型训练/验证数据 |
| `models/bge-m3` | 向量嵌入模型，用于 dense/sparse 混合检索 |
| `models/bge-reranker-large` | 重排序模型，用于提高检索结果相关性 |
| `models/bert-base-chinese` | 查询分类模型的基础 BERT |
| `models/nlp_bert_document-segmentation_chinese-base` | 文档语义切分相关模型 |
| `loaders+spliter` | 自定义文档加载器和中文切分器 |
| `milvus镜像/docker-compose.yml` | Milvus、etcd、minio、Redis 启动配置 |
| `requirments.txt` | Python 依赖列表，文件名拼写保留原样 |
| `attu-Setup-2.6.0.exe` | Milvus 图形化管理工具 Attu |
| `CentOS7-1.zip` | 虚拟机/系统环境资料，可能用于课程演示 |

## 3. 项目代码模块拆解

核心入口：

- `app.py`：FastAPI 服务入口，提供 HTTP、WebSocket、静态页面。
- `new_main.py`：集成问答系统主流程，串联 MySQL FAQ、Redis 缓存、Milvus RAG、大模型和会话历史。

基础模块：

- `base/config.py`：读取 `config.ini`，管理 MySQL、Redis、Milvus、LLM 和检索参数。
- `base/logger.py`：日志工具。

FAQ 模块：

- `mysql_qa/db/mysql_client.py`：连接 MySQL、建表、导入 FAQ CSV、查询问题和答案。
- `mysql_qa/cache/redis_client.py`：缓存 FAQ 问题、分词结果和答案。
- `mysql_qa/retrieval/bm25_search.py`：用 BM25 + softmax 匹配用户问题，命中高于阈值就直接返回 FAQ 答案。

RAG 模块：

- `rag_qa/core/document_processor.py`：加载 PDF、Word、PPT、图片、Markdown、TXT，并做父子块切分。
- `rag_qa/core/vector_store.py`：连接 Milvus，创建 collection，写入向量，执行 dense + sparse 混合检索和 rerank。
- `rag_qa/core/query_classifier.py`：判断问题是通用知识还是专业咨询。
- `rag_qa/core/strategy_selector.py`：选择检索增强策略，例如直接检索、HyDE、子查询、回溯问题。
- `rag_qa/core/prompts.py`：RAG 回答提示词、HyDE 提示词、子查询提示词。
- `rag_qa/core/new_rag_system.py`：带历史记录和流式输出的 RAG 系统。

评估模块：

- `rag_qa/rag_assesment/rag_as.py`：用 RAGAS 评估忠实度、答案相关性、上下文准确率和上下文召回率。

前端/API：

- `static/index.html`
- `static/src/App.jsx`
- `app.py` 中的 `/api/query`、`/api/stream`、`/api/history`、`/api/sources`、`/health`

## 4. 系统运行主流程

用户提问后，系统按这个顺序工作：

1. FastAPI 接收请求。
2. 先判断是否是问候语，是的话直接返回固定回复。
3. 调用 BM25 FAQ 检索。
4. 如果 FAQ 相似度高于阈值，从 MySQL 返回标准答案。
5. 如果 FAQ 未命中，进入 RAG。
6. RAG 先用 BERT 查询分类判断是否需要查知识库。
7. 如果是专业咨询，选择检索策略。
8. 从 Milvus 做 dense + sparse 混合检索。
9. 对父文档块做 rerank。
10. 拼接上下文、历史对话和问题。
11. 调用 DashScope 兼容 OpenAI API 流式生成答案。
12. 将会话历史写入 MySQL。
13. HTTP 或 WebSocket 返回结果。

可以把它理解为：

```text
用户问题
  -> 问候语判断
  -> FAQ/BM25/MySQL
  -> 未命中则 RAG
  -> 查询分类
  -> 检索策略选择
  -> Milvus 混合检索
  -> reranker 重排
  -> Prompt 组装
  -> DashScope 大模型生成
  -> 保存历史
  -> API/WebUI 输出
```

## 5. 第一阶段：先跑通原项目

不要一上来改代码。先把原项目跑起来，确认环境和链路能通。

建议把完整代码复制到工作目录，例如：

```text
D:\agentdev\edurag\integrated_qa_system
```

然后进入项目目录：

```powershell
cd D:\agentdev\edurag\integrated_qa_system
python -m venv .venv
.\.venv\Scripts\activate
pip install -r D:\BaiduNetdiskDownload\eduRAG项目资料\资料\requirments.txt
```

验收标准：

- Python 环境能创建成功。
- 依赖能安装完成。
- `python -c "import fastapi, pymilvus, langchain, torch"` 不报错。

## 6. 第二阶段：启动基础服务

这个项目至少需要：

- MySQL：存 FAQ、会话历史。
- Redis：缓存 FAQ、分词结果、答案。
- Milvus：存知识库向量。
- etcd + minio：Milvus 依赖服务。
- DashScope API：生成最终答案。

Milvus 和 Redis 可以用资料里的 compose：

```powershell
cd D:\BaiduNetdiskDownload\eduRAG项目资料\资料\milvus镜像
docker compose up -d
```

如果不能联网拉镜像，先把目录里的 tar 镜像导入：

```powershell
docker load -i redis.tar
docker load -i minio.tar
docker load -i milvusdb.tar
docker load -i etcd.tar
docker compose up -d
```

检查服务：

```powershell
docker ps
```

验收标准：

- Redis 暴露 `6379`。
- Milvus 暴露 `19530`。
- `milvus-standalone`、`milvus-etcd`、`milvus-minio`、`milvus-redis` 都在运行。

## 7. 第三阶段：修正配置

重点看 `config.ini`。

当前资料里的配置大概是：

```ini
[mysql]
host = 192.168.100.128
user = root
password = 123456
database = subjects_kg

[redis]
host = 192.168.100.128
port = 6379
password = 1234
db = 0

[milvus]
host = 192.168.100.128
port = 19530
collection_name = edurag_final
```

如果你在本机 Docker 跑，建议改成：

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

必须注意：

- `config.ini` 里 `database_name = itcast` 要单独一行，不要跟注释混在同一行。
- `mysql_client.py` 里 MySQL 端口硬编码为 `3307`，你要么让 MySQL 跑在 `3307`，要么把代码改成读取配置。
- `dashscope_api_key = sk-` 需要换成你自己的 DashScope API Key。

验收标准：

- `Config().MILVUS_DATABASE_NAME` 能读到 `itcast`。
- Redis host、Milvus host 和实际 Docker 地址一致。
- MySQL 端口与实际服务一致。

## 8. 第四阶段：准备 MySQL FAQ 数据

FAQ 数据位于：

```text
完整代码\integrated_qa_system\mysql_qa\data\JP学科知识问答.csv
```

MySQL 表结构在 `mysql_qa/db/mysql_client.py`：

```sql
CREATE TABLE IF NOT EXISTS jpkb (
  id INT AUTO_INCREMENT PRIMARY KEY,
  subject_name VARCHAR(20),
  question VARCHAR(1000),
  answer VARCHAR(1000)
)
```

你需要做：

1. 创建数据库 `subjects_kg`。
2. 跑 `create_table()`。
3. 跑 `insert_data(csv_path)` 导入 FAQ。
4. 用 `fetch_questions()` 验证能读到问题。
5. 用 `BM25Search.search()` 验证 FAQ 能命中。

验收标准：

- MySQL 有 `subjects_kg.jpkb` 表。
- 表里有 FAQ 数据。
- 问一个 CSV 里接近的问题，能直接返回 MySQL 答案。

## 9. 第五阶段：构建 Milvus 知识库

RAG 数据位于：

```text
完整代码\integrated_qa_system\rag_qa\data\ai_data
```

入库流程是：

1. `document_processor.process_documents(directory_path)` 加载文档。
2. 按父块和子块切分。
3. 给每个子块附带父块内容、source、timestamp。
4. `vector_store.add_documents(documents)` 用 BGE-M3 生成 dense/sparse 向量。
5. 写入 Milvus collection。

关键参数来自 `config.ini`：

```ini
parent_chunk_size = 1200
child_chunk_size = 300
chunk_overlap = 50
retrieval_k = 5
candidate_m = 2
```

验收标准：

- Milvus 中创建了 `edurag_final` collection。
- collection 有数据。
- 执行 `hybrid_search_with_rerank("AI课程大纲是什么", source_filter="ai")` 能返回文档块。

## 10. 第六阶段：跑通 RAG 回答

RAG 回答主入口是：

```python
RAGSystem(vector_store, call_dashscope).generate_answer(...)
```

你需要验证三件事：

- 查询分类器能返回“专业咨询”或“通用知识”。
- 检索策略选择器能返回一种检索策略。
- 大模型能基于 context 生成答案。

推荐测试问题：

```text
AI学科课程大纲内容是什么？
人工智能就业课的课程版本是什么？
课程优势有哪些？
```

验收标准：

- 不报 Milvus 连接错误。
- 不报模型路径错误。
- 不报 DashScope API 错误。
- 回答中能体现课程资料内容。

## 11. 第七阶段：跑 API 和 WebUI

启动：

```powershell
cd D:\agentdev\edurag\integrated_qa_system
.\.venv\Scripts\activate
uvicorn app:app --host 0.0.0.0 --port 8000
```

接口：

- `GET /health`：健康检查。
- `GET /api/sources`：获取学科 source。
- `POST /api/create_session`：创建会话。
- `POST /api/query`：非流式查询，FAQ 命中时可直接返回。
- `WebSocket /api/stream`：RAG 流式回答。
- `GET /api/history/{session_id}`：查历史。
- `DELETE /api/history/{session_id}`：清历史。

验收标准：

- 浏览器打开 `http://127.0.0.1:8000/health` 返回 `{"status":"healthy"}`。
- FAQ 问题走 `/api/query` 能直接返回答案。
- RAG 问题走 `/api/stream` 能流式返回答案。
- 历史记录能写入 MySQL。

## 12. 第八阶段：做 RAG 评估

评估脚本：

```text
rag_qa\rag_assesment\rag_as.py
```

评估数据：

```text
rag_qa\rag_assesment\rag_evaluate_data.json
```

指标：

- `faithfulness`：回答是否忠实于上下文。
- `answer_relevancy`：回答是否贴合问题。
- `context_precision`：检索上下文是否精准。
- `context_recall`：检索上下文是否覆盖必要信息。

脚本默认使用 Ollama：

```python
ChatOllama(model="qwen2.5:7b", base_url="http://localhost:11434")
OllamaEmbeddings(model="mxbai-embed-large", base_url="http://localhost:11434")
```

验收标准：

- 评估脚本能读入数据集。
- RAGAS 能输出四类指标。
- 你能记录一次 baseline 分数。

## 13. 最适合你的开发顺序

第一轮只做“跑通”：

1. 复制完整代码到 `D:\agentdev\edurag`。
2. 创建 Python 环境并安装依赖。
3. 启动 Redis、Milvus、etcd、minio。
4. 准备 MySQL，并确认端口。
5. 修正 `config.ini` 和 API Key。
6. 导入 FAQ CSV。
7. 构建 Milvus 知识库。
8. 跑 `app.py`。
9. 测试 FAQ 和 RAG 两条链路。

第二轮做“理解和改造”：

1. 画出 query 流程。
2. 改一条 Prompt，让回答风格符合你的项目。
3. 换一批自己的知识库文件。
4. 增加一个新的 `source_filter`。
5. 调整 chunk 参数。
6. 调整 BM25 阈值。
7. 记录效果变化。

第三轮做“交付”：

1. 写 README。
2. 写部署说明。
3. 截图 API/WebUI 效果。
4. 记录 RAGAS 评估结果。
5. 总结项目亮点和不足。

## 14. 你需要真正写/改的内容

这个项目大部分代码已经有了，你主要需要完成这些：

- 环境配置：把 IP、端口、API Key 改成自己的。
- 数据导入：MySQL FAQ 和 Milvus 知识库入库。
- 运行脚本：补一个一键初始化脚本会很加分。
- Prompt 优化：让回答更像“教育咨询助手”。
- README：说明怎么部署、怎么启动、怎么测试。
- 评估报告：用 RAGAS 或人工样例对比效果。
- 可选改造：把 MySQL 端口从硬编码改成配置项。

## 15. 常见卡点

### 1. MySQL 连不上

优先检查：

- MySQL 是否启动。
- 端口是不是 `3307`。
- 数据库 `subjects_kg` 是否存在。
- `config.ini` 的 host、user、password 是否正确。

### 2. Redis 连不上

优先检查：

- Docker 里的 Redis 是否运行。
- 密码是否为 `1234`。
- `config.ini` host 是否是 `127.0.0.1` 或虚拟机 IP。

### 3. Milvus 连不上

优先检查：

- `docker ps` 是否有 Milvus standalone。
- `19530` 是否暴露。
- `database_name = itcast` 是否正确读取。
- Attu 是否能连接 Milvus。

### 4. 模型加载慢或内存爆

项目会加载：

- BGE-M3 embedding 模型。
- BGE reranker。
- BERT query classifier。

如果机器配置一般，第一次加载会慢。可以先用小数据、小文档跑通，不要一次性导入大量资料。

### 5. RAG 回答没有引用资料

优先检查：

- Milvus 是否真的有数据。
- `source_filter` 是否传错。
- chunk 是否切得太碎或太大。
- reranker 是否返回空结果。
- query classifier 是否把专业问题误判成通用知识。

## 16. 最终交付物

建议最终项目目录里至少包含：

```text
README.md
config.ini.example
requirements.txt
scripts/
  init_mysql.py
  build_vector_store.py
  smoke_test.py
docs/
  architecture.md
  deployment.md
  evaluation.md
screenshots/
  health.png
  api_query.png
  webui.png
```

最终演示顺序：

1. 展示系统架构。
2. 展示 FAQ 问题直接命中 MySQL。
3. 展示非 FAQ 问题进入 RAG。
4. 展示 Milvus 检索出的上下文。
5. 展示流式回答。
6. 展示会话历史。
7. 展示 RAGAS 评估结果。

## 17. 当前最小任务清单

- [ ] 复制 `完整代码/integrated_qa_system` 到工作目录。
- [ ] 创建虚拟环境。
- [ ] 安装 `requirments.txt`。
- [ ] 启动 Docker 基础服务。
- [ ] 修正 `config.ini`。
- [ ] 准备 MySQL 数据库和 FAQ 表。
- [ ] 导入 `JP学科知识问答.csv`。
- [ ] 处理 `rag_qa/data/ai_data` 文档。
- [ ] 写入 Milvus collection。
- [ ] 配置 DashScope API Key。
- [ ] 启动 FastAPI。
- [ ] 测试 FAQ 问答。
- [ ] 测试 RAG 问答。
- [ ] 跑一次 RAGAS 评估。
- [ ] 写 README 和部署文档。

## 18. 推荐你下一步做什么

先不要改功能。下一步只做一件事：

把 `完整代码/integrated_qa_system` 复制到 `D:\agentdev\edurag\integrated_qa_system`，然后把 `config.ini` 里的 IP、Milvus database、MySQL 端口和 DashScope Key 配好。配置能读通之后，再开始导入 FAQ 和构建 Milvus 知识库。
