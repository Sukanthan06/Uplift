from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.audit import router as audit_router
from app.api.batch import router as batch_router
from app.api.decisions import router as decisions_router
from app.api.overview import router as overview_router

app = FastAPI(title="Uplift", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(audit_router)
app.include_router(overview_router)
app.include_router(batch_router)
app.include_router(decisions_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
