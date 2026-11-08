"""BM25 + exact symbol/path retrieval with 1-hop graph neighborhood expansion."""

from __future__ import annotations

import re
from typing import Any

import networkx as nx
from rank_bm25 import BM25Okapi

TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
STOPWORDS = {
    "where",
    "what",
    "which",
    "when",
    "who",
    "whom",
    "whose",
    "why",
    "how",
    "does",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "the",
    "and",
    "or",
    "for",
    "in",
    "on",
    "at",
    "to",
    "from",
    "with",
    "by",
    "about",
    "into",
    "this",
    "that",
    "these",
    "those",
    "can",
    "could",
    "would",
    "should",
    "defined",
    "handled",
    "work",
    "works",
    "file",
    "function",
    "class",
    "code",
    "repo",
    "repository",
}


def tokenize_code(text: str) -> list[str]:
    """Split identifiers on snake_case and camelCase in addition to raw words."""
    tokens: list[str] = []
    for raw in TOKEN_RE.findall(text):
        lower = raw.lower()
        if lower in STOPWORDS or len(lower) < 2:
            continue
        tokens.append(lower)
        subparts = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", raw).lower().split("_")
        for sp in subparts:
            if len(sp) > 1 and sp != lower and sp not in STOPWORDS:
                tokens.append(sp)
    return tokens


class CodeRetriever:
    """Fast local retriever over AST chunks using BM25 + exact symbol/path boosts."""

    def __init__(self, chunks: list[dict[str, Any]]) -> None:
        self.chunks = chunks
        self.corpus_tokens = [
            tokenize_code(f"{c['path']} {c['symbol']} {c.get('text', '')}")
            for c in chunks
        ]
        self.corpus_token_sets = [set(toks) for toks in self.corpus_tokens]
        self.bm25 = BM25Okapi(self.corpus_tokens) if self.corpus_tokens else None

    def retrieve(
        self,
        question: str,
        graph: nx.DiGraph | None = None,
        top_k: int = 6,
    ) -> list[dict[str, Any]]:
        if not self.chunks:
            return []

        q_tokens = tokenize_code(question)
        if not q_tokens:
            return []
        q_unique = set(q_tokens)
        q_lower = question.lower()
        scores = (
            list(self.bm25.get_scores(q_tokens))
            if self.bm25
            else [0.0] * len(self.chunks)
        )

        # Require reasonable keyword coverage unless an exact symbol or path name is mentioned
        min_overlap = 1 if len(q_unique) <= 2 else max(2, int(len(q_unique) * 0.4))

        scored_indices: list[tuple[float, int]] = []
        for idx, chunk in enumerate(self.chunks):
            # Avoid matching test files on self-referential test string literals unless question asks for tests
            if chunk["path"].startswith("tests/") or "/tests/" in chunk["path"]:
                if "test" not in q_lower:
                    continue

            overlap = len(q_unique & self.corpus_token_sets[idx])
            if overlap == 0:
                continue

            sym_lower = chunk["symbol"].lower()
            path_lower = chunk["path"].lower()
            exact_symbol = len(sym_lower) >= 3 and sym_lower in q_lower
            exact_path = path_lower in q_lower or path_lower.split("/")[-1] in q_lower

            if not exact_symbol and not exact_path and overlap < min_overlap:
                continue

            score = max(0.0, float(scores[idx])) + overlap * 1.5
            if exact_symbol:
                score += 8.0
            if exact_path:
                score += 6.0
            for tok in q_unique:
                if len(tok) >= 3 and tok in sym_lower:
                    score += 2.5
                if len(tok) >= 3 and tok in path_lower:
                    score += 1.5

            if score >= 1.5:
                scored_indices.append((score, idx))

        scored_indices.sort(key=lambda pair: (-pair[0], pair[1]))
        primary = [
            {**self.chunks[idx], "score": round(score, 2)}
            for score, idx in scored_indices[:top_k]
        ]

        # Expand 1-hop imports/dependents if slots remain
        if graph is not None and primary and len(primary) < top_k:
            seen_ids = {c["id"] for c in primary}
            neighbor_paths: set[str] = set()
            for c in primary[:2]:
                p = c["path"]
                if p in graph:
                    neighbor_paths.update(graph.successors(p))
                    neighbor_paths.update(graph.predecessors(p))
            for chunk in self.chunks:
                if chunk["path"] in neighbor_paths and chunk["id"] not in seen_ids:
                    primary.append({**chunk, "score": 0.5})
                    seen_ids.add(chunk["id"])
                    if len(primary) >= top_k:
                        break

        return primary
