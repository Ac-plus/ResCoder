#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Download embedding model from Hugging Face using pure Python.

Target:
  repo_id = "BAAI/bge-small-zh-v1.5"
  local_dir = "./rag/embed_models/bge-small-zh-v1.5"

Requirements:
  pip install huggingface_hub

Python 3.8 compatible.
"""

import os
import sys
import time
from pathlib import Path

def main():
    repo_id = "BAAI/bge-small-zh-v1.5"
    # This script is placed under ./rag/, so parent is project root
    rag_dir = Path("/root/agent/rag")
    local_dir = rag_dir / "embed_models" / "bge-small-zh-v1.5"
    local_dir.mkdir(parents=True, exist_ok=True)

    print("=== [download] ===")
    print("repo_id   =", repo_id)
    print("local_dir =", str(local_dir))

    try:
        from huggingface_hub import snapshot_download
    except Exception as e:
        print("[error] huggingface_hub not installed. Please run:")
        print("  python -m pip install -U huggingface_hub")
        raise

    # Optional: if you need to use a proxy, set env before running:
    #   HTTP_PROXY / HTTPS_PROXY
    # Optional: if you need auth (private repo), set:
    #   HUGGINGFACE_HUB_TOKEN

    t0 = time.time()

    # NOTE:
    # - local_dir_use_symlinks=False makes files physically copied into local_dir
    #   (more stable for Windows / cross-drive / portability).
    # - resume_download=True will continue incomplete downloads if interrupted.
    # - You can restrict patterns if you want, but here we download the full repo snapshot.
    print("[1/2] Starting snapshot_download ...")
    snapshot_path = snapshot_download(
        repo_id=repo_id,
        local_dir=str(local_dir),
        local_dir_use_symlinks=False,
        resume_download=True,
        # allow_patterns=None,  # download all
        # ignore_patterns=None,
    )

    dt = time.time() - t0
    print("[2/2] Done.")
    print("snapshot_path =", snapshot_path)
    print("time_seconds  =", "%.2f" % dt)

    # Basic sanity checks: some common files
    expected_any = [
        local_dir / "config.json",
        local_dir / "modules.json",
        local_dir / "sentence_bert_config.json",
    ]
    ok = any(p.exists() for p in expected_any)
    print("sanity_check_ok =", bool(ok))

    if not ok:
        print("[warn] Download finished but expected files not found in local_dir.")
        print("      Please inspect the directory:", str(local_dir))
        sys.exit(2)

if __name__ == "__main__":
    # Make stdout unbuffered-ish if user didn't pass -u
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    main()
