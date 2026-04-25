#!/bin/bash
# GPU Resource Allocation Diagnostic for Local Lucy v7
# Checks that both LLM (Ollama) and TTS (Kokoro) are using GPU efficiently

set -e

echo "============================================================"
echo "LOCAL LUCY v7 - GPU ALLOCATION DIAGNOSTIC"
echo "============================================================"
echo "Timestamp: $(date)"
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if nvidia-smi is available
if ! command -v nvidia-smi &> /dev/null; then
    echo -e "${RED}ERROR: nvidia-smi not found. Is NVIDIA driver installed?${NC}"
    exit 1
fi

# GPU Info
echo "=== GPU INFORMATION ==="
nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free,temperature.gpu,utilization.gpu \
    --format=csv,noheader,nounits 2>/dev/null | while IFS=',' read -r name total used free temp util; do
    echo "  GPU: $name"
    echo "  Temperature: ${temp}°C"
    echo "  Utilization: ${util}%"
    echo "  Memory Total: $((total / 1024)) GB"
    echo "  Memory Used:  $((used / 1024)) GB"
    echo "  Memory Free:  $((free / 1024)) GB"
done
echo ""

# Check GPU Processes
echo "=== GPU PROCESSES ==="
nvidia-smi --query-compute-apps=pid,process_name,used_memory \
    --format=csv,noheader 2>/dev/null | while IFS=',' read -r pid name mem; do
    # Trim whitespace
    pid=$(echo "$pid" | xargs)
    name=$(echo "$name" | xargs)
    mem=$(echo "$mem" | xargs)
    
    if echo "$name" | grep -q "ollama"; then
        echo -e "  ${GREEN}✓${NC} Ollama LLM       PID:$pid  Memory:$mem"
    elif echo "$name" | grep -q "kokoro"; then
        echo -e "  ${GREEN}✓${NC} Kokoro TTS       PID:$pid  Memory:$mem"
    elif echo "$name" | grep -q "python"; then
        echo -e "  ${YELLOW}◦${NC} Python (other)   PID:$pid  Memory:$mem"
    else
        echo -e "  ${YELLOW}◦${NC} $name  PID:$pid  Memory:$mem"
    fi
done
echo ""

# Check Kokoro Worker
echo "=== KOKORO TTS WORKER ==="
KOKORO_PID=$(pgrep -f "kokoro_session_worker" || echo "")
if [ -n "$KOKORO_PID" ]; then
    echo -e "  ${GREEN}✓${NC} Worker running   PID:$KOKORO_PID"
    
    # Check if it's using GPU
    if nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -q "^\s*${KOKORO_PID}\s*$"; then
        echo -e "  ${GREEN}✓${NC} Using GPU (CUDA)"
    else
        echo -e "  ${RED}✗${NC} NOT using GPU (check PyTorch CUDA)"
    fi
    
    # Check socket
    # V8 ISOLATION: Use v8 socket path
    SOCKET="${LUCY_VOICE_KOKORO_SOCKET:-/home/mike/lucy-v8/snapshots/opt-experimental-v8-dev/tmp/run/kokoro_tts_worker.sock}"
    if [ -S "$SOCKET" ]; then
        echo -e "  ${GREEN}✓${NC} Socket available"
    else
        echo -e "  ${RED}✗${NC} Socket missing"
    fi
else
    echo -e "  ${RED}✗${NC} Worker not running"
fi
echo ""

# Check Ollama
echo "=== OLLAMA LLM ==="
OLLAMA_PID=$(pgrep -f "ollama serve" || echo "")
if [ -n "$OLLAMA_PID" ]; then
    echo -e "  ${GREEN}✓${NC} Service running  PID:$OLLAMA_PID"
    
    # Check if model is loaded on GPU
    if nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -q "^\s*${OLLAMA_PID}\s*$"; then
        echo -e "  ${GREEN}✓${NC} Model on GPU"
    else
        echo -e "  ${YELLOW}◦${NC} Model not currently loaded (will load on first request)"
    fi
else
    echo -e "  ${RED}✗${NC} Service not running"
fi
echo ""

# Check PyTorch CUDA (if venv available)
echo "=== PYTORCH CUDA ==="
VENV_PYTHON="/home/mike/lucy/ui-v7/.venv/bin/python"
if [ -x "$VENV_PYTHON" ]; then
    CUDA_CHECK=$($VENV_PYTHON -c "import torch; print(torch.cuda.is_available())" 2>/dev/null || echo "False")
    if [ "$CUDA_CHECK" = "True" ]; then
        echo -e "  ${GREEN}✓${NC} PyTorch CUDA available"
        $VENV_PYTHON -c "import torch; print(f'  Device: {torch.cuda.get_device_name(0)}')" 2>/dev/null || true
    else
        echo -e "  ${RED}✗${NC} PyTorch CUDA NOT available"
    fi
else
    echo -e "  ${YELLOW}◦${NC} Virtual environment not found"
fi
echo ""

# Summary
echo "=== SUMMARY ==="
TOTAL_GPU_MEM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 | xargs)
USED_GPU_MEM=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1 | xargs)

if [ -n "$TOTAL_GPU_MEM" ] && [ -n "$USED_GPU_MEM" ]; then
    USAGE_PERCENT=$((USED_GPU_MEM * 100 / TOTAL_GPU_MEM))
    echo "  GPU Memory Usage: ${USAGE_PERCENT}% ($((USED_GPU_MEM / 1024))/$((TOTAL_GPU_MEM / 1024)) GB)"
    
    if [ "$USAGE_PERCENT" -lt 80 ]; then
        echo -e "  ${GREEN}✓${NC} Healthy utilization"
    elif [ "$USAGE_PERCENT" -lt 95 ]; then
        echo -e "  ${YELLOW}◦${NC} High utilization - monitor closely"
    else
        echo -e "  ${RED}✗${NC} Critical utilization - may OOM"
    fi
fi

echo ""
echo "============================================================"
echo "Diagnostic complete."
echo "============================================================"
