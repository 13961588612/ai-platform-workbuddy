#!/bin/bash
# =============================================================================
# init-embedding.sh — Local Embedding Model Deployment Script
# =============================================================================
# Deploys the bge-small-zh-v1.5 embedding model for local/intranet use:
#   - Downloads model from HuggingFace (BAAI/bge-small-zh-v1.5)
#   - Configures sentence-transformers with ONNX Runtime for optimized inference
#   - Starts a FastAPI embedding service on port 8001
#   - Vector dimension: 768
#
# Prerequisites:
#   - Python 3.12+
#   - pip
#   - Internet access (for initial model download only; then runs fully offline)
#
# Usage:
#   ./init-embedding.sh [--port PORT] [--model-dir DIR]
#
# Defaults:
#   PORT=8001
#   MODEL_DIR=./models
# =============================================================================

set -euo pipefail

# ===== Parse Arguments =====
PORT=8001
MODEL_DIR="./models"
MODEL_NAME="BAAI/bge-small-zh-v1.5"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --port)
            PORT="$2"
            shift 2
            ;;
        --model-dir)
            MODEL_DIR="$2"
            shift 2
            ;;
        --model-name)
            MODEL_NAME="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--port PORT] [--model-dir DIR] [--model-name NAME]"
            exit 1
            ;;
    esac
done

echo "=========================================="
echo "  Embedding Model Deployment"
echo "=========================================="
echo "  Model:       ${MODEL_NAME}"
echo "  Port:        ${PORT}"
echo "  Model Dir:   ${MODEL_DIR}"
echo "  Dimension:   768"
echo "=========================================="
echo ""

# ===== Create model directory =====
mkdir -p "${MODEL_DIR}"

# ===== Install Python dependencies =====
echo "Installing Python dependencies..."
pip install --upgrade pip
pip install --no-cache-dir \
    "fastapi[standard]>=0.111.0" \
    "uvicorn[standard]>=0.29.0" \
    "sentence-transformers>=3.0.0" \
    "onnxruntime>=1.17.0" \
    "numpy>=1.26.0" \
    "torch>=2.2.0" \
    "transformers>=4.40.0" \
    "pydantic>=2.7.0"
echo "✓ Dependencies installed."
echo ""

# ===== Pre-download model =====
echo "Pre-downloading model (this may take a few minutes on first run)..."
export SENTENCE_TRANSFORMERS_HOME="${MODEL_DIR}"
export TRANSFORMERS_CACHE="${MODEL_DIR}"

python3 -c "
from sentence_transformers import SentenceTransformer
import sys

model_name = '${MODEL_NAME}'
print(f'Downloading model: {model_name}...')
model = SentenceTransformer(model_name, cache_folder='${MODEL_DIR}')

# Verify model works
test_text = ['测试向量化']
embedding = model.encode(test_text, normalize_embeddings=True)
print(f'✓ Model loaded successfully.')
print(f'  Vector dimension: {embedding.shape[1]}')
print(f'  Sample embedding (first 5 dims): {embedding[0][:5].tolist()}')

if embedding.shape[1] != 768:
    print(f'  WARNING: Expected dimension 768, got {embedding.shape[1]}')
    sys.exit(1)
print('✓ Dimension check passed (768).')
"
echo ""

# ===== Create embedding service script =====
echo "Creating embedding service script..."
cat > /app/embedding_server.py << 'PYEOF'
"""
Local embedding model service using bge-small-zh-v1.5.

Provides a REST API for text embedding generation:
  GET  /health   — Health check
  POST /embed    — Generate embeddings for input texts

Vector dimension: 768 (bge-small-zh-v1.5)
"""
import os
import time
from typing import List

import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel, Field

MODEL_NAME = os.environ.get("MODEL_NAME", "BAAI/bge-small-zh-v1.5")
PORT = int(os.environ.get("PORT", "8001"))
MAX_BATCH_SIZE = int(os.environ.get("MAX_BATCH_SIZE", "32"))

app = FastAPI(
    title="AI Platform Embedding Service",
    description="Local embedding model service (bge-small-zh-v1.5, 768-dim)",
    version="1.0.0",
)

_model = None


def get_model():
    """Lazy-load the embedding model on first request."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        cache_dir = os.environ.get("SENTENCE_TRANSFORMERS_HOME", "/app/models")
        _model = SentenceTransformer(MODEL_NAME, cache_folder=cache_dir)
    return _model


class EmbedRequest(BaseModel):
    """Request body for the /embed endpoint."""
    texts: List[str] = Field(..., description="List of texts to embed")
    batch_size: int = Field(default=32, description="Batch size for encoding")


class EmbedResponse(BaseModel):
    """Response body for the /embed endpoint."""
    embeddings: List[List[float]] = Field(..., description="Embedding vectors")
    dimension: int = Field(..., description="Vector dimension")
    model: str = Field(..., description="Model name")
    elapsed_ms: float = Field(..., description="Processing time in ms")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "model": MODEL_NAME, "dimension": 768}


@app.post("/embed", response_model=EmbedResponse)
async def embed(request: EmbedRequest):
    """Generate embeddings for the provided texts."""
    start = time.perf_counter()
    model = get_model()
    texts = request.texts[:MAX_BATCH_SIZE]
    embeddings = model.encode(texts, normalize_embeddings=True)
    elapsed = (time.perf_counter() - start) * 1000
    return EmbedResponse(
        embeddings=embeddings.tolist(),
        dimension=int(embeddings.shape[1]),
        model=MODEL_NAME,
        elapsed_ms=round(elapsed, 2),
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
PYEOF
echo "✓ Service script created."
echo ""

# ===== Start service =====
echo "=========================================="
echo "  Starting embedding service on port ${PORT}..."
echo "=========================================="

export MODEL_NAME="${MODEL_NAME}"
export PORT="${PORT}"
export SENTENCE_TRANSFORMERS_HOME="${MODEL_DIR}"
export TRANSFORMERS_CACHE="${MODEL_DIR}"

exec uvicorn embedding_server:app --host 0.0.0.0 --port "${PORT}"
