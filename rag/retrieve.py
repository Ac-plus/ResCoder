# -*- coding: utf-8 -*-
"""
retrieve.py

Hybrid retrieval: BM25 + Embedding (FAISS) for multi-library RAG.

- Two libraries: FAQ, Standards
- Each library returns top_n_per_lib chunks (default 3)
- Score fusion: final = w_bm25 * bm25_norm + w_vec * vec_norm
  where bm25_norm and vec_norm are min-max normalized within the candidate pool.

Constraints:
- Embedding model must be local, no online downloads.
- Python 3.8 compatible.
"""

import os
import json
import math
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional

import numpy as np
import faiss
from sentence_transformers import SentenceTransformer


# =========================
# Paths (default)
# =========================
DEFAULT_INDEX_DIR = Path("/root/agent/rag/index")
DEFAULT_EMBED_MODEL_DIR = Path("/root/agent/rag/embed_models/bge-small-zh-v1.5")


# =========================
# Minimal BM25 implementation (no external deps)
# =========================
def _is_cjk(ch: str) -> bool:
    o = ord(ch)
    # CJK Unified Ideographs + common ranges
    return (
        0x4E00 <= o <= 0x9FFF
        or 0x3400 <= o <= 0x4DBF
        or 0x20000 <= o <= 0x2A6DF
        or 0x2A700 <= o <= 0x2B73F
        or 0x2B740 <= o <= 0x2B81F
        or 0x2B820 <= o <= 0x2CEAF
        or 0xF900 <= o <= 0xFAFF
    )

def simple_tokenize(text: str) -> List[str]:
    """
    Very lightweight tokenizer for mixed zh/en:
    - English: split by non-alnum
    - Chinese: each CJK char as a token
    """
    if not text:
        return []
    text = text.strip()
    toks: List[str] = []
    buf: List[str] = []
    for ch in text:
        if _is_cjk(ch):
            if buf:
                toks.append("".join(buf).lower())
                buf = []
            toks.append(ch)
        else:
            if ch.isalnum() or ch in ("_", "-"):
                buf.append(ch)
            else:
                if buf:
                    toks.append("".join(buf).lower())
                    buf = []
    if buf:
        toks.append("".join(buf).lower())
    # drop empty
    return [t for t in toks if t]

class BM25:
    """
    Minimal BM25 Okapi over a list of documents (token lists).
    """
    def __init__(self, corpus_tokens: List[List[str]], k1: float = 1.5, b: float = 0.75):
        self.k1 = float(k1)
        self.b = float(b)
        self.corpus = corpus_tokens
        self.N = len(corpus_tokens)

        self.doc_lens = [len(x) for x in corpus_tokens]
        self.avgdl = (sum(self.doc_lens) / float(self.N)) if self.N > 0 else 0.0

        # df
        df: Dict[str, int] = {}
        for doc in corpus_tokens:
            seen = set(doc)
            for t in seen:
                df[t] = df.get(t, 0) + 1
        self.df = df

        # idf
        self.idf: Dict[str, float] = {}
        for t, dfi in df.items():
            # classic BM25 idf
            self.idf[t] = math.log(1.0 + (self.N - dfi + 0.5) / (dfi + 0.5))

        # term freq per doc
        self.tfs: List[Dict[str, int]] = []
        for doc in corpus_tokens:
            tf: Dict[str, int] = {}
            for t in doc:
                tf[t] = tf.get(t, 0) + 1
            self.tfs.append(tf)

    def score(self, query_tokens: List[str]) -> List[float]:
        scores = [0.0] * self.N
        if self.N == 0:
            return scores
        for i in range(self.N):
            dl = self.doc_lens[i]
            tf = self.tfs[i]
            s = 0.0
            for t in query_tokens:
                if t not in tf:
                    continue
                f = tf[t]
                idf = self.idf.get(t, 0.0)
                denom = f + self.k1 * (1.0 - self.b + self.b * (dl / (self.avgdl + 1e-12)))
                s += idf * (f * (self.k1 + 1.0)) / (denom + 1e-12)
            scores[i] = s
        return scores


# =========================
# Loading chunks/index per library
# =========================
def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out

def _load_faiss(index_path: Path) -> faiss.Index:
    return faiss.read_index(str(index_path))

def _minmax_norm(xs: List[float]) -> List[float]:
    if not xs:
        return xs
    mn = min(xs)
    mx = max(xs)
    if mx - mn < 1e-12:
        # all equal -> return 1.0 for non-zero values else 0.0
        return [1.0 if x > 0 else 0.0 for x in xs]
    return [(x - mn) / (mx - mn) for x in xs]


