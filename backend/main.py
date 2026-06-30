"""
main.py — entry point.
Run locally with: uvicorn main:app --reload --port 8000
"""

import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from database import Base, engine
from routes import auth, engine as engine_routes, billing, anon

Base.metadata.create_all(bind=engine)

app = FastAPI(title="PersonaOS API", version="0.1.0")

# Cookie-based auth requires allow_credentials=True, which in turn requires
# explicit origins — "*" is rejected by browsers when credentials are sent.
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:5500").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(engine_routes.router)
app.include_router(billing.router)
app.include_router(anon.router)


@app.get("/health")
def health():
    return {"status": "ok"}
