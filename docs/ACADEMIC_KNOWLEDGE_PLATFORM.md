# Academic Knowledge Platform direction

CampusPilot models Australian academic information as a versioned knowledge
platform rather than one undifferentiated vector corpus.

## Coverage maturity

```text
CATALOG
  institution and program discovery, official source links
    ↓
STRUCTURED
  normalized program, unit, year, credit and offering facts
    ↓
VERIFIED
  reviewed rule scope and deterministic planning scenarios
```

Maturity is resolved for `university + program + handbook year +
specialisation`. A university may have broad Catalog coverage while one program
has Structured or Verified capability. New Australian institutions can enter
at Catalog level without waiting for complete rule parsing.

The registry is stored in `data/academic_coverage.json` and exposed through
`GET /api/coverage/capabilities`.

## Retrieval flow

```text
query + conversation context
  → RetrievalScopeResolver
  → university/program/year/specialisation filters
  → lexical, semantic, or hybrid EvidenceRetriever
  → official evidence
```

Business code sends a `RetrievalRequest`; Elasticsearch and Milvus remain
behind lexical/dense interfaces and composition code.

## Incremental publication

Both Handbook indexers compare the current corpus with the last successful
index state:

```text
source_sha256 changed → compare per-chunk content hashes
chunk added/changed     → upsert that chunk only
chunk removed          → delete stale chunk_id
source unchanged       → no backend write
source removed         → delete all previous chunks
```

State is written atomically only after backend operations succeed. Use
`--recreate` once when bootstrapping state for an existing index, when adopting
the `specialisation_codes` schema field, or for an intentional full rebuild.

## Deployment profiles

- `lite`: local BM25, no dense retrieval or reranker.
- `standard`: Elasticsearch BM25, no dense retrieval or reranker.
- `full`: Elasticsearch + Milvus + reranker.

Profiles provide defaults; explicit component environment variables can tune
an environment independently.

## Evaluation

`eval/handbook_retrieval_cases.json` contains corpus-grounded lexical,
semantic, and hybrid cases. Metrics remain scenario-specific: exact identifier
ranking for lexical search, concept discovery for semantic search, and channel
coverage for hybrid fusion, with scope precision measured for every scenario.

```powershell
python scripts/evaluate_handbook_retrieval.py --scenarios lexical
python scripts/evaluate_handbook_retrieval.py --scenarios lexical semantic hybrid
```