# =========================
# Retriever
# =========================
class HybridRetriever:
    """
    Loads two FAISS indexes + chunks, and builds BM25 corpus per library.
    """

    def __init__(
        self,
        index_dir: Path = DEFAULT_INDEX_DIR,
        embed_model_dir: Path = DEFAULT_EMBED_MODEL_DIR,
        device: str = "cpu",
    ):
        self.index_dir = Path(index_dir)
        self.embed_model_dir = Path(embed_model_dir)

        if not self.index_dir.exists():
            raise FileNotFoundError("index_dir not found: %s" % str(self.index_dir))
        if not self.embed_model_dir.exists():
            raise FileNotFoundError("embed_model_dir not found: %s" % str(self.embed_model_dir))

        # Force offline
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_HUB_OFFLINE"] = "1"

        self.embedder = SentenceTransformer(str(self.embed_model_dir), device=device)

        # Load FAQ
        self.faq_chunks = _read_jsonl(self.index_dir / "faq_chunks.jsonl")
        self.faq_index = _load_faiss(self.index_dir / "faq.index")

        # Load Standards
        self.std_chunks = _read_jsonl(self.index_dir / "standards_chunks.jsonl")
        self.std_index = _load_faiss(self.index_dir / "standards.index")

        # Build BM25 corpora
        self.faq_tokens = [simple_tokenize(x.get("text", "")) for x in self.faq_chunks]
        self.std_tokens = [simple_tokenize(x.get("text", "")) for x in self.std_chunks]

        self.faq_bm25 = BM25(self.faq_tokens)
        self.std_bm25 = BM25(self.std_tokens)

    def _embed_query(self, query: str) -> np.ndarray:
        qv = self.embedder.encode(
            [query],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).astype("float32")
        return qv

    def _faiss_topk(self, index: faiss.Index, qv: np.ndarray, topk: int) -> Tuple[List[int], List[float]]:
        scores, ids = index.search(qv, topk)
        id_list = ids[0].tolist()
        sc_list = scores[0].tolist()
        # filter invalid
        out_ids: List[int] = []
        out_sc: List[float] = []
        for i, s in zip(id_list, sc_list):
            if i is None or int(i) < 0:
                continue
            out_ids.append(int(i))
            out_sc.append(float(s))
        return out_ids, out_sc

    def _hybrid_rank_one_lib(
        self,
        lib_name: str,
        query: str,
        chunks: List[Dict[str, Any]],
        bm25: BM25,
        faiss_index: faiss.Index,
        top_n: int,
        faiss_topk: int,
        w_bm25: float,
        w_vec: float,
    ) -> List[Dict[str, Any]]:
        """
        1) Get FAISS topk candidates
        2) Compute BM25 scores over the same candidate set
        3) Normalize scores within candidates
        4) Weighted mean fusion
        """
        q_tokens = simple_tokenize(query)
        qv = self._embed_query(query)

        cand_ids, vec_scores = self._faiss_topk(faiss_index, qv, faiss_topk)

        # If index is tiny or returns nothing
        if not cand_ids:
            return []

        # BM25 scores for all docs, then pick candidate subset
        bm25_all = bm25.score(q_tokens)
        bm25_scores = [float(bm25_all[i]) if 0 <= i < len(bm25_all) else 0.0 for i in cand_ids]

        # Normalize within candidates
        vec_norm = _minmax_norm(vec_scores)
        bm25_norm = _minmax_norm(bm25_scores)

        fused = []
        for rank, (idx, vs, bs, vn, bn) in enumerate(zip(cand_ids, vec_scores, bm25_scores, vec_norm, bm25_norm)):
            final = float(w_vec) * float(vn) + float(w_bm25) * float(bn)
            meta = chunks[idx]
            fused.append(
                {
                    "library": lib_name,
                    "chunk_id": meta.get("id", ""),
                    "source_relpath": meta.get("source_relpath", meta.get("source_relpath", meta.get("source_relpath", ""))),
                    "source_path": meta.get("source_path", ""),
                    "chunk_index": meta.get("chunk_index", -1),
                    "text": meta.get("text", ""),
                    "score": final,
                    "score_vec_raw": float(vs),
                    "score_bm25_raw": float(bs),
                    "score_vec_norm": float(vn),
                    "score_bm25_norm": float(bn),
                    "cand_rank_vec": int(rank),
                }
            )

        fused.sort(key=lambda x: x["score"], reverse=True)
        return fused[:top_n]

    def retrieve(
        self,
        query: str,
        top_n_per_lib: int = 3,
        faiss_topk: int = 20,
        w_bm25: float = 0.5,
        w_vec: float = 0.5,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Return:
          {
            "FAQ": [ ... top_n_per_lib ... ],
            "Standards": [ ... top_n_per_lib ... ]
          }
        """
        # normalize weights
        s = float(w_bm25) + float(w_vec)
        if s <= 0:
            w_bm25, w_vec = 0.5, 0.5
        else:
            w_bm25, w_vec = float(w_bm25) / s, float(w_vec) / s

        faq_hits = self._hybrid_rank_one_lib(
            lib_name="FAQ",
            query=query,
            chunks=self.faq_chunks,
            bm25=self.faq_bm25,
            faiss_index=self.faq_index,
            top_n=top_n_per_lib,
            faiss_topk=faiss_topk,
            w_bm25=w_bm25,
            w_vec=w_vec,
        )
        std_hits = self._hybrid_rank_one_lib(
            lib_name="Standards",
            query=query,
            chunks=self.std_chunks,
            bm25=self.std_bm25,
            faiss_index=self.std_index,
            top_n=top_n_per_lib,
            faiss_topk=faiss_topk,
            w_bm25=w_bm25,
            w_vec=w_vec,
        )

        return {"FAQ": faq_hits, "Standards": std_hits}


# Convenience functional API
_retriever_singleton: Optional[HybridRetriever] = None

def retrieve(
    query: str,
    index_dir: str = "/root/agent/rag/index",
    embed_model_dir: str = "/root/agent/rag/embed_models/bge-small-zh-v1.5",
    top_n_per_lib: int = 3,
    faiss_topk: int = 20,
    w_bm25: float = 0.5,
    w_vec: float = 0.5,
    reuse_singleton: bool = True,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Simple function wrapper.
    Use singleton by default to avoid reloading FAISS + BM25 every request.
    """
    global _retriever_singleton
    if (not reuse_singleton) or (_retriever_singleton is None):
        _retriever_singleton = HybridRetriever(
            index_dir=Path(index_dir),
            embed_model_dir=Path(embed_model_dir),
            device="cpu",
        )
    return _retriever_singleton.retrieve(
        query=query,
        top_n_per_lib=top_n_per_lib,
        faiss_topk=faiss_topk,
        w_bm25=w_bm25,
        w_vec=w_vec,
    )
