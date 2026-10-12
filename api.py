"""FastAPI backend for QueueLess Campus.

Run:  uvicorn api:app --reload      then open http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import io
from datetime import datetime
from typing import Optional

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

from app import analytics, config, db, recommender, seed

db.init_db()
app = FastAPI(title="QueueLess Campus API", version="1.0.0",
              description="Token capture, waiting-time analytics and scheduling suggestions.")


class TokenIn(BaseModel):
    counter: str
    service_type: str = "general"
    source: str = "token"
    issued_at: Optional[datetime] = None


class ManualObservation(BaseModel):
    """A voluntary observation: when someone arrived and how long they waited."""
    counter: str
    arrived_at: datetime
    waited_min: float
    service_type: str = "general"


def _prepared() -> pd.DataFrame:
    return analytics.prepare(db.load_tokens())


def _records(df: pd.DataFrame) -> list[dict]:
    return df.astype(object).where(df.notna(), None).to_dict(orient="records")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/tokens")
def issue_token(body: TokenIn):
    """Issue a new token (call when a student takes a token)."""
    return db.issue_token(body.counter, body.service_type, body.issued_at, body.source)


@app.post("/tokens/{token_id}/serve")
def serve_token(token_id: int):
    """Staff pressed 'Next': service for this token starts now."""
    if not db.serve_token(token_id):
        raise HTTPException(404, "Token not found or already served")
    return {"id": token_id, "status": "serving"}


@app.post("/tokens/{token_id}/finish")
def finish_token(token_id: int):
    if not db.finish_token(token_id):
        raise HTTPException(404, "Token not found, not served yet, or already finished")
    return {"id": token_id, "status": "finished"}


@app.post("/observations")
def add_observation(body: ManualObservation):
    """Add a voluntary manual observation (stored with source='manual')."""
    if body.waited_min < 0:
        raise HTTPException(422, "waited_min must be >= 0")
    t = db.issue_token(body.counter, body.service_type, body.arrived_at, source="manual")
    db.serve_token(t["id"], pd.Timestamp(body.arrived_at) + pd.Timedelta(minutes=body.waited_min))
    return t


@app.get("/tokens")
def list_tokens(limit: int = 100):
    df = db.load_tokens().tail(limit)
    return _records(df.astype({"issued_at": str, "served_at": str, "finished_at": str}))


@app.get("/queue")
def queue():
    """Tokens currently waiting for service."""
    df = db.load_tokens()
    waiting = df[df["served_at"].isna()]
    return _records(waiting.astype({"issued_at": str, "served_at": str, "finished_at": str}))


@app.get("/analytics/summary")
def summary():
    return _records(analytics.waiting_summary(_prepared()))


@app.get("/analytics/hourly")
def hourly(sensitivity: float = config.PEAK_SENSITIVITY):
    hp = analytics.detect_peaks(analytics.hourly_stats(_prepared()), sensitivity)
    return _records(hp.round(2))


@app.get("/recommendations")
def recommendations(target_wait: float = config.TARGET_WAIT_MIN,
                    appointment_share: float = config.APPOINTMENT_SHARE,
                    sensitivity: float = config.PEAK_SENSITIVITY):
    df = _prepared()
    hp = analytics.detect_peaks(analytics.hourly_stats(df), sensitivity)
    return recommender.build_recommendations(df, hp, None, target_wait, appointment_share)


@app.post("/seed")
def seed_data(days: int = 5, reset: bool = False):
    """Load generated sample data (optionally wiping existing data first)."""
    if reset:
        db.clear_tokens()
    n = db.insert_dataframe(seed.generate_sample(days=days), source="sample")
    return {"inserted": n}


@app.post("/upload")
async def upload_csv(file: UploadFile = File(...)):
    """Import a CSV with columns counter, issued_at, served_at (optional: token_no, finished_at)."""
    try:
        df = pd.read_csv(io.BytesIO(await file.read()))
        n = db.insert_dataframe(df, source="upload")
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"inserted": n}


@app.delete("/tokens")
def clear():
    db.clear_tokens()
    return {"status": "cleared"}
