# CampusPilot deployment profiles

Set `CAMPUSPILOT_DEPLOYMENT_PROFILE` to choose sensible component defaults:

| Profile | Lexical evidence | Semantic evidence | Reranker |
| --- | --- | --- | --- |
| `lite` | in-process BM25 | off | off |
| `standard` | Elasticsearch BM25 | off | off |
| `full` | Elasticsearch BM25 | Milvus | on |

The versioned Rule Engine is available in every profile. Individual component
environment variables override the profile defaults, so environments can be
tuned without adding more profile names.

When an existing Elasticsearch or Milvus deployment first adopts these
profiles, rebuild its Handbook indexes once with `--recreate` to establish the
incremental state files. The Milvus rebuild also adopts the lightweight
semantic-subset schema; Elasticsearch continues to retain the full evidence
corpus.
