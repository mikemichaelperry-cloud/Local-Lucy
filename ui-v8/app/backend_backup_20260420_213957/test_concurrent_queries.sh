#!/bin/bash
#
# Concurrent Query Execution Test
# Tests the hybrid_wrapper.sh under concurrent load
#

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROUTER_ROOT="$(cd "${SCRIPT_DIR}/../../" && pwd)"

# Test configuration
NUM_QUERIES=10
TIMEOUT=60
OUTPUT_DIR="/tmp/lucy_concurrent_test_$(date +%s)"

# Create output directory
mkdir -p "$OUTPUT_DIR"

echo "========================================"
echo "CONCURRENT QUERY EXECUTION TEST"
echo "========================================"
echo "Output directory: $OUTPUT_DIR"
echo "Number of queries: $NUM_QUERIES"
echo "Timeout per query: ${TIMEOUT}s"
echo ""

# Test queries (various types to exercise different code paths)
declare -a QUERIES=(
    "What is the weather today?"
    "Tell me a joke"
    "Calculate 15 times 23"
    "What is Python programming?"
    "How do I make pasta?"
    "What time is it?"
    "Explain quantum mechanics"
    "Who wrote Romeo and Juliet?"
    "What is the capital of France?"
    "How does photosynthesis work?"
)

# Results tracking
SUCCESS_COUNT=0
FAIL_COUNT=0
declare -a RESPONSE_TIMES
declare -a ERROR_LOGS

# Function to run a single query
run_query() {
    local idx=$1
    local query="${QUERIES[$idx]}"
    local output_file="$OUTPUT_DIR/query_${idx}.log"
    local start_time end_time duration
    
    start_time=$(date +%s.%N)
    
    # Run query with timeout
    if timeout "$TIMEOUT" "${ROUTER_ROOT}/tools/router_py/hybrid_wrapper.sh" "$query" > "$output_file" 2>&1; then
        end_time=$(date +%s.%N)
        duration=$(echo "$end_time - $start_time" | bc 2>/dev/null || echo "0")
        
        # Check for errors in output
        if grep -q "ERR:" "$output_file" 2>/dev/null || grep -q "ERROR" "$output_file" 2>/dev/null; then
            echo "FAIL:$idx:$duration"
            return 1
        else
            echo "SUCCESS:$idx:$duration"
            return 0
        fi
    else
        end_time=$(date +%s.%N)
        duration=$(echo "$end_time - $start_time" | bc 2>/dev/null || echo "0")
        echo "FAIL:$idx:$duration"
        return 1
    fi
}

export -f run_query
export ROUTER_ROOT OUTPUT_DIR TIMEOUT

echo "--- Launching concurrent queries ---"
START_TIME=$(date +%s)

# Launch all queries concurrently
for i in $(seq 0 $((NUM_QUERIES - 1))); do
    run_query "$i" &
done

# Wait for all to complete
wait
END_TIME=$(date +%s)
TOTAL_TIME=$((END_TIME - START_TIME))

echo ""
echo "--- Analyzing results ---"

# Analyze results
for i in $(seq 0 $((NUM_QUERIES - 1))); do
    log_file="$OUTPUT_DIR/query_${i}.log"
    
    if [[ -f "$log_file" ]]; then
        # Check for success indicators
        if grep -q "ERR:" "$log_file" 2>/dev/null || \
           grep -qi "error" "$log_file" 2>/dev/null || \
           grep -q "shared-state overlap" "$log_file" 2>/dev/null; then
            echo "Query $i: FAILED"
            FAIL_COUNT=$((FAIL_COUNT + 1))
            ERROR_LOGS+=("query_$i: $(head -3 "$log_file")")
        else
            # Check if output has reasonable content
            output_size=$(stat -f%z "$log_file" 2>/dev/null || stat -c%s "$log_file" 2>/dev/null || echo "0")
            if [[ "$output_size" -gt 10 ]]; then
                echo "Query $i: SUCCESS"
                SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
            else
                echo "Query $i: FAILED (empty output)"
                FAIL_COUNT=$((FAIL_COUNT + 1))
            fi
        fi
    else
        echo "Query $i: FAILED (no output file)"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
done

echo ""
echo "========================================"
echo "RESULTS SUMMARY"
echo "========================================"
echo "Successful queries: $SUCCESS_COUNT"
echo "Failed queries: $FAIL_COUNT"
echo "Success rate: $(( SUCCESS_COUNT * 100 / NUM_QUERIES ))%"
echo "Total execution time: ${TOTAL_TIME}s"
echo ""

# Check for specific error patterns
echo "--- Error Pattern Analysis ---"
OVERLAP_ERRORS=$(grep -l "shared-state overlap" "$OUTPUT_DIR"/*.log 2>/dev/null | wc -l)
TIMEOUT_ERRORS=$(grep -l "timeout" "$OUTPUT_DIR"/*.log 2>/dev/null | wc -l)
LOCK_ERRORS=$(grep -l "lock" "$OUTPUT_DIR"/*.log 2>/dev/null | wc -l)

echo "Shared-state overlap errors: $OVERLAP_ERRORS"
echo "Timeout errors: $TIMEOUT_ERRORS"
echo "Lock-related errors: $LOCK_ERRORS"

if [[ ${#ERROR_LOGS[@]} -gt 0 ]]; then
    echo ""
    echo "--- Sample Errors ---"
    for err in "${ERROR_LOGS[@]:0:3}"; do
        echo "$err"
    done
fi

# Resource usage check
echo ""
echo "--- Resource Usage ---"
PYTHON_PROCS=$(ps aux | grep -c "python.*router_py" || echo "0")
echo "Python router processes: $((PYTHON_PROCS - 1))"  # Subtract grep itself

# Cleanup option
if [[ "${KEEP_LOGS:-0}" != "1" ]]; then
    rm -rf "$OUTPUT_DIR"
    echo ""
    echo "Cleaned up log files"
fi

# Exit with appropriate code
if [[ $FAIL_COUNT -eq 0 ]]; then
    echo ""
    echo "✅ All queries completed successfully"
    exit 0
else
    echo ""
    echo "❌ Some queries failed"
    exit 1
fi
