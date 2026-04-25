from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.database import engine, Base
from app.routers import auth, scanner, trades, settings_router

Base.metadata.create_all(bind=engine)

app = FastAPI(title="AussieInvest API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(scanner.router, prefix="/api/scanner", tags=["scanner"])
app.include_router(trades.router, prefix="/api/trades", tags=["trades"])
app.include_router(settings_router.router, prefix="/api/settings", tags=["settings"])

@app.get("/api/health")
def health():
    return {"status": "ok", "version": "1.0.0", "name": "AussieInvest"}
