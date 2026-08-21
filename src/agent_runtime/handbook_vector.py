from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable, Iterable, Protocol


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST_PATH = REPO_ROOT / "data" / "handbook_source_manifest.json"
DEFAULT_EXTRACTION_REPORT_PATH = (
    REPO_ROOT / "data" / "official_sources" / "extraction-report.json"
)
DEFAULT_CHUNK_PATH = (
    REPO_ROOT / "data" / "official_sources" / "handbook-chunks.jsonl"
)
MILVUS_VARCHAR_LIMITS = {
    "chunk_id": 64,
    "parent_id": 160,
    "source_id": 160,
    "university_id": 48,
    "program_code": 64,
    "program_codes": 2048,
    "source_type": 64,
    "discipline_ids": 256,
    "title": 1024,
    "heading": 2048,
    "content": 65535,
    "parent_content": 65535,
    "source_url": 4096,
    "source_sha256": 64,
}


@dataclass(frozen=True)
class HandbookChunk:
    chunk_id: str
    parent_id: str
    source_id: str
    university_id: str
    handbook_year: int
    program_code: str
    source_type: str
    discipline_ids: list[str]
    title: str
    heading: str
    content: str
    parent_content: str
    source_url: str
    source_sha256: str
    program_codes: list[str] = field(default_factory=list)

    @property
    def embedding_text(self) -> str:
        labels = [self.title, self.heading, self.content]
        return "\n".join(item for item in labels if item).strip()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DenseEmbedder(Protocol):
    dimension: int

    def encode(self, texts: list[str]) -> list[list[float]]: ...


def parse_markdown_document(path: str | Path) -> tuple[dict[str, Any], str]:
    text = Path(path).read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, text
    closing = text.find("\n---\n", 4)
    if closing < 0:
        return {}, text
    metadata: dict[str, Any] = {}
    for line in text[4:closing].splitlines():
        key, separator, value = line.partition(":")
        if not separator:
            continue
        metadata[key.strip()] = value.strip().strip('"')
    return metadata, text[closing + 5 :].strip()


