"""Ingest EduRAG AI documents into Milvus.

This keeps the original PDF pipeline, but loads Markdown with a lightweight
splitter to avoid UnstructuredMarkdownLoader's NLTK runtime dependency.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

from langchain.docstore.document import Document
from langchain.text_splitter import MarkdownTextSplitter


def project_root() -> Path:
    return Path(os.environ.get("EDURAG_PROJECT_ROOT", r"D:\agentdev\integrated_qa_system"))


def prepare_imports(root: Path) -> None:
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "rag_qa"))
    sys.path.insert(0, str(root / "rag_qa" / "core"))


def load_markdown_chunks(root: Path) -> list[Document]:
    md_path = root / "rag_qa" / "data" / "ai_data" / "人工智能就业课课程大纲.md"
    if not md_path.exists():
        return []

    text = md_path.read_text(encoding="utf-8")
    parent_splitter = MarkdownTextSplitter(chunk_size=1200, chunk_overlap=50)
    child_splitter = MarkdownTextSplitter(chunk_size=300, chunk_overlap=50)
    timestamp = datetime.now().isoformat()

    base_doc = Document(
        page_content=text,
        metadata={"source": "ai", "file_path": str(md_path), "timestamp": timestamp},
    )

    chunks: list[Document] = []
    for parent_index, parent_doc in enumerate(parent_splitter.split_documents([base_doc])):
        parent_id = f"md_course_parent_{parent_index}"
        for child_index, child_doc in enumerate(child_splitter.split_documents([parent_doc])):
            child_doc.metadata.update(
                {
                    "source": "ai",
                    "file_path": str(md_path),
                    "timestamp": timestamp,
                    "parent_id": parent_id,
                    "parent_content": parent_doc.page_content,
                    "id": f"{parent_id}_child_{child_index}",
                }
            )
            chunks.append(child_doc)

    return chunks


def main() -> None:
    root = project_root()
    prepare_imports(root)

    from core.document_processor import process_documents
    from core.vector_store import VectorStore

    data_dir = root / "rag_qa" / "data" / "ai_data"
    processed_chunks = process_documents(str(data_dir))
    pdf_chunks = [
        doc for doc in processed_chunks if doc.metadata.get("file_path", "").lower().endswith(".pdf")
    ]
    md_chunks = load_markdown_chunks(root)

    print(f"pdf_chunks={len(pdf_chunks)}")
    print(f"md_chunks={len(md_chunks)}")

    vector_store = VectorStore()
    all_chunks = pdf_chunks + md_chunks
    for index, chunk in enumerate(all_chunks, start=1):
        print(f"upserting {index}/{len(all_chunks)}", flush=True)
        vector_store.add_documents([chunk])

    stats = vector_store.client.get_collection_stats(vector_store.collection_name)
    print(f"milvus_stats={stats}")


if __name__ == "__main__":
    main()
