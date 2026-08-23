# Data contract

Git 中的 `data/` 是可复现的轻量公开数据层，不是生产语料、运行数据库或模型仓库。

## Logical ownership

```text
data/
├── catalog/       # conceptual: versioned structured catalogs and rules
├── manifests/     # conceptual: official source inventories and hashes
├── samples/       # conceptual: small reproducible examples and fixtures
└── runtime/       # ignored: raw snapshots, vector stores, databases and caches
```

当前仍保留兼容路径，避免一次目录搬迁破坏脚本与已发布镜像：

| 当前路径 | 逻辑分类 | 是否进入 Git | 说明 |
| --- | --- | --- | --- |
| `data/admissions/*.json` | catalog | 是 | 版本化院校、项目和人工审核规则 |
| `data/admissions/vector_docs/` | samples/catalog text | 是 | 可复现的轻量官方文本 |
| `data/*catalog*.json` | catalog | 是 | 结构化公开目录 |
| `data/handbook_source_manifest.json` | manifests | 是 | 官方来源清单与检索范围 |
| `data/*sample*.json`、`data/campuspilot_faq.json` | samples | 是 | 演示与回归样例 |
| `data/official_sources/raw/` | runtime | 否 | 原始 HTML、MHTML、DOCX 快照 |
| `data/official_sources/clean/` | runtime | 否 | 本地解析产物，可由 pipeline 重建 |
| `data/vector/`、`*.db` | runtime | 否 | Milvus Lite、SQLite 和索引状态 |
| `data/unit_sources/` | runtime | 否 | 本地课程页采集结果 |

## Source-of-truth rules

1. 确定性 Planner 只读取经过版本化和审核的结构数据。
2. RAG 文本用于证据、解释与引用，不能覆盖确定性学分或先修规则。
3. 原始来源先进入 ignored runtime 路径；审核、解析和回归测试通过后才能更新版本化数据。
4. 所有规则必须携带学校、项目、Handbook Year、适用路径和官方来源标识。
5. 不提交运行数据库、模型权重、缓存、抓取凭据、私有文件或无法复现的大型语料。

后续若物理迁移到 `catalog/`、`manifests/`、`samples/`，应在单独提交中更新所有消费者并通过
完整测试；不能只为了目录观感破坏稳定运行路径。
