from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from openai import AsyncOpenAI

from app.config import KNOWLEDGE_DIR, get_settings

log = logging.getLogger("harbor.rag")


@dataclass
class Chunk:
    title: str
    source: str
    text: str
    embedding: np.ndarray | None = None


def _split_markdown(path: Path) -> list[Chunk]:
    raw = path.read_text(encoding="utf-8")
    parts = re.split(r"(?m)^## ", raw)
    chunks: list[Chunk] = []
    header = parts[0].strip()
    title = header.split("\n", 1)[0].lstrip("# ").strip() or path.stem
    if len(parts) == 1:
        chunks.append(Chunk(title=title, source=path.name, text=raw.strip()))
        return chunks
    lead = parts[0].strip()
    if lead:
        chunks.append(Chunk(title=title, source=path.name, text=lead))
    for part in parts[1:]:
        lines = part.strip().split("\n", 1)
        heading = lines[0].strip()
        body = lines[1].strip() if len(lines) > 1 else ""
        chunks.append(
            Chunk(
                title=f"{title} — {heading}",
                source=path.name,
                text=f"{heading}\n{body}".strip(),
            )
        )
    return chunks


class KnowledgeStore:
    def __init__(self) -> None:
        self.chunks: list[Chunk] = []
        self._ready = False

    async def load(self) -> None:
        self.chunks = []
        if not KNOWLEDGE_DIR.exists():
            log.warning("Knowledge dir missing: %s", KNOWLEDGE_DIR)
            return
        for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
            self.chunks.extend(_split_markdown(path))
        settings = get_settings()
        if not settings.openai_api_key or settings.tts_provider != "openai":
            log.info("RAG using keyword search (no OpenAI embeddings)")
            self._ready = True
            return
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        texts = [c.text for c in self.chunks]
        try:
            resp = await client.embeddings.create(
                model="text-embedding-3-small",
                input=texts,
            )
            for chunk, item in zip(self.chunks, resp.data, strict=True):
                chunk.embedding = np.array(item.embedding, dtype=np.float32)
            self._ready = True
            log.info("Embedded %d knowledge chunks", len(self.chunks))
        except Exception:
            log.exception("Embedding failed; falling back to keywords")
            self._ready = True

    def search(self, query: str, k: int = 3) -> list[dict]:
        if not query.strip() or not self.chunks:
            return []
        ranked = self._embed_rank(query) if self._has_embeddings() else self._keyword_rank(query)
        hits = []
        for score, chunk in ranked[:k]:
            hits.append(
                {
                    "title": chunk.title,
                    "source": chunk.source,
                    "text": chunk.text[:900],
                    "score": round(float(score), 3),
                }
            )
        return hits

    def _has_embeddings(self) -> bool:
        return bool(self.chunks) and self.chunks[0].embedding is not None

    def _embed_rank(self, query: str) -> list[tuple[float, Chunk]]:
        # Query embedding is computed lazily via a sync-unfriendly path;
        # callers that need true vectors should use search_async. This
        # fallback ranks with keywords if we cannot embed the query here.
        return self._keyword_rank(query)

    def _keyword_rank(self, query: str) -> list[tuple[float, Chunk]]:
        terms = [t for t in re.findall(r"[a-z0-9']+", query.lower()) if len(t) > 2]
        scored: list[tuple[float, Chunk]] = []
        for chunk in self.chunks:
            blob = chunk.text.lower()
            score = sum(blob.count(t) for t in terms)
            if score:
                scored.append((float(score), chunk))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored or [(0.0, c) for c in self.chunks[:3]]

    async def search_async(self, query: str, k: int = 3) -> list[dict]:
        settings = get_settings()
        if not settings.openai_api_key or not self._has_embeddings():
            return self.search(query, k=k)
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        try:
            resp = await client.embeddings.create(
                model="text-embedding-3-small",
                input=query,
            )
            q = np.array(resp.data[0].embedding, dtype=np.float32)
            scored: list[tuple[float, Chunk]] = []
            for chunk in self.chunks:
                if chunk.embedding is None:
                    continue
                denom = float(np.linalg.norm(q) * np.linalg.norm(chunk.embedding)) or 1e-9
                score = float(np.dot(q, chunk.embedding) / denom)
                scored.append((score, chunk))
            scored.sort(key=lambda x: x[0], reverse=True)
            hits = []
            for score, chunk in scored[:k]:
                hits.append(
                    {
                        "title": chunk.title,
                        "source": chunk.source,
                        "text": chunk.text[:900],
                        "score": round(score, 3),
                    }
                )
            return hits
        except Exception:
            log.exception("Query embed failed")
            return self.search(query, k=k)


store = KnowledgeStore()
