"""Reviewer-only download route for the committed capstone submission archive."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse, HTMLResponse

router = APIRouter(prefix="/demo", include_in_schema=False)


def _require_demo_mode() -> None:
    if os.getenv("DEMO_MODE", "").strip().lower() not in {"1", "true", "yes", "on"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")


def _archive_path() -> Path:
    return Path(__file__).resolve().parents[2] / "FlyRank_Backend_Capstone_Submission.zip"


@router.get("/submission", response_class=HTMLResponse)
def submission_download_page() -> HTMLResponse:
    _require_demo_mode()
    return HTMLResponse(
        '<!doctype html><html><body><h1>FlyRank Backend Capstone Submission</h1>'
        '<p><a href="/demo/submission.zip">Download final submission ZIP</a></p>'
        '</body></html>'
    )


@router.get("/submission.zip")
def submission_download() -> FileResponse:
    _require_demo_mode()
    archive = _archive_path()
    if not archive.is_file():
        raise HTTPException(status_code=404, detail="Submission archive not found.")
    return FileResponse(
        path=archive,
        media_type="application/zip",
        filename="FlyRank_Backend_Capstone_Submission.zip",
    )
