#!/usr/bin/env bash
# Video test runner for pokere_1980.mp4

set -euo pipefail

echo "========================================"
echo "VIDEO TEST: pokere_1980.mp4"
echo "========================================"
echo ""

# Verify video exists
VIDEO_PATH="chapo92/pokere/pokere_1980.mp4"
if [ ! -f "$VIDEO_PATH" ]; then
    echo "ERROR: Video not found!"
    echo "Expected: $VIDEO_PATH"
    exit 1
fi

echo "Starting analysis..."
echo ""

# Run Python analyzer
python scripts/test/test_video_analysis.py

echo ""
echo "========================================"
echo "TEST COMPLETE!"
echo "========================================"
echo ""
echo "Results saved to: test_results_pokere_1980.json"
echo ""
