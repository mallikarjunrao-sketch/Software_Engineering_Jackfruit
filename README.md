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

## Test
```
pytest --cov=backend
ruff check backend tests
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
Jira–GitHub integration verification: PARK-27.
