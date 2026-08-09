from fastapi import FastAPI, Header, HTTPException

from .connectors.mock import MockConnector

app = FastAPI(title="Campus Connector", version="0.1.0")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/sync/preview")
async def preview(x_campus_token: str | None = Header(default=None)):
    if not x_campus_token:
        raise HTTPException(401, "Missing short-lived campus token")
    return {"items": await MockConnector().fetch(x_campus_token)}

