"""
Lightweight OpenAI-compatible embedding + chat proxy.

Serves /v1/embeddings using sentence-transformers (all-MiniLM-L6-v2)
and proxies /v1/chat/completions to the Anthropic API.
"""

import os
import time
import json
import hashlib
from typing import Optional

import httpx
import numpy as np
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sentence_transformers import SentenceTransformer

app = FastAPI()

# Load a small embedding model — 384 dims, fast on CPU
MODEL_NAME = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
TARGET_DIM = int(os.environ.get("EMBEDDING_DIM", "1024"))
ANTHROPIC_URL = os.environ.get("ANTHROPIC_URL", "https://api.anthropic.com/v1")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_KEY", "")

_model: Optional[SentenceTransformer] = None


def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def pad_or_truncate(vec, target_dim):
    """Pad with zeros or truncate to target dimension."""
    if len(vec) >= target_dim:
        return vec[:target_dim]
    return list(vec) + [0.0] * (target_dim - len(vec))


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_NAME, "target_dim": TARGET_DIM}


@app.post("/v1/embeddings")
async def embeddings(request: Request):
    body = await request.json()
    inp = body.get("input", [])
    if isinstance(inp, str):
        inp = [inp]

    model = get_model()
    raw = model.encode(inp, normalize_embeddings=True)

    data = []
    for i, vec in enumerate(raw):
        padded = pad_or_truncate(vec.tolist(), TARGET_DIM)
        data.append({
            "object": "embedding",
            "index": i,
            "embedding": padded,
        })

    return {
        "object": "list",
        "data": data,
        "model": body.get("model", MODEL_NAME),
        "usage": {"prompt_tokens": sum(len(t.split()) for t in inp), "total_tokens": 0},
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """Proxy to Anthropic's OpenAI-compatible chat endpoint."""
    body = await request.json()
    headers = {
        "Authorization": f"Bearer {ANTHROPIC_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{ANTHROPIC_URL}/chat/completions",
            json=body,
            headers=headers,
        )
        return JSONResponse(content=resp.json(), status_code=resp.status_code)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8004"))
    uvicorn.run(app, host="0.0.0.0", port=port)
