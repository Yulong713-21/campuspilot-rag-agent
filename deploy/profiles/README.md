# CampusPilot deployment profiles

Set `CAMPUSPILOT_DEPLOYMENT_PROFILE` to choose sensible component defaults:

| Profile | Lexical evidence | Semantic evidence | Reranker |
| --- | --- | --- | --- |
| `lite` | in-process BM25 | off | off |
| `standard` | Elasticsearch BM25 | off | off |
| `full` | Elasticsearch BM25 | Milvus semantic subset | optional |

The versioned Rule Engine is available in every profile. Individual component
environment variables override the profile defaults, so environments can be
tuned without adding more profile names.

When an existing Elasticsearch or Milvus deployment first adopts these
profiles, rebuild its Handbook indexes once with `--recreate` to establish the
incremental state files. The Milvus rebuild also adopts the lightweight
semantic-subset schema; Elasticsearch continues to retain the full evidence
corpus.

The single-server demo uses Milvus Lite at a bind-mounted file path. This is a
lightweight deployment choice and is not equivalent to a standalone Milvus
Server. PostgreSQL and Elasticsearch stay on the Compose network without host
port mappings; only the FastAPI loopback port is published for Nginx.
