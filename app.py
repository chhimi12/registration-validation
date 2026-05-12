import asyncio
import ipaddress
import logging
import os
import socket
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl

from validation import scan_url

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

SCAN_TIMEOUT_SECONDS = int(os.getenv("SCAN_TIMEOUT_SECONDS", "90"))
MAX_CONCURRENT_SCANS = int(os.getenv("MAX_CONCURRENT_SCANS", "2"))
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "*").split(",")
    if origin.strip()
]

app = FastAPI(
    title="Contact Form Compliance Scanner",
    description="Scans a URL and returns contact form, consent, and policy validation results.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

scan_semaphore = asyncio.BoundedSemaphore(MAX_CONCURRENT_SCANS)


class ScanRequest(BaseModel):
    url: HttpUrl


def validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="Only http and https URLs are supported.")

    if not parsed.hostname:
        raise HTTPException(status_code=400, detail="A valid hostname is required.")

    try:
        addresses = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror:
        raise HTTPException(status_code=400, detail="Could not resolve the URL hostname.")

    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise HTTPException(status_code=400, detail="Private or internal network URLs are not allowed.")


@app.get("/")
async def scanner_ui():
    return FileResponse("Scanner.html")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/scan")
async def scan_endpoint(request: ScanRequest):
    url = str(request.url)
    validate_public_url(url)

    if scan_semaphore.locked():
        raise HTTPException(status_code=429, detail="Scanner is busy. Please try again shortly.")

    await scan_semaphore.acquire()
    scan_task = asyncio.create_task(asyncio.to_thread(scan_url, url))

    def release_scan_slot(_):
        scan_semaphore.release()

    scan_task.add_done_callback(release_scan_slot)

    try:
        return await asyncio.wait_for(asyncio.shield(scan_task), timeout=SCAN_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Scan timed out.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Scan failed unexpectedly.") from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
