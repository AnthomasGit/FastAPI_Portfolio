#!/bin/bash

# ==========================================
# DEVELOPMENT SERVER LAUNCHER
# ==========================================

# 1. Update this path to point to where you cloned ComfyUI on your machine
COMFY_DIR="/home/anthomas/ComfyUI"
API_DIR="."
UI_DIR="../portfolio-ui"

# 2. Cleanup Trap (The secret sauce)
# This function runs automatically when you press Ctrl+C
cleanup() {
    echo ""
    echo "🛑 Caught Ctrl+C! Shutting down development servers..."

    # Kill the background ComfyUI process
    if [ -n "$COMFY_PID" ]; then
        echo "Shutting down ComfyUI (PID: $COMFY_PID)..."
        kill $COMFY_PID
    fi

    # Kill the background FastAPI process
    if [ -n "$FASTAPI_PID" ]; then
        echo "Shutting down FastAPI (PID: $FASTAPI_PID)..."
        kill $FASTAPI_PID
    fi

    echo "✅ All servers shut down cleanly."
    exit 0
}

# Bind the cleanup function to the SIGINT (Ctrl+C) signal
trap cleanup SIGINT

# ==========================================

echo "========================================"
echo "🚀 Booting AI Portfolio Dev Environment"
echo "========================================"

# 3. Boot ComfyUI (Background)
echo "Starting ComfyUI natively on port 8188..."
cd "$COMFY_DIR" || { echo "❌ Could not find ComfyUI directory at $COMFY_DIR"; exit 1; }

# Activate ComfyUI virtual environment
source zimagevenv/bin/activate || { echo "❌ Could not activate ComfyUI venv"; exit 1; }

# Run ComfyUI in the background using the '&' operator
python main.py --listen 127.0.0.1 --port 8188 &
COMFY_PID=$! # Save the Process ID so the trap function can kill it later

# Deactivate so it doesn't bleed into the FastAPI environment
deactivate

# 4. Boot FastAPI (Background)
echo "Starting FastAPI Orchestrator natively on port 8000..."
cd - > /dev/null # Go back to the original directory invisibly
cd "$API_DIR" || { echo "❌ Could not find API directory"; exit 1; }

# Activate FastAPI virtual environment
source ../.venv/bin/activate || { echo "❌ Could not activate FastAPI venv"; exit 1; }

# Export the environment variable your main.py is looking for
export COMFY_API_URL="http://127.0.0.1:8188"

# Run Uvicorn in the foreground (this blocks the script and streams your API logs)
uvicorn main:app --host 127.0.0.1 --port 8000 --reload &
FastAPI_PID=$!

# 5. Boot Frontend UI (Foreground)
echo "Starting Frontend UI..."
cd - > /dev/null
cd "$UI_DIR" || { echo "❌ Could not find UI directory at $UI_DIR"; exit 1; }

echo ""
echo "✅ Environment Ready! FastAPI logs will stream below."
echo "Press Ctrl+C at any time to shut down both servers."
echo "========================================"

# Run npm dev in the foreground
npm run dev