"""Dense embedding and Milvus adapters for semantic evidence retrieval.

Lexical evidence belongs to Elasticsearch and deterministic academic facts
belong to PostgreSQL; this module owns neither responsibility.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from ..handbook_vector import HandbookChunk


MILVUS_VARCHAR_LIMITS = {
    "chunk_id": 64,
    "parent_id": 160,
    "source_id": 160,
    "university_id": 48,
    "program_code": 64,
    "program_codes": 2048,
    "source_type": 64,
    "discipline_ids": 256,
    "specialisation_codes": 1024,
    "title": 1024,
    "heading": 2048,
    "content": 65535,
    "parent_content": 65535,
    "source_url": 4096,
    "source_sha256": 64,
}


class DenseEmbedder(Protocol):
    dimension: int

    def encode(self, texts: list[str]) -> list[list[float]]: ...


def validate_milvus_chunks(chunks: Iterable[HandbookChunk]) -> None:
    """Fail before ingestion when a chunk exceeds the fixed Milvus schema."""
    for position, chunk in enumerate(chunks):
        row = {
            **chunk.to_dict(),
            "discipline_ids": "|".join(chunk.discipline_ids),
            "specialisation_codes": (
                "|" + "|".join(chunk.specialisation_codes) + "|"
                if chunk.specialisation_codes
                else ""
            ),
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
    """CPU-safe BGE-M3 dense-vector adapter."""
    dimension = 1024

    def __init__(self, model_path: str | Path) -> None:
        import os
        import torch
        from FlagEmbedding import BGEM3FlagModel

        torch.set_num_threads(max(1, os.cpu_count() or 1))
        self.model = BGEM3FlagModel(str(model_path), use_fp16=False)

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
    """Normalized dense-vector adapter for sentence transformers."""
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
    """Persist and query semantic Handbook candidates in Milvus."""
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

    def has_collection(self) -> bool:
        """Return whether the configured semantic collection exists."""

        return bool(self.client.has_collection(self.collection_name))

    def recreate_collection(self) -> None:
        from pymilvus import DataType

        if self.has_collection():
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
            "specialisation_codes",
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
        schema.add_field(field_name="handbook_year", datatype=DataType.INT64)
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
            rows = self._rows(batch)
            self.client.insert(
                collection_name=self.collection_name,
                data=rows,
            )
            inserted += len(rows)
            if progress_callback is not None:
                progress_callback(inserted, len(chunks) - inserted)
        self.client.flush(self.collection_name)
        return inserted

    def upsert(
        self,
        chunks: list[HandbookChunk],
        *,
        batch_size: int = 64,
    ) -> int:
        """Encode and replace changed chunks without rebuilding collection."""

        if not chunks:
            return 0
        for offset in range(0, len(chunks), batch_size):
            batch = chunks[offset : offset + batch_size]
            self.client.upsert(
                collection_name=self.collection_name,
                data=self._rows(batch),
            )
        self.client.flush(self.collection_name)
        return len(chunks)

    def delete(self, chunk_ids: list[str]) -> int:
        """Delete stale semantic vectors by stable chunk identity."""

        if not chunk_ids:
            return 0
        self.client.delete(
            collection_name=self.collection_name,
            ids=chunk_ids,
        )
        self.client.flush(self.collection_name)
        return len(chunk_ids)

    def _rows(self, chunks: list[HandbookChunk]) -> list[dict[str, Any]]:
        vectors = self.embedder.encode(
            [chunk.embedding_text for chunk in chunks]
        )
        # List metadata is delimiter-wrapped because this schema stores it in
        # VARCHAR fields and still needs exact containment filters.
        return [
            {
                **chunk.to_dict(),
                "discipline_ids": "|".join(chunk.discipline_ids),
                "specialisation_codes": (
                    "|" + "|".join(chunk.specialisation_codes) + "|"
                    if chunk.specialisation_codes
                    else ""
                ),
                "program_codes": (
                    "|" + "|".join(chunk.program_codes) + "|"
                    if chunk.program_codes
                    else ""
                ),
                "dense_vector": vector,
            }
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]

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
        specialisation_code: str | None = None,
        source_type: str | None = None,
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
                "program_codes like "
                f'"%|{self._escape(program_code)}|%"'
            )
        if discipline_id:
            filters.append(
                f'discipline_ids like "%{self._escape(discipline_id)}%"'
            )
        if source_type:
            filters.append(
                f'source_type == "{self._escape(source_type)}"'
            )
        if specialisation_code:
            filters.append(
                "specialisation_codes like "
                f'"%|{self._escape(specialisation_code)}|%"'
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
                "specialisation_codes",
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
