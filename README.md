# Automated Parking Management System (APMS)

[![CI](https://github.com/mallikarjunrao-sketch/Software_Engineering_Jackfruit/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/mallikarjunrao-sketch/Software_Engineering_Jackfruit/actions/workflows/ci.yml)
[![CD](https://github.com/mallikarjunrao-sketch/Software_Engineering_Jackfruit/actions/workflows/cd.yml/badge.svg?branch=main)](https://github.com/mallikarjunrao-sketch/Software_Engineering_Jackfruit/actions/workflows/cd.yml)

A simulated smart parking system: vehicle entry and exit, simulated number plate recognition (ANPR), slot allocation, live availability, automated billing, simulated payments and receipts, plus a staff dashboard with tariff management and reports. Built by a four-member team over three 4-day sprints, tracked on the PARK Jira board.

## Features

| Area | What it does |
|---|---|
| Entry | Plate capture from a simulated ANPR image or manual fallback, duplicate and full-lot denial, session and ticket creation |
| Slots | Nearest matching slot allocation for car, two-wheeler, EV and accessible bays, with atomic slot state updates |
| Availability | Live free/total counts per vehicle type on a display board, pushed over a WebSocket |
| Exit | Plate recognition at exit, fee calculation, pay before exit, gate authorisation and slot release |
| Billing | Tariff engine with grace period, first-hour and extra-hour fees, and a daily cap |
| Payment | Simulated gateway (success, failure, timeout), payment record and receipt number. No card data is stored |
| Staff | Role-based login, attendant override with audit trail, admin tariff editor, revenue and occupancy reports (JSON or CSV) |
| Security | Salted password hashing, server-side RBAC, append-only audit log, input validation, HTTPS enforcement, session timeout and login lockout |
| Operations | Backup, restore and retention job, performance, capacity and soak test scripts |

## Tech stack

- Python 3.11, FastAPI, Uvicorn
- SQLAlchemy with SQLite (`apms.db`, created on first run)
- Plain HTML/JS frontends served by the backend
- pytest, pytest-cov, ruff, bandit, pip-audit
- Docker, GitHub Actions (CI and CD)

## Project structure

```
backend/app/        FastAPI app: routers, services, models, auth, HTTPS middleware
frontend/           kiosk.html, board.html, dashboard.html
simulators/         ANPR and payment gateway simulators
tests/              unit, integration and system tests
performance/        load, capacity and soak test scripts
scripts/            check_tls.py (TLS check for APMS-SR-001)
Docs/               SRS, Test Plan, Architecture and Design (SAD), usability test plan
.github/workflows/  ci.yml and cd.yml
```

## Getting started

### Run locally

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn backend.app.main:app --reload
```

The database is created and seeded automatically on first start (4 zones, 50 slots, default tariffs and two demo accounts).

| Page | URL |
|---|---|
| Kiosk (entry and exit) | http://localhost:8000/kiosk |
| Availability board | http://localhost:8000/board |
| Staff dashboard | http://localhost:8000/dashboard |
| API docs (Swagger) | http://localhost:8000/docs |
| Health check | http://localhost:8000/health |

### Run with Docker

```bash
docker build -t apms .
docker run -p 8000:8000 apms
```

### Demo logins

| Username | Password | Role |
|---|---|---|
| `admin` | `admin123` | Admin: tariffs and reports |
| `attendant` | `attendant123` | Attendant: entry, exit and override |

These are development defaults. Set `SEED_ADMIN_PASSWORD` and `SEED_ATTENDANT_PASSWORD` before the first run to change them.

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `dev` | Anything other than `dev` requires `JWT_SECRET` and turns on HTTPS enforcement |
| `JWT_SECRET` | dev-only secret | Signing key for login tokens (must be set outside `dev`) |
| `FORCE_HTTPS` | on unless `APP_ENV=dev` | Redirect or refuse plain HTTP |
| `DATABASE_URL` | `sqlite:///./apms.db` | Database location |
| `AVAILABILITY_PUSH_SECONDS` | `1.0` | How often the board is pushed new counts |
| `BACKUP_DIR`, `BACKUP_KEEP_DAYS`, `RECORD_RETENTION_DAYS` | `backups`, `30`, `365` | Backup job settings |

## Demo walkthrough

Start the server, then open the kiosk (`/kiosk`) and the board (`/board`) side by side so you can watch availability change live.

**1. Check availability.** The board shows free and total slots per vehicle type (seeded: 20 car, 20 two-wheeler, 5 EV, 5 accessible).

**2. Vehicle entry (manual plate).** On the kiosk, open the Entry tab, type `KA01AB1234`, choose *car* and submit. A ticket number and slot are shown, the gate indicator opens, and the board's car count drops by one.

**3. Duplicate entry is denied.** Submit `KA01AB1234` again. Entry is refused because that vehicle already has an active session.

**4. Entry with simulated ANPR.** Enter an image reference such as `entry_cam_KA02CD5678.jpg`. The plate is recognised from the file name and a ticket is issued.
- `entry_cam_LOWCONF_KA03EF9012.jpg` is rejected as low confidence (below 0.80), so type the plate manually instead.
- `UNREADABLE.jpg` fails recognition and also falls back to manual entry.

**5. Vehicle exit.** Open the Exit tab and enter the plate (or an exit image reference). The kiosk finds the active session and shows the amount due.

**6. Pay and leave.**
- Within the grace period (10 minutes for cars) the fee is 0, so the kiosk goes straight to exit authorisation.
- To see a paid exit without waiting, log in to the dashboard as `admin`, open Tariffs and set the car grace period to 0, then repeat steps 2 and 5 after at least one full minute. Choose a payment mode (cash, card or UPI) and pay. A receipt number is issued, the gate opens and the slot is freed on the board.

**7. Attendant override.** Log in to the dashboard as `attendant`, open Vehicle exit, look up a plate and use *Override exit* with a reason. The session closes, the slot is freed and the override is written to the audit log.

**8. Admin tools.** Log in as `admin` to edit tariffs (the new fee applies to later sessions) and to view or download revenue and occupancy reports as JSON or CSV.

### Main API endpoints

| Workflow | Endpoint | Notes |
|---|---|---|
| Entry | `POST /api/v1/entries` | Body: `plate` or `imageRef`, plus `vehicleType`. Returns session, slot and ticket |
| Exit lookup | `POST /api/v1/exits` | Recognises the plate and returns the active session and amount due |
| Fee | `GET /api/v1/sessions/{id}/fee` | Duration, amount due and tariff breakdown |
| Payment | `POST /api/v1/payments` | Optional `simulate`: `success` (default), `failure` or `timeout` |
| Exit authorisation | `POST /api/v1/exits/{id}/authorise` | Rejected unless paid (or free) |
| Override | `POST /api/v1/exits/{id}/override` | Staff login required, reason recorded in the audit log |
| Availability | `GET /api/v1/availability` | Optional `zone` filter. Live feed on `WS /ws/availability` |
| Login | `POST /api/v1/auth/login` | Returns a bearer token. 5 failed attempts lock the account for 5 minutes |
| Reports | `GET /api/v1/reports/revenue`, `/occupancy` | Admin only. Add `format=csv` for a download |
| Audit log | `GET /api/v1/admin/audit` | Admin only |

Full request and response schemas are in the Swagger docs at `/docs`.

## Testing

```bash
ruff check backend simulators tests
pytest --cov=backend --cov=simulators
```

CI also enforces a minimum of 70% coverage.

Extra checks:

```bash
python performance/add_slots.py                # add car slots before load tests
python performance/load_test.py                # entry decision time and availability delay
python performance/capacity_test.py            # many slots, simultaneous gates
python performance/soak_test.py --minutes 5    # uptime from health checks
python scripts/check_tls.py https://<host>     # TLS 1.2+ check
```

The performance scripts expect the server to be running on `http://localhost:8000` (change with `--base-url`).

### Backup and retention

```bash
python -m backend.app.maintenance backup        # verified backup now
python -m backend.app.maintenance restore <file> --force
python -m backend.app.maintenance run-daily     # backup, prune old backups, report purgeable records
python -m backend.app.maintenance purge --apply # delete closed records past retention (dry run without --apply)
```

## CI/CD

- **CI** (`.github/workflows/ci.yml`) runs on every pull request and push to `main`: ruff lint, pytest with coverage (at least 70%), bandit static security scan, pip-audit dependency scan and a Docker build.
- **CD** (`.github/workflows/cd.yml`) runs on push to `main` and publishes the Docker image to GitHub Container Registry.

## Team workflow

1. Pick a Jira ticket (project key `PARK`) and create a branch named `PARK-<number>-short-description`.
2. One story per branch and pull request, with the key in the PR title. Use the PR template.
3. Move the ticket to In Progress when you start, In Review when the PR is open, and Done only after it is merged with CI green.
4. A teammate reviews each PR before merge.

| Member | Area |
|---|---|
| Member 1 (KS) | Entry and ANPR, kiosk UI, usability, final documents |
| Member 2 (MR) | Slots, availability, dashboard UI, capacity and performance tests |
| Member 3 (MM) | Billing, payment, exit, override, test reports |
| Member 4 (MS) | CI/CD, login and roles, security, reports, ZAP scan |

## Documentation

Project documents are in `Docs/`: the SRS (with requirement traceability), Test Plan, Software Architecture and Design (SAD), and the PARK-43 usability test plan.
