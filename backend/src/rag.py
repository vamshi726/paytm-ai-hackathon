"""Local-Markdown RAG using LangChain documents and a local retriever."""
from __future__ import annotations

import math
import os
import re
from collections import Counter
from pathlib import Path

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import ConfigDict

DOCS_DIR = Path(__file__).resolve().parents[1] / "knowledge_base"
CHROMA_DIR = Path(__file__).resolve().parents[1] / ".chroma"


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


class MarkdownVectorStore:
    """Split local Markdown into LangChain documents and retrieve relevant chunks."""

    def __init__(self, docs_dir: Path = DOCS_DIR):
        self.docs_dir = docs_dir
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=700,
            chunk_overlap=80,
            add_start_index=True,
        )
        self.documents = self._load_markdown()
        self.collection = None
        if os.getenv("SAATHI_DISABLE_CHROMA", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            return
        try:
            import chromadb

            client = chromadb.PersistentClient(path=str(CHROMA_DIR))
            self.collection = client.get_or_create_collection("saathi_md_playbooks")
            current_ids = [f"md-{i}" for i in range(len(self.documents))]
            existing_ids = self.collection.get(include=[])["ids"]
            stale_ids = [item_id for item_id in existing_ids if item_id not in current_ids]
            if stale_ids:
                self.collection.delete(ids=stale_ids)
            self.collection.upsert(
                ids=current_ids,
                documents=[item["content"] for item in self.documents],
                metadatas=[{"source": item["source"]} for item in self.documents],
                embeddings=[self._embed(item["content"]) for item in self.documents],
            )
        except ImportError:
            pass

    def _load_markdown(self) -> list[dict[str, str]]:
        documents = []
        for path in sorted(self.docs_dir.glob("*.md")):
            for section in re.split(
                r"(?=^## )",
                path.read_text(encoding="utf-8"),
                flags=re.MULTILINE,
            ):
                if not section.strip():
                    continue
                source_document = Document(
                    page_content=section.strip(),
                    metadata={"source": path.name},
                )
                documents.extend(
                    {
                        "source": chunk.metadata["source"],
                        "content": chunk.page_content,
                    }
                    for chunk in self.splitter.split_documents([source_document])
                )
        return documents

    @staticmethod
    def _embed(text: str) -> list[float]:
        vector = [0.0] * 128
        for word in tokens(text):
            vector[hash(word) % 128] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector

    def as_retriever(self, limit: int = 2) -> BaseRetriever:
        return MarkdownRetriever(store=self, limit=limit)

    def search(self, query: str, limit: int = 2) -> list[dict[str, str | float]]:
        documents = self.as_retriever(limit).invoke(query)
        return [
            {
                "source": document.metadata["source"],
                "content": document.page_content,
                "score": document.metadata["score"],
            }
            for document in documents
        ]

    def _search(self, query: str, limit: int) -> list[dict[str, str | float]]:
        if not self.documents:
            return []
        if self.collection is not None:
            found = self.collection.query(
                query_embeddings=[self._embed(query)],
                n_results=min(limit, len(self.documents)),
                include=["documents", "metadatas", "distances"],
            )
            return [
                {
                    "source": metadata["source"],
                    "content": content,
                    "score": round(1 - distance, 3),
                }
                for content, metadata, distance in zip(
                    found["documents"][0],
                    found["metadatas"][0],
                    found["distances"][0],
                )
            ]

        query_terms = Counter(tokens(query))
        scored = []
        for item in self.documents:
            document_terms = Counter(tokens(item["content"]))
            dot = sum(query_terms[word] * document_terms[word] for word in query_terms)
            denominator = math.sqrt(
                sum(value * value for value in query_terms.values())
                * sum(value * value for value in document_terms.values())
            )
            scored.append(
                {
                    **item,
                    "score": round(dot / denominator if denominator else 0, 3),
                }
            )
        return [
            item
            for item in sorted(scored, key=lambda item: item["score"], reverse=True)[
                :limit
            ]
            if item["score"] > 0
        ]


class MarkdownRetriever(BaseRetriever):
    store: MarkdownVectorStore
    limit: int = 2
    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        return [
            Document(
                page_content=item["content"],
                metadata={"source": item["source"], "score": item["score"]},
            )
            for item in self.store._search(query, self.limit)
        ]


vector_store = MarkdownVectorStore()
