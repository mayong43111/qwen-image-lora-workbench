from __future__ import annotations

import os

import uvicorn

from server.app.main import app


if __name__ == "__main__":
    uvicorn.run("server.app.main:app", host="127.0.0.1", port=int(os.environ.get("PORT", "8787")), reload=False)
