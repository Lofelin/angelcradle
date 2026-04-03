"""
Angel Cradle — Backend entry point.

Usage:
    cd backend && python main.py
"""

import os
from pathlib import Path

# Load .env
env_path = Path(__file__).parent / ".env"
if env_path.is_file():
    for line in env_path.read_text().strip().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

from fastapi.middleware.cors import CORSMiddleware
from api import create_app

app = create_app()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
