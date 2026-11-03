from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.database import Base, SessionLocal, engine
from backend.app.errors import ApiError, api_error_handler
from backend.app.https_enforcement import HTTPSEnforcementMiddleware
from backend.app.routers import admin, auth, availability, billing, dashboard, kiosk, parking, reports, simulated
from backend.app.seed import seed_database

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_database(db)
    yield


app = FastAPI(title="Automated Parking Management System", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["null", "http://127.0.0.1:8000", "http://localhost:8000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_exception_handler(ApiError, api_error_handler)
app.add_middleware(HTTPSEnforcementMiddleware)
app.include_router(parking.router)
app.include_router(billing.router)
app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(reports.router)
app.include_router(availability.router)
app.include_router(availability.live_router)
app.include_router(dashboard.router)
app.include_router(simulated.router)
app.include_router(kiosk.router)


@app.get("/health")
def health():
    return {"status": "ok"}
