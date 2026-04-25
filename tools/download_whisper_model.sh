#!/bin/bash
# Download Whisper models for Local Lucy voice system
# Usage: ./download_whisper_model.sh [tiny|base|small|medium|large]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODELS_DIR="${SCRIPT_DIR}/../runtime/voice/models"

# Default to base if no argument
MODEL_SIZE="${1:-base}"

# Validate model size
case "$MODEL_SIZE" in
    tiny|base|small|medium|large)
        ;;
    *)
        echo "Usage: $0 [tiny|base|small|medium|large]"
        echo ""
        echo "Model sizes:"
        echo "  tiny   ~75 MB   - Fastest, lower accuracy"
        echo "  base   ~150 MB  - Good speed/accuracy balance"
        echo "  small  ~488 MB  - Current default, good accuracy"
        echo "  medium ~1.5 GB  - Higher accuracy, slower"
        echo "  large  ~3 GB    - Best accuracy, slowest"
        exit 1
        ;;
esac

# Create models directory if needed
mkdir -p "$MODELS_DIR"

cd "$MODELS_DIR"

# Check if model already exists
MODEL_FILE="ggml-${MODEL_SIZE}.en.bin"
if [ -f "$MODEL_FILE" ]; then
    echo "Model already exists: $MODEL_FILE"
    ls -lh "$MODEL_FILE"
    exit 0
fi

echo "Downloading Whisper model: ${MODEL_SIZE}.en"
echo "Target: ${MODELS_DIR}/${MODEL_FILE}"
echo ""

# Download using the whisper.cpp script
cd "${SCRIPT_DIR}/../runtime/voice/whisper.cpp/models"

if [ -f "./download-ggml-model.sh" ]; then
    bash ./download-ggml-model.sh "${MODEL_SIZE}.en"
else
    echo "Error: download-ggml-model.sh not found"
    exit 1
fi

# Copy to runtime models directory if downloaded elsewhere
if [ -f "ggml-${MODEL_SIZE}.en.bin" ]; then
    cp "ggml-${MODEL_SIZE}.en.bin" "$MODELS_DIR/"
    echo ""
    echo "✓ Model installed: ${MODELS_DIR}/${MODEL_FILE}"
    ls -lh "$MODELS_DIR/${MODEL_FILE}"
fi

echo ""
echo "To use this model, set environment variable:"
echo "  export LUCY_VOICE_MODEL=${MODEL_SIZE}.en"