class HandbookChunker:
    """Creates heading-aware parent and child chunks from cleaned Handbook text."""

    HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
    MAX_HEADING_CHARS = 240

    def __init__(
        self,
        *,
        parent_size: int = 3200,
        child_size: int = 1200,
        child_overlap: int = 160,
    ) -> None:
        if child_overlap >= child_size:
            raise ValueError("child_overlap must be smaller than child_size")
        if child_size > parent_size:
            raise ValueError("child_size must not exceed parent_size")
        self.parent_size = parent_size
        self.child_size = child_size
        self.child_overlap = child_overlap

    def chunk_document(
        self,
        *,
        path: str | Path,
        source: dict[str, Any],
    ) -> list[HandbookChunk]:
        front_matter, body = parse_markdown_document(path)
        title = source.get("title") or self._first_title(body)
        sections = self._sections(body)
        chunks: list[HandbookChunk] = []
        parent_number = 0
        for heading, section_text in sections:
            for parent_content in self._split_text(
                section_text,
                size=self.parent_size,
                overlap=0,
            ):
                parent_number += 1
                parent_id = f"{source['source_id']}-p{parent_number:04d}"
                child_texts = self._split_text(
                    parent_content,
                    size=self.child_size,
                    overlap=self.child_overlap,
                )
                for child_number, child_content in enumerate(
                    child_texts,
                    start=1,
                ):
                    identity = (
                        f"{parent_id}:{child_number}:{child_content}"
                    ).encode("utf-8")
                    chunk_id = hashlib.sha1(identity).hexdigest()
                    chunks.append(
                        HandbookChunk(
                            chunk_id=chunk_id,
                            parent_id=parent_id,
                            source_id=source["source_id"],
                            university_id=source.get(
                                "university_id",
                                front_matter.get("university_id", ""),
                            ),
                            handbook_year=int(
                                source.get("handbook_year") or -1
                            ),
                            program_code=source.get("program_code", ""),
                            source_type=source.get("source_type", ""),
                            discipline_ids=list(
                                source.get("discipline_ids", [])
                            ),
                            title=title,
                            heading=heading,
                            content=child_content,
                            parent_content=parent_content,
                            source_url=source.get(
                                "url",
                                front_matter.get("source_url", ""),
                            ),
                            source_sha256=front_matter.get(
                                "source_sha256",
                                "",
                            ),
                            program_codes=list(
                                source.get("related_program_codes")
                                or (
                                    [source["program_code"]]
                                    if source.get("program_code")
                                    else []
                                )
                            ),
                        )
                    )
        return chunks

    def _sections(self, body: str) -> list[tuple[str, str]]:
        heading_stack: list[str] = []
        current_heading = ""
        current_lines: list[str] = []
        sections: list[tuple[str, str]] = []

        def flush() -> None:
            content = "\n".join(current_lines).strip()
            if content:
                sections.append((current_heading, content))

        for line in body.splitlines():
            match = self.HEADING_PATTERN.match(line)
            if not match:
                current_lines.append(line)
                continue
            heading_text = match.group(2).strip()
            if len(heading_text) > self.MAX_HEADING_CHARS:
                current_lines.append(heading_text)
                continue
            flush()
            current_lines = []
            level = len(match.group(1))
            heading_stack[level - 1 :] = [heading_text]
            current_heading = " > ".join(heading_stack)
        flush()
        return sections

    @staticmethod
    def _first_title(body: str) -> str:
        for line in body.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return ""

    @staticmethod
    def _split_text(
        text: str,
        *,
        size: int,
        overlap: int,
    ) -> list[str]:
        normalized = re.sub(r"\n{3,}", "\n\n", text).strip()
        if not normalized:
            return []
        chunks: list[str] = []
        start = 0
        length = len(normalized)
        while start < length:
            tentative_end = min(start + size, length)
            end = tentative_end
            if tentative_end < length:
                boundary = max(
                    normalized.rfind("\n\n", start + size // 2, tentative_end),
                    normalized.rfind(". ", start + size // 2, tentative_end),
                    normalized.rfind("; ", start + size // 2, tentative_end),
                )
                if boundary > start:
                    end = boundary + 1
            chunk = normalized[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= length:
                break
            next_start = max(end - overlap, start + 1)
            while (
                next_start < end
                and not normalized[next_start].isspace()
            ):
                next_start += 1
            start = min(next_start + 1, end)
        return chunks


def build_ready_corpus(
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
    extraction_report_path: str | Path = DEFAULT_EXTRACTION_REPORT_PATH,
    chunker: HandbookChunker | None = None,
) -> list[HandbookChunk]:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    report = json.loads(
        Path(extraction_report_path).read_text(encoding="utf-8")
    )
    sources = {
        source["source_id"]: source for source in manifest["sources"]
    }
    active_chunker = chunker or HandbookChunker()
    chunks: list[HandbookChunk] = []
    for result in report["results"]:
        if result["status"] != "ready":
            continue
        source = sources[result["source_id"]]
        chunks.extend(
            active_chunker.chunk_document(
                path=result["output_path"],
                source=source,
            )
        )
    return chunks


def write_chunks(
    chunks: Iterable[HandbookChunk],
    path: str | Path = DEFAULT_CHUNK_PATH,
) -> int:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with target.open("w", encoding="utf-8") as output:
        for chunk in chunks:
            output.write(
                json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n"
            )
            count += 1
    return count


def read_chunks(path: str | Path = DEFAULT_CHUNK_PATH) -> list[HandbookChunk]:
    return [
        HandbookChunk(**json.loads(line))
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def validate_milvus_chunks(chunks: Iterable[HandbookChunk]) -> None:
    for position, chunk in enumerate(chunks):
        row = {
            **chunk.to_dict(),
            "discipline_ids": "|".join(chunk.discipline_ids),
            "program_codes": (
                "|" + "|".join(chunk.program_codes) + "|"
                if chunk.program_codes
                else ""
            ),
        }
        for field, max_length in MILVUS_VARCHAR_LIMITS.items():
            value = str(row[field])
            if len(value) > max_length:
                raise ValueError(
                    f"chunk {position} field {field} has length "
                    f"{len(value)}, exceeding {max_length}"
                )


class BGEM3DenseEmbedder:
    dimension = 1024

    def __init__(self, model_path: str | Path) -> None:
        import os
        import torch
        from FlagEmbedding import BGEM3FlagModel

        torch.set_num_threads(max(1, os.cpu_count() or 1))
        self.model = BGEM3FlagModel(
            str(model_path),
            use_fp16=False,
        )

    def encode(self, texts: list[str]) -> list[list[float]]:
        result = self.model.encode(
            texts,
            batch_size=16,
            max_length=1024,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        return result["dense_vecs"].tolist()


class SentenceTransformerDenseEmbedder:
    def __init__(self, model_path: str | Path) -> None:
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(str(model_path), device="cpu")
        dimension = self.model.get_sentence_embedding_dimension()
        if dimension is None:
            raise RuntimeError("embedding model did not report its dimension")
        self.dimension = int(dimension)

    def encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(
            texts,
            batch_size=64,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vectors.tolist()


class SentenceTransformerReranker:
    def __init__(self, model_path: str | Path) -> None:
        from sentence_transformers import CrossEncoder

        self.model = CrossEncoder(str(model_path), device="cpu")

    def rerank(
        self,
        query: str,
        documents: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not documents:
            return []
        scores = self.model.predict(
            [
                (
                    query,
                    str(
                        item.get("content")
                        or item.get("parent_content")
                        or ""
                    ),
                )
                for item in documents
            ],
            show_progress_bar=False,
        )
        reranked = [
            {**item, "rerank_score": round(float(score), 6)}
            for item, score in zip(documents, scores, strict=True)
        ]
        reranked.sort(key=lambda item: item["rerank_score"], reverse=True)
        return reranked


def create_dense_embedder(
    backend: str,
    model_path: str | Path,
) -> DenseEmbedder:
    normalized = backend.strip().lower()
    if normalized == "bge-m3":
        return BGEM3DenseEmbedder(model_path)
    if normalized == "sentence-transformer":
        return SentenceTransformerDenseEmbedder(model_path)
    raise ValueError(f"unsupported embedding backend: {backend}")


class CampusPilotMilvusStore:
    def __init__(
        self,
        *,
        uri: str,
        collection_name: str,
        embedder: DenseEmbedder,
        client: Any | None = None,
    ) -> None:
        self.uri = uri
        self.collection_name = collection_name
        self.embedder = embedder
        if client is None:
            from pymilvus import MilvusClient

            client = MilvusClient(uri=uri)
        self.client = client

    def recreate_collection(self) -> None:
        from pymilvus import DataType

        if self.client.has_collection(self.collection_name):
            self.client.drop_collection(self.collection_name)
        schema = self.client.create_schema(
            auto_id=False,
            enable_dynamic_field=False,
        )
        schema.add_field(
            field_name="chunk_id",
            datatype=DataType.VARCHAR,
            is_primary=True,
            max_length=MILVUS_VARCHAR_LIMITS["chunk_id"],
        )
        for field_name in (
            "parent_id",
            "source_id",
            "university_id",
            "program_code",
            "program_codes",
            "source_type",
            "discipline_ids",
            "title",
            "heading",
            "source_url",
            "source_sha256",
        ):
            schema.add_field(
                field_name=field_name,
                datatype=DataType.VARCHAR,
                max_length=MILVUS_VARCHAR_LIMITS[field_name],
            )
        schema.add_field(
            field_name="handbook_year",
            datatype=DataType.INT64,
        )
        for field_name in ("content", "parent_content"):
            schema.add_field(
                field_name=field_name,
                datatype=DataType.VARCHAR,
                max_length=MILVUS_VARCHAR_LIMITS[field_name],
            )
        schema.add_field(
            field_name="dense_vector",
            datatype=DataType.FLOAT_VECTOR,
            dim=self.embedder.dimension,
        )
        index_params = self.client.prepare_index_params()
        index_params.add_index(
            field_name="dense_vector",
            index_type="AUTOINDEX",
            metric_type="COSINE",
        )
        self.client.create_collection(
            collection_name=self.collection_name,
            schema=schema,
            index_params=index_params,
        )

    def ingest(
        self,
        chunks: list[HandbookChunk],
        *,
        batch_size: int = 64,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> int:
        inserted = 0
        for offset in range(0, len(chunks), batch_size):
            batch = chunks[offset : offset + batch_size]
            vectors = self.embedder.encode(
                [chunk.embedding_text for chunk in batch]
            )
            rows = [
                {
                    **chunk.to_dict(),
                    "discipline_ids": "|".join(chunk.discipline_ids),
                    "program_codes": (
                        "|" + "|".join(chunk.program_codes) + "|"
                        if chunk.program_codes
                        else ""
                    ),
                    "dense_vector": vector,
                }
                for chunk, vector in zip(batch, vectors, strict=True)
            ]
            self.client.insert(
                collection_name=self.collection_name,
                data=rows,
            )
            inserted += len(rows)
            if progress_callback is not None:
                progress_callback(inserted, len(chunks) - inserted)
        self.client.flush(self.collection_name)
        return inserted

    def row_count(self) -> int:
        stats = self.client.get_collection_stats(self.collection_name)
        return int(stats["row_count"])

    def chunk_ids(self, *, limit: int) -> set[str]:
        rows = self.client.query(
            collection_name=self.collection_name,
            filter='chunk_id != ""',
            output_fields=["chunk_id"],
            limit=limit,
        )
        return {str(row["chunk_id"]) for row in rows}

    def search(
        self,
        query: str,
        *,
        handbook_year: int | None = None,
        university_id: str | None = None,
        discipline_id: str | None = None,
        program_code: str | None = None,
        k: int = 10,
    ) -> list[dict[str, Any]]:
        vector = self.embedder.encode([query])[0]
        filters: list[str] = []
        if handbook_year is not None:
            filters.append(f"handbook_year == {int(handbook_year)}")
        if university_id:
            filters.append(
                f'university_id == "{self._escape(university_id)}"'
            )
        if program_code:
            filters.append(
                'program_codes like '
                f'"%|{self._escape(program_code)}|%"'
            )
        if discipline_id:
            filters.append(
                f'discipline_ids like "%{self._escape(discipline_id)}%"'
            )
        result = self.client.search(
            collection_name=self.collection_name,
            data=[vector],
            anns_field="dense_vector",
            filter=" and ".join(filters),
            limit=k,
            output_fields=[
                "chunk_id",
                "parent_id",
                "source_id",
                "university_id",
                "handbook_year",
                "program_code",
                "program_codes",
                "source_type",
                "discipline_ids",
                "title",
                "heading",
                "content",
                "parent_content",
                "source_url",
            ],
            search_params={"metric_type": "COSINE", "params": {}},
        )
        return [
            {
                **hit["entity"],
                "document_id": hit["entity"]["chunk_id"],
                "dense_score": round(float(hit["distance"]), 6),
            }
            for hit in result[0]
        ]

    @staticmethod
    def _escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')


class CampusPilotHybridRetriever:
    """Fuses lexical BM25 and Milvus dense retrieval with reciprocal ranks."""

    def __init__(
        self,
        *,
        chunks: list[HandbookChunk],
        vector_store: CampusPilotMilvusStore | None,
        reranker: Any | None = None,
        rrf_constant: int = 60,
    ) -> None:
        from rank_bm25 import BM25Okapi

        self.chunks = chunks
        self.vector_store = vector_store
        self.reranker = reranker
        self.rrf_constant = rrf_constant
        self.last_search_diagnostics: dict[str, Any] = {}
        self._tokenized = [
            self._tokenize(chunk.embedding_text) for chunk in chunks
        ]
        self._bm25 = BM25Okapi(self._tokenized)

    def search(
        self,
        query: str,
        *,
        handbook_year: int | None = None,
        university_id: str | None = None,
        discipline_id: str | None = None,
        program_code: str | None = None,
        k: int = 3,
    ) -> list[dict[str, Any]]:
        candidate_k = max(k * 4, 12)
        lexical = self._lexical_search(
            query,
            handbook_year=handbook_year,
            university_id=university_id,
            discipline_id=discipline_id,
            program_code=program_code,
            k=candidate_k,
        )
        dense_error = None
        dense: list[dict[str, Any]] = []
        if self.vector_store is not None:
            try:
                dense = self.vector_store.search(
                    query,
                    handbook_year=handbook_year,
                    university_id=university_id,
                    discipline_id=discipline_id,
                    program_code=program_code,
                    k=candidate_k,
                )
            except Exception as exc:
                dense_error = type(exc).__name__
        self.last_search_diagnostics = {
            "bm25_count": len(lexical),
            "dense_count": len(dense),
            "dense_error": dense_error,
            "degraded": self.vector_store is not None and dense_error is not None,
        }
        fused: dict[str, dict[str, Any]] = {}
        program_scope_query = self._is_program_scope_query(query)
        query_identifiers = set(
            re.findall(r"\b[A-Z]{3}\d{4}\b", query.upper())
        )
        for channel, results in (("bm25", lexical), ("dense", dense)):
            for rank, item in enumerate(results, start=1):
                chunk_id = item["chunk_id"]
                record = fused.setdefault(
                    chunk_id,
                    {
                        **item,
                        "retrieval_channels": [],
                        "rrf_score": 0.0,
                    },
                )
                record["retrieval_channels"].append(channel)
                record["rrf_score"] += 1 / (
                    self.rrf_constant + rank
                )
                if "bm25_score" in item:
                    record["bm25_score"] = item["bm25_score"]
                if "dense_score" in item:
                    record["dense_score"] = item["dense_score"]

        if program_scope_query:
            for record in fused.values():
                if record.get("source_type") == "program_handbook":
                    record["scope_bonus"] = 0.01
                    record["rrf_score"] += record["scope_bonus"]
        if query_identifiers:
            for record in fused.values():
                searchable_identity = (
                    f"{record.get('source_id', '')} "
                    f"{record.get('title', '')}"
                ).upper()
                if any(
                    identifier in searchable_identity
                    for identifier in query_identifiers
                ):
                    record["identifier_bonus"] = 0.02
                    record["rrf_score"] += record["identifier_bonus"]

        ranked = sorted(
            fused.values(),
            key=lambda item: (
                item["rrf_score"],
                item.get("dense_score", float("-inf")),
            ),
            reverse=True,
        )
        reranker_error = None
        if self.reranker is not None:
            try:
                ranked = self._blend_reranker_rank(
                    self.reranker.rerank(query, ranked),
                    rrf_constant=self.rrf_constant,
                )
            except Exception as exc:
                reranker_error = type(exc).__name__
        self.last_search_diagnostics["reranker_active"] = (
            self.reranker is not None
        )
        self.last_search_diagnostics["reranker_error"] = reranker_error
        self.last_search_diagnostics["degraded"] = (
            self.last_search_diagnostics["degraded"]
            or reranker_error is not None
        )
        selected: list[dict[str, Any]] = []
        seen_parents: set[str] = set()
        for item in ranked:
            parent_id = item["parent_id"]
            if parent_id in seen_parents:
                continue
            seen_parents.add(parent_id)
            selected.append(
                {
                    **item,
                    "document_id": item["chunk_id"],
                    "score": round(item["rrf_score"], 6),
                    "content": item["parent_content"],
                }
            )
            if len(selected) >= k:
                break
        return selected

    @staticmethod
    def _blend_reranker_rank(
        reranked: list[dict[str, Any]],
        *,
        rrf_constant: int,
    ) -> list[dict[str, Any]]:
        for rank, item in enumerate(reranked, start=1):
            item["reranker_rrf_score"] = 1 / (rrf_constant + rank)
            item["rrf_score"] += item["reranker_rrf_score"]
        return sorted(
            reranked,
            key=lambda item: (
                item["rrf_score"],
                item.get("rerank_score", float("-inf")),
            ),
            reverse=True,
        )

    @staticmethod
    def _is_program_scope_query(query: str) -> bool:
        normalized = query.lower()
        return any(
            marker in normalized
            for marker in (
                "course structure",
                "program structure",
                "degree requirement",
                "credit requirement",
                "specialisation",
                "specialization",
                "项目结构",
                "培养方案",
                "毕业要求",
                "专业方向",
            )
        )

    def _lexical_search(
        self,
        query: str,
        *,
        handbook_year: int | None,
        university_id: str | None,
        discipline_id: str | None,
        program_code: str | None,
        k: int,
    ) -> list[dict[str, Any]]:
        query_tokens = self._tokenize(query)
        filter_tokens = {
            item.lower()
            for item in (
                university_id,
                program_code,
                str(handbook_year) if handbook_year is not None else None,
            )
            if item
        }
        query_tokens = [
            token for token in query_tokens if token not in filter_tokens
        ]
        if not query_tokens:
            return []
        scores = self._bm25.get_scores(query_tokens)
        matches: list[tuple[float, HandbookChunk]] = []
        for chunk, score in zip(self.chunks, scores, strict=True):
            if score <= 0 or not self._matches(
                chunk,
                handbook_year=handbook_year,
                university_id=university_id,
                discipline_id=discipline_id,
                program_code=program_code,
            ):
                continue
            matches.append((float(score), chunk))
        matches.sort(key=lambda item: item[0], reverse=True)
        return [
            {
                **chunk.to_dict(),
                "discipline_ids": "|".join(chunk.discipline_ids),
                "document_id": chunk.chunk_id,
                "bm25_score": round(score, 6),
            }
            for score, chunk in matches[:k]
        ]

    @staticmethod
    def _matches(
        chunk: HandbookChunk,
        *,
        handbook_year: int | None,
        university_id: str | None,
        discipline_id: str | None,
        program_code: str | None,
    ) -> bool:
        return all(
            (
                handbook_year is None
                or chunk.handbook_year == handbook_year,
                university_id is None
                or chunk.university_id == university_id,
                discipline_id is None
                or discipline_id in chunk.discipline_ids,
                program_code is None
                or program_code in chunk.program_codes
                or chunk.program_code == program_code,
            )
        )

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        normalized = text.lower()
        words = re.findall(r"[a-z0-9]+", normalized)
        chinese_runs = re.findall(r"[\u4e00-\u9fff]+", normalized)
        chinese_tokens = [
            run[index : index + 2]
            for run in chinese_runs
            for index in range(max(len(run) - 1, 1))
        ]
        return words + chinese_tokens
