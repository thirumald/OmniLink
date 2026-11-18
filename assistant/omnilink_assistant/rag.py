"""Knowledge base for runbooks, SOPs, manuals and past incidents (pgvector in production)."""

from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass, field

from .llm import LLM


@dataclass
class Chunk:
    id: str
    tenant: str
    doc: str
    text: str
    meta: dict = field(default_factory=dict)
    vector: list[float] = field(default_factory=list)


def chunk_markdown(text: str, max_chars: int = 1200, overlap: int = 150) -> list[str]:
    """Split on headings first, then by size with overlap."""
    sections = re.split(r"(?m)^(?=#{1,3} )", text)
    out = []
    for s in sections:
        s = s.strip()
        if not s:
            continue
        while len(s) > max_chars:
            cut = s.rfind("\n", 0, max_chars)
            cut = cut if cut > max_chars // 2 else max_chars
            out.append(s[:cut].strip())
            s = s[max(cut - overlap, 1):]
        out.append(s)
    return [c for c in out if c]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class MemoryKnowledgeBase:
    def __init__(self, llm: LLM):
        self.llm = llm
        self.chunks: list[Chunk] = []

    async def ingest(self, tenant: str, doc: str, text: str, meta: dict | None = None) -> int:
        parts = chunk_markdown(text)
        vecs = await self.llm.embed(parts)
        self.chunks = [c for c in self.chunks if not (c.tenant == tenant and c.doc == doc)]
        self.chunks += [Chunk(str(uuid.uuid4()), tenant, doc, p, meta or {}, v) for p, v in zip(parts, vecs)]
        return len(parts)

    async def search(self, tenant: str, query: str, k: int = 4) -> list[Chunk]:
        [qv] = await self.llm.embed([query])
        scored = sorted((c for c in self.chunks if c.tenant == tenant), key=lambda c: cosine(qv, c.vector), reverse=True)
        return scored[:k]


PGVECTOR_DDL = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS kb_chunks (
    id uuid PRIMARY KEY, tenant_id text NOT NULL, doc text NOT NULL, text text NOT NULL,
    meta jsonb NOT NULL DEFAULT '{}', embedding vector(1024) NOT NULL
);
CREATE INDEX IF NOT EXISTS kb_chunks_hnsw ON kb_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS kb_chunks_tenant ON kb_chunks (tenant_id, doc);
"""


class PgKnowledgeBase:  # pragma: no cover - integration path
    def __init__(self, llm: LLM, pool):
        self.llm, self.pool = llm, pool

    async def ingest(self, tenant, doc, text, meta=None):
        parts = chunk_markdown(text)
        vecs = await self.llm.embed(parts)
        async with self.pool.acquire() as c, c.transaction():
            await c.execute("DELETE FROM kb_chunks WHERE tenant_id=$1 AND doc=$2", tenant, doc)
            await c.executemany("INSERT INTO kb_chunks (id, tenant_id, doc, text, meta, embedding) VALUES ($1,$2,$3,$4,$5,$6)",
                                [(uuid.uuid4(), tenant, doc, p, meta or {}, str(v)) for p, v in zip(parts, vecs)])
        return len(parts)

    async def search(self, tenant, query, k=4):
        [qv] = await self.llm.embed([query])
        async with self.pool.acquire() as c:
            rows = await c.fetch("""SELECT id, doc, text, meta FROM kb_chunks WHERE tenant_id=$1
                                    ORDER BY embedding <=> $2::vector LIMIT $3""", tenant, str(qv), k)
        return [Chunk(str(r["id"]), tenant, r["doc"], r["text"], r["meta"]) for r in rows]
