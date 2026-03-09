#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Build FAISS indexes for multi-route RAG.

Input:
  ./rag/docs/FAQ
  ./rag/docs/Standards

Output:
  ./rag/index/faq.index
  ./rag/index/faq_chunks.jsonl
  ./rag/index/standards.index
  ./rag/index/standards_chunks.jsonl
  ./rag/index/manifest.json

Notes:
- Embedding model MUST be local (no online download in code).
- Python 3.8 compatible.
- Progress bars included (tqdm).
"""

import os
import re
import json
import time
import hashlib
from pathlib import Path

from typing import List, Dict, Any, Tuple

import numpy as np
from tqdm import tqdm

import faiss
from sentence_transformers import SentenceTransformer


# =========================
# Paths
# =========================
# ROOT = Path(__file__).resolve().parent.parent  # project root (one level above ./rag)
ROOT = Path("/root/agent")
RAG_DIR = ROOT / "rag"
DOCS_DIR = RAG_DIR / "docs"
INDEX_DIR = RAG_DIR / "index"
EMBED_DIR = RAG_DIR / "embed_models"

FAQ_DIR = DOCS_DIR / "FAQ"
STD_DIR = DOCS_DIR / "Standards"

# Local embedding model path (downloaded by CLI)
EMBED_MODEL_LOCAL = EMBED_DIR / "bge-small-zh-v1.5"

# =========================
# Chunking config
# =========================
CHUNK_CHARS = 900          # chunk size in characters (roughly 450-700 tokens for mixed zh/en, depends)
CHUNK_OVERLAP = 150        # overlap chars
MIN_CHUNK_CHARS = 80       # drop too-short chunks


# =========================
# File reading
# =========================
TEXT_EXTS = {".txt", ".md", ".markdown", ".rst"}

def _clean_text(s: str) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    # collapse repeated blank lines
    s = re.sub(r"\n{3,}", "\n\n", s)
    # strip trailing spaces
    s = "\n".join([line.rstrip() for line in s.split("\n")])
    return s.strip()

def read_text_file(p: Path) -> str:
    # Try utf-8, then gbk (common in CN), then latin-1 as last resort
    for enc in ("utf-8", "utf-8-sig", "gbk", "gb18030", "latin-1"):
        try:
            return _clean_text(p.read_text(encoding=enc, errors="strict"))
        except Exception:
            continue
    # fallback with replace
    return _clean_text(p.read_text(encoding="utf-8", errors="replace"))

def read_pdf_file(p: Path) -> str:
    """
    Optional PDF support. If pypdf is not available, raise.
    """
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "PDF file detected but 'pypdf' is not installed. "
            "Install it or convert PDFs to text/markdown. Error: %s" % str(e)
        )
    reader = PdfReader(str(p))
    parts = []
    for page in reader.pages:
        txt = page.extract_text() or ""
        if txt.strip():
            parts.append(txt)
    return _clean_text("\n\n".join(parts))

def load_documents(folder: Path) -> List[Dict[str, Any]]:
    """
    Recursively load documents under folder.
    Returns list of dict: {path, relpath, text}
    """
    docs = []
    if not folder.exists():
        return docs

    files = [p for p in folder.rglob("*") if p.is_file()]
    for p in files:
        ext = p.suffix.lower()
        try:
            if ext in TEXT_EXTS:
                text = read_text_file(p)
            elif ext == ".pdf":
                text = read_pdf_file(p)
            else:
                # skip unknown
                continue
        except Exception as e:
            print("[warn] Failed to read file:", str(p), "error=", str(e))
            continue

        if text.strip():
            rel = str(p.relative_to(folder))
            docs.append({"path": str(p), "relpath": rel, "text": text})
    return docs


# =========================
# Chunking
# =========================
def chunk_text(text: str, chunk_chars: int, overlap: int) -> List[str]:
    """
    Simple char-based sliding window chunking.
    Deterministic and stable, avoids LLM-based semantic split errors.
    """
    text = text.strip()
    if not text:
        return []

    chunks = []
    n = len(text)
    start = 0
    while start < n:
        end = min(n, start + chunk_chars)
        chunk = text[start:end].strip()
        if len(chunk) >= MIN_CHUNK_CHARS:
            chunks.append(chunk)
        if end >= n:
            break
        start = max(0, end - overlap)
    return chunks


# =========================
# Embedding + FAISS
# =========================
def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", errors="ignore")).hexdigest()

def ensure_dirs():
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

def load_embedder(local_model_dir: Path) -> SentenceTransformer:
    if not local_model_dir.exists():
        raise FileNotFoundError(
            "Local embedding model not found: %s\n"
            "Please download it into ./rag/embed_models first." % str(local_model_dir)
        )

    # Force offline behavior
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_OFFLINE"] = "1"

    # SentenceTransformer supports local path
    embedder = SentenceTransformer(
        str(local_model_dir),
        device="cpu"
    )
    return embedder

def embed_texts(embedder: SentenceTransformer, texts: List[str], batch_size: int = 64) -> np.ndarray:
    vecs = embedder.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True
    ).astype("float32")
    return vecs

def build_one_index(
    library_name: str,
    library_dir: Path,
    embedder: SentenceTransformer,
    out_index_path: Path,
    out_chunks_path: Path
) -> Dict[str, Any]:
    """
    Build FAISS index + chunks jsonl for one library.
    """
    t0 = time.time()
    docs = load_documents(library_dir)
    print("=== [%s] docs=%d ===" % (library_name, len(docs)))

    chunks_meta = []
    all_chunks = []

    # Chunk documents
    for d in tqdm(docs, desc="Chunking %s" % library_name):
        doc_text = d["text"]
        chs = chunk_text(doc_text, CHUNK_CHARS, CHUNK_OVERLAP)
        for j, ch in enumerate(chs):
            cid = sha1("%s||%s||%d||%s" % (library_name, d["relpath"], j, ch[:80]))
            meta = {
                "id": cid,
                "library": library_name,
                "source_path": d["path"],
                "source_relpath": d["relpath"],
                "chunk_index": j,
                "text": ch
            }
            chunks_meta.append(meta)
            all_chunks.append(ch)

    if not all_chunks:
        raise RuntimeError("No chunks built for library: %s (check documents)." % library_name)

    # Embed
    print("Embedding %s chunks=%d ..." % (library_name, len(all_chunks)))
    vecs = []
    bs = 64
    for i in tqdm(range(0, len(all_chunks), bs), desc="Embedding %s" % library_name):
        batch = all_chunks[i:i+bs]
        v = embed_texts(embedder, batch, batch_size=bs)
        vecs.append(v)
    vecs = np.vstack(vecs).astype("float32")

    dim = int(vecs.shape[1])
    # FAISS IndexFlatIP for cosine-sim (we normalized embeddings)
    index = faiss.IndexFlatIP(dim)
    index.add(vecs)

    # Save index
    faiss.write_index(index, str(out_index_path))

    # Save chunks meta (jsonl)
    with out_chunks_path.open("w", encoding="utf-8") as f:
        for m in chunks_meta:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")

    dt = time.time() - t0
    info = {
        "library": library_name,
        "docs_dir": str(library_dir),
        "docs": len(docs),
        "chunks": len(all_chunks),
        "dim": dim,
        "index_path": str(out_index_path),
        "chunks_path": str(out_chunks_path),
        "seconds": float(dt),
    }
    print("=== [%s] done: chunks=%d dim=%d time=%.2fs ===" % (library_name, len(all_chunks), dim, dt))
    return info


def main():
    print("=== [paths] ===")
    print("  ROOT      =", str(ROOT))
    print("  DOCS_DIR  =", str(DOCS_DIR))
    print("  FAQ_DIR   =", str(FAQ_DIR))
    print("  STD_DIR   =", str(STD_DIR))
    print("  INDEX_DIR =", str(INDEX_DIR))
    print("  EMBED     =", str(EMBED_MODEL_LOCAL))

    ensure_dirs()

    print("\n=== [1/2] Load embedder (offline, CPU) ===")
    embedder = load_embedder(EMBED_MODEL_LOCAL)

    manifest = {
        "embed_model_local": str(EMBED_MODEL_LOCAL),
        "chunk_chars": int(CHUNK_CHARS),
        "chunk_overlap": int(CHUNK_OVERLAP),
        "min_chunk_chars": int(MIN_CHUNK_CHARS),
        "libraries": {}
    }

    print("\n=== [2/2] Build FAISS indexes ===")

    # FAQ
    faq_index = INDEX_DIR / "faq.index"
    faq_chunks = INDEX_DIR / "faq_chunks.jsonl"
    faq_info = build_one_index(
        library_name="FAQ",
        library_dir=FAQ_DIR,
        embedder=embedder,
        out_index_path=faq_index,
        out_chunks_path=faq_chunks
    )
    manifest["libraries"]["FAQ"] = faq_info

    # Standards
    std_index = INDEX_DIR / "standards.index"
    std_chunks = INDEX_DIR / "standards_chunks.jsonl"
    std_info = build_one_index(
        library_name="Standards",
        library_dir=STD_DIR,
        embedder=embedder,
        out_index_path=std_index,
        out_chunks_path=std_chunks
    )
    manifest["libraries"]["Standards"] = std_info

    # Save manifest
    manifest_path = INDEX_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== all done ===")
    print("Manifest:", str(manifest_path))
    print("FAQ index:", str(faq_index))
    print("Standards index:", str(std_index))


if __name__ == "__main__":
    main()
