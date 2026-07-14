#!/bin/bash
# Render build script
set -e

echo "=== Installing Python dependencies ==="
pip install --upgrade pip
pip install -r requirements.txt

echo "=== Installing Playwright browser ==="
python -m playwright install chromium || echo "⚠️ Playwright browser install failed (extraction only)"

# Try to install system deps (may fail on Render without sudo)
echo "=== Installing Playwright system dependencies ==="
python -m playwright install-deps chromium 2>/dev/null || {
    echo "⚠️ System deps install failed (needs sudo - extraction must run locally)"
    echo "   The bot itself will work fine. Run extract_codes.py on your local machine."
}

echo "=== Initializing database ==="
python -c "
import asyncio
from database import init_db
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
loop.run_until_complete(init_db())
print('✅ Database initialized!')
"

echo "=== Build complete! ==="
