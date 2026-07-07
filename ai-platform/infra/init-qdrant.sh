#!/bin/bash
# =============================================================================
# init-qdrant.sh — Qdrant Collection Initialization Script
# =============================================================================
# Creates three Qdrant collections required by the AI Platform:
#   1. skills_index          — Skill semantic search (768-dim, bge-small-zh-v1.5)
#   2. agent_router_index    — AgentRouter semantic routing (768-dim)
#   3. agent_memory_index    — Agent dynamic memory retrieval (768-dim)
#
# All collections use cosine distance (normalized embeddings from bge-small-zh)
# and HNSW index for fast approximate nearest neighbor search.
#
# Usage (requires bash, curl, and python3):
#   bash init-qdrant.sh [QDRANT_URL]
#
# Default QDRANT_URL: http://localhost:6333
#
# With Docker Compose (Qdrant exposed on localhost:6333):
#   bash init-qdrant.sh http://localhost:6333
#
# Do NOT run with `sh` — pipefail and arrays require bash.
# The Qdrant image has bash but not curl/python3; run from the host instead.
# =============================================================================

set -euo pipefail

QDRANT_URL="${1:-http://localhost:6333}"
VECTOR_SIZE=768
DISTANCE="Cosine"

# Collections to create
COLLECTIONS=("skills_index" "agent_router_index" "agent_memory_index")

echo "=========================================="
echo "  Qdrant Collection Initialization"
echo "=========================================="
echo "  Qdrant URL:    ${QDRANT_URL}"
echo "  Vector Size:   ${VECTOR_SIZE}"
echo "  Distance:      ${DISTANCE}"
echo "  Collections:   ${COLLECTIONS[*]}"
echo "=========================================="
echo ""

# Wait for Qdrant to be ready
echo "Waiting for Qdrant to be ready..."
MAX_RETRIES=30
RETRY_COUNT=0
while [ ${RETRY_COUNT} -lt ${MAX_RETRIES} ]; do
    if curl -sf "${QDRANT_URL}/healthz" > /dev/null 2>&1; then
        echo "✓ Qdrant is ready."
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo "  Attempt ${RETRY_COUNT}/${MAX_RETRIES} — Qdrant not ready, retrying in 2s..."
    sleep 2
done

if [ ${RETRY_COUNT} -ge ${MAX_RETRIES} ]; then
    echo "✗ ERROR: Qdrant did not become ready within ${MAX_RETRIES} retries."
    exit 1
fi

echo ""

# Create each collection
for COLLECTION in "${COLLECTIONS[@]}"; do
    echo "Creating collection: ${COLLECTION}"

    # Check if collection already exists
    EXISTS=$(curl -s -o /dev/null -w "%{http_code}" "${QDRANT_URL}/collections/${COLLECTION}")

    if [ "${EXISTS}" = "200" ]; then
        echo "  ⚠ Collection '${COLLECTION}' already exists — skipping creation."
        echo ""
        continue
    fi

    # Create collection with HNSW index
    CREATE_RESPONSE=$(curl -s -X PUT "${QDRANT_URL}/collections/${COLLECTION}" \
        -H "Content-Type: application/json" \
        -d "{
            \"vectors\": {
                \"size\": ${VECTOR_SIZE},
                \"distance\": \"${DISTANCE}\"
            },
            \"hnsw_config\": {
                \"m\": 16,
                \"ef_construct\": 100,
                \"full_scan_threshold\": 10000,
                \"max_indexing_threads\": 0,
                \"on_disk\": false,
                \"payload_m\": 16
            },
            \"optimizers_config\": {
                \"deleted_threshold\": 0.2,
                \"vacuum_min_vector_number\": 1000,
                \"default_segment_number\": 0,
                \"max_segment_size\": null,
                \"memmap_threshold\": null,
                \"indexing_threshold\": 20000,
                \"flush_interval_sec\": 5,
                \"max_optimization_threads\": 0
            },
            \"wal_config\": {
                \"wal_capacity_mb\": 32,
                \"wal_segments_amount\": 2
            },
            \"quantization_config\": null
        }")

    # Check creation result (Qdrant returns {"result": true, "status": "ok"})
    SUCCESS=$(echo "${CREATE_RESPONSE}" | python3 -c "
import sys, json
d = json.load(sys.stdin)
r = d.get('result')
ok = d.get('status') == 'ok' and (r is True or (isinstance(r, dict) and r.get('status') in ('ok', 'acknowledged')))
print('True' if ok else 'False')
" 2>/dev/null || echo "False")

    if [ "${SUCCESS}" = "True" ] || [ "${SUCCESS}" = "true" ]; then
        echo "  ✓ Collection '${COLLECTION}' created successfully."
    else
        echo "  ✗ Failed to create collection '${COLLECTION}'."
        echo "  Response: ${CREATE_RESPONSE}"
        exit 1
    fi

    echo ""
done

# =============================================================================
# Create payload indices for agent_memory_index
# =============================================================================
# The agent_memory_index collection requires keyword payload indices on the
# filterable fields used by the two-phase retrieval:
#   - agent_name  — filter by Agent
#   - user_id     — filter by User
#   - session_id  — filter by Session (session-level memories)
#   - scope       — filter by "user" or "session" scope
# =============================================================================
MEMORY_COLLECTION="agent_memory_index"
PAYLOAD_FIELDS=("agent_name" "user_id" "session_id" "scope")

echo "=========================================="
echo "  Creating payload indices for '${MEMORY_COLLECTION}'"
echo "=========================================="

for FIELD in "${PAYLOAD_FIELDS[@]}"; do
    echo "  Creating payload index: ${FIELD}"

    INDEX_RESPONSE=$(curl -s -X PUT "${QDRANT_URL}/collections/${MEMORY_COLLECTION}/index" \
        -H "Content-Type: application/json" \
        -d "{\"field_name\": \"${FIELD}\", \"field_schema\": \"keyword\"}")

    INDEX_SUCCESS=$(echo "${INDEX_RESPONSE}" | python3 -c "
import sys, json
d = json.load(sys.stdin)
r = d.get('result')
ok = d.get('status') == 'ok' and (r is True or (isinstance(r, dict) and r.get('status') in ('ok', 'acknowledged')))
print('True' if ok else 'False')
" 2>/dev/null || echo "False")

    if [ "${INDEX_SUCCESS}" = "True" ] || [ "${INDEX_SUCCESS}" = "true" ]; then
        echo "    ✓ Payload index '${FIELD}' created."
    else
        echo "    ⚠ Payload index '${FIELD}' may already exist or failed."
        echo "    Response: ${INDEX_RESPONSE}"
    fi
done

echo ""

# List all collections to verify
echo "=========================================="
echo "  Verifying collections..."
echo "=========================================="
curl -s "${QDRANT_URL}/collections" | python3 -m json.tool 2>/dev/null || \
    curl -s "${QDRANT_URL}/collections"
echo ""
echo "✓ Qdrant initialization complete."
