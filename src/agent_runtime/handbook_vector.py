"""Handbook chunking plus compatibility exports for retrieval implementations.

Storage-specific lexical, dense, and fusion logic lives under `retrieval/`;
imports remain here so existing scripts and integrations keep working.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST_PATH = REPO_ROOT / "data" / "handbook_source_manifest.json"
DEFAULT_EXTRACTION_REPORT_PATH = (
    REPO_ROOT / "data" / "official_sources" / "extraction-report.json"
)
DEFAULT_CHUNK_PATH = (
    REPO_ROOT / "data" / "official_sources" / "handbook-chunks.jsonl"
)
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


# Imported after HandbookChunk is defined so retrieval implementations can use
# it for type checking without introducing a runtime import cycle.
from .retrieval import (  # noqa: E402
    BGEM3DenseEmbedder,
    CampusPilotHybridRetriever,
    CampusPilotMilvusStore,
    DenseEmbedder,
    MILVUS_VARCHAR_LIMITS,
    SentenceTransformerDenseEmbedder,
    SentenceTransformerReranker,
    create_dense_embedder,
    validate_milvus_chunks,
)

__all__ = [
    "BGEM3DenseEmbedder",
    "CampusPilotHybridRetriever",
    "CampusPilotMilvusStore",
    "DEFAULT_CHUNK_PATH",
    "DEFAULT_EXTRACTION_REPORT_PATH",
    "DEFAULT_MANIFEST_PATH",
    "DenseEmbedder",
    "HandbookChunk",
    "HandbookChunker",
    "MILVUS_VARCHAR_LIMITS",
    "SentenceTransformerDenseEmbedder",
    "SentenceTransformerReranker",
    "build_ready_corpus",
    "create_dense_embedder",
    "parse_markdown_document",
    "read_chunks",
    "validate_milvus_chunks",
    "write_chunks",
]
