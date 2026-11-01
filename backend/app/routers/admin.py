from fastapi import APIRouter, Depends

from backend.app.auth import require_admin

# Every route added to this router is admin-only (APMS-SR-003).
# PARK-19 adds the tariff routes here, so they inherit the check automatically.
router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


@router.get("/ping")
def admin_ping():
    return {"status": "ok"}