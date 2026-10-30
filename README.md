# Automated Parking Management System (APMS)

![CI](../../actions/workflows/ci.yml/badge.svg)

Simulation of a smart parking system: vehicle entry and exit, simulated number plate recognition, slot allocation, real-time availability, automated billing and simulated payments.

## Structure
- backend/ - FastAPI services
- frontend/ - kiosk, attendant and admin UI
- simulators/ - ANPR and payment gateway simulators
- tests/ - unit, integration and system tests
- docs/ - SRS, Test Plan and Software Architecture and Design

## Run locally
```
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.app.main:app --reload
```
Open http://localhost:8000/health and http://localhost:8000/docs

## Sprint 1 starter code
Included and working: database models and seed data, password hashing, ANPR simulator, payment gateway simulator, availability endpoint, error format, tests.
Stubbed (return 501 NOT_IMPLEMENTED until built): entries, exits, authorise, override, fee, payments.

| Story | Where to work |
|---|---|
| PARK-9, 10, 11 (entry) | backend/app/routers/parking.py, create_entry |
| PARK-12, 13 (slot allocation, atomic update) | new backend/app/services/slots.py, used by create_entry |
| PARK-18 (fee) | new backend/app/services/billing.py, get_fee in routers/billing.py |
| PARK-20, 21 (payment, receipt) | create_payment in routers/billing.py, simulators/gateway.py |
| PARK-23, 29 (login, hashing) | new backend/app/routers/auth.py, backend/app/security.py |
| PARK-24 (schema and seed) | backend/app/models.py, backend/app/seed.py |
| PARK-25, 26 (simulators) | simulators/anpr.py, simulators/gateway.py |

When you implement an endpoint, remove its row from tests/test_stubs.py and add real tests.

Demo logins after first run: admin / admin123 and attendant / attendant123. Override with SEED_ADMIN_PASSWORD and SEED_ATTENDANT_PASSWORD.

## Test
```
pytest --cov=backend --cov=simulators
ruff check backend simulators tests
```

## Workflow
1. Pick a Jira ticket (project key PARK) and create a branch named PARK-<id>-short-description
2. Commit often and open a pull request to main using the template
3. CI must pass and one teammate must approve before merge
4. Merge to main triggers the CD workflow

## Team
| Member | Area |
|---|---|
| Member 1 | Entry and ANPR |
| Member 2 | Slots and availability |
| Member 3 | Billing, payment and exit |
| Member 4 | Platform, security and DevOps |


## Jira ticket — PARK-15: Recognise Plate at Exit

### What changed

Implemented the `POST /api/v1/exits` workflow for APMS-F-007. The exit endpoint now accepts either a manually entered registration plate or an image reference from the exit ANPR simulator. It reuses the existing plate-recognition and validation logic used by vehicle entry, then retrieves the matching active parking session.

- Manual registration numbers are normalised by removing whitespace and converting letters to uppercase.
- Image references are processed by the existing `simulators.anpr.recognise()` service.
- Recognition confidence below the existing 0.80 threshold is rejected with `LOW_CONFIDENCE`, allowing the caller to retry with a manually entered plate.
- Unreadable images, missing input and invalid registration formats return the existing structured API errors.
- The endpoint searches only for sessions with `ACTIVE` status. If no active session matches the recognised plate, it returns `404 SESSION_NOT_FOUND`.
- The existing billing service is reused to calculate the current amount due for the response. No payment is initiated by this endpoint.

### Exit API

`POST /api/v1/exits`

Example image-based request:

```json
{
  "imageRef": "exit_cam_KA01AB1234.jpg"
}
```

Example manual fallback request:

```json
{
  "plate": "KA01AB1234"
}
```

Successful response (`200 OK`) follows the existing `ExitResponse` schema:

```json
{
  "sessionId": 1,
  "amountDue": 50,
  "status": "ACTIVE"
}
```

### Scope and separation

PARK-15 identifies the vehicle and retrieves its active session. It does not authorise or open the exit gate, close the session, release the parking slot, process payment, or implement kiosk UI. Those responsibilities remain with their respective exit-authorisation, slot-management, payment and frontend workflows.

### Verification

Added exit-recognition tests for image recognition, manual plate normalisation, missing/invalid/unreadable/low-confidence inputs, active-session lookup, missing active sessions and selection of an active session when historical paid sessions exist. The exit-start endpoint was also removed from the unimplemented-endpoint test list; the other exit endpoints remain stubs.
