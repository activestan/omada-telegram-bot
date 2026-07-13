#!/bin/bash
# Render build script
echo "Installing Python dependencies..."
pip install -r requirements.txt

echo "Installing Playwright browser..."
python -m playwright install chromium
python -m playwright install-deps chromium

echo "Initializing database..."
python -c "
import asyncio
from database import init_db
asyncio.run(init_db())
print('Database initialized!')
"

echo "Build complete!"
