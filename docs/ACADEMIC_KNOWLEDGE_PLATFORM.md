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

### Deterministic retrieval planning

Routing happens after scope resolution and does not require an LLM:

| Query signal | Planned capabilities |
| --- | --- |
| prerequisites, offerings, credits, exclusions, plan validity | Structured + Lexical |
| exact identifiers or official wording | Lexical |
| career fit, interests, descriptions, learning outcomes | Lexical + Semantic |
| program-scoped eligible course discovery with preferences | Structured + Lexical + Semantic |

`STRUCTURED`, `LEXICAL`, and `SEMANTIC` are independent capabilities; hybrid
evidence retrieval is represented by selecting both evidence channels. Route
reasons remain visible in diagnostics and an LLM is not used as the primary
router.

For mixed queries, a PostgreSQL-backed structured resolver can be injected and
then runs first, returning candidate course, program, or specialisation codes.
These identifiers are applied inside Elasticsearch, Milvus, or local BM25
filters. Candidate constraints only come from this explicit resolver; the
scope resolver continues to produce ordinary university, program, year, and
specialisation filters and never promotes them into candidates. An empty
candidate set therefore leaves normal scope filtering unchanged. If required
candidates are unavailable, global semantic discovery is skipped rather than
asking retrieval or an LLM to infer eligibility.

Execution diagnostics distinguish the planned and effective route and report
structured, lexical, and semantic usage, normalized scope, candidate count,
route reasons, fallback use, and safe degradation categories. A Milvus failure
retains Structured + Lexical execution; complete evidence failure preserves any
structured result.

### Semantic subset

Milvus is a semantic candidate index, not a second Handbook store. A
deterministic classifier includes descriptions, learning outcomes,
specialisation narratives, policy or eligibility explanations, career content,
academic advice and other sufficiently rich prose. It skips navigation,
metadata-only fragments, exact code lists, credit or prerequisite tables,
teaching-period tables and other structured numeric records.

Milvus stores stable IDs, scope fields, semantic category and the vector. The
canonical chunk corpus resolves display and citation text after retrieval;
Elasticsearch retains the complete lexical evidence corpus. Measure the current
subset without loading an embedding model or connecting to Milvus:

```powershell
python scripts/build_handbook_vector_index.py --report-only
```

For the checked-in 2026 corpus, the current policy selects 6,806 of 16,797
chunks (40.5191%). This is a measured outcome of the content rules, not a fixed
percentage target.

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

State is written atomically only after backend operations succeed. The semantic
index passes only eligible chunks into this pipeline, so eligibility transitions
produce the same upsert/delete operations as content changes. Use `--recreate`
once when adopting the lightweight semantic schema or for an intentional full
rebuild.

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
coverage for hybrid fusion. Recall@K, reciprocal rank and scope precision are
reported per scenario alongside semantic subset coverage.

```powershell
python scripts/evaluate_handbook_retrieval.py --scenarios lexical
python scripts/evaluate_handbook_retrieval.py --scenarios lexical semantic hybrid
```

The real Milvus integration test is opt-in through
`CAMPUSPILOT_TEST_MILVUS_URI`; ordinary unit and API tests remain
infrastructure-independent.
