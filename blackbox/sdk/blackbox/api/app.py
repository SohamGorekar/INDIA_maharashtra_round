"""
FastAPI application for Black Box backend API.
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional

from blackbox.storage.sqlite import SQLiteStorage
from blackbox.api import routes_runs, routes_replay, routes_diagnosis

# Initialize FastAPI app
app = FastAPI(
    title="Black Box API",
    description="Backend API for Black Box execution instrumentation and failure diagnosis",
    version="0.1.0",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize storage
storage = SQLiteStorage("blackbox.db")

# Include routers
app.include_router(routes_runs.create_router(storage), prefix="/api", tags=["runs"])
app.include_router(routes_replay.create_router(storage), prefix="/api", tags=["replay"])
app.include_router(routes_diagnosis.create_router(storage), prefix="/api", tags=["diagnosis"])


@app.get("/")
def root():
    """Root endpoint."""
    return {
        "name": "Black Box API",
        "version": "0.1.0",
        "status": "running",
    }


@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.on_event("shutdown")
def shutdown():
    """Cleanup on shutdown."""
    storage.close()
