from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.app.database import Base, SessionLocal, engine
from backend.app.errors import ApiError, api_error_handler
from backend.app.routers import auth, availability, billing, parking, simulated
from backend.app.seed import seed_database


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_database(db)
    yield


app = FastAPI(title="Automated Parking Management System", version="1.0.0", lifespan=lifespan)
app.add_exception_handler(ApiError, api_error_handler)
app.include_router(parking.router)
app.include_router(billing.router)
app.include_router(auth.router)
app.include_router(availability.router)
app.include_router(simulated.router)


@app.get("/health")
def health():
    return {"status": "ok"}
