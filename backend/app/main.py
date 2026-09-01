from fastapi import FastAPI

from app.api.audit import router as audit_router

app = FastAPI(title="Uplift", version="0.1.0")
app.include_router(audit_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
