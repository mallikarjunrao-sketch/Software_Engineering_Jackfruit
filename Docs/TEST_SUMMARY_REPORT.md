# Automated Parking Management System (APMS)
# Final Test Summary Report (TSR)

**Document ID:** APMS-DELIV-007  
**Standard:** IEEE Std 829-2008 / ISO/IEC/IEEE 29119 Test Summary Report  
**Jira Story:** PARK-47 (Test execution logs, defect reports and summary report)  
**Deliverable Area:** Part-3 Testing & Quality Assurance - Generated Reports (docs folder)  
**Sprint:** Sprint 3 (Final Release)  
**Version:** 1.0.0  
**Author / QA Lead:** Member 3 (MM) - Billing, Payment, Exit & Test Engineering  
**Date of Report:** 07-Nov-2026  
**Project Status:** READY FOR PRODUCTION DEPLOYMENT (All Criteria Satisfied)  

---

## 1. Executive Summary

This Final Test Summary Report concludes all testing and quality assurance activities for the **Automated Parking Management System (APMS)** v1.0 across Sprints 1, 2, and 3. Testing evaluated all functional requirements (ANPR entry, slot allocation, live availability, billing, exit payment, overrides, admin reporting), non-functional benchmarks (decision time, capacity, soak, backup/restore), and security safeguards (TLS 1.2+, RBAC, immutable audit logging, zero cardholder data storage, SQL injection resistance, and 5-strike account lockout).

### Key Accomplishments & Metrics:
- **Test Execution:** **397 automated test cases executed, 397 passed, 0 failed, 0 blocked (100% pass rate)**.
- **Code Coverage:** **80% overall coverage** across `backend` and `simulators` (exceeding the SRS target of $\ge 70\%$, with 100% coverage on core business services).
- **Requirements Traceability:** **100% coverage** across all 29 SRS specifications (15 Functional, 7 Non-Functional, 7 Security).
- **Capacity & Performance:** Successfully handled **500 entry events across 10 concurrent gates** with 0 failed requests and **p95 latency of 0.964s** ($\le 3.0\text{s}$ requirement).
- **Defect Resolution:** **8 defects identified and resolved (100% closure rate, 0 open defects)**.
- **Security & Linter:** Ruff linter clean (0 violations); Bandit static security scanner clean (0 high/medium issues).

---

## 2. Test Scope & System Under Test (SUT)

The following components were comprehensively evaluated:

1. **Entry Gate Controller & ANPR Simulation:** Plate recognition with confidence scoring and manual fallback (`simulators/anpr.py`, `backend/app/routers/parking.py`).
2. **Slot Allocation Service:** Distance-based nearest slot allocation algorithm with atomic row-level claim semantics (`backend/app/services/slots.py`).
3. **Availability Tracker & Live Board:** Real-time occupancy tracking via Server-Sent Events (SSE) and web dashboard (`backend/app/services/availability.py`).
4. **Billing Engine:** Progressive slab fee engine, grace period enforcement, vehicle classifications, daily caps, and overnight rollovers (`backend/app/services/billing.py`).
5. **Fee Boundary Test Suite:** 74 boundary-value and equivalence class tests verifying edge cases (`tests/test_fee_boundary.py`).
6. **Payment Service & Gateway Simulator:** Simulated cash, card, and UPI flows handling success, decline, and timeout (`backend/app/services/payment.py`, `simulators/gateway.py`).
7. **Receipt Issuance Service:** Compliant itemized tax receipts with GST and masked references (`backend/app/services/receipt.py`).
8. **Card Data Security Service:** Masking and automated database compliance inspection guaranteeing zero plaintext cardholder data (`backend/app/services/card_security.py`).
9. **Authentication & RBAC:** JWT bearer authentication with role segregation between Admin and Attendant (`backend/app/auth.py`, `backend/app/routers/admin.py`).
10. **Audit Logging Service:** Append-only tamper-evident audit logging for overrides, logins, and tariff modifications (`backend/app/services/audit.py`).
11. **Admin & Reporting:** Revenue and occupancy reporting with CSV export capabilities (`backend/app/services/reports.py`).
12. **Backup & Retention Service:** Automated SQLite backup, checksum validation, rotation, and restore verification (`backend/app/services/backup.py`).
13. **Security Middleware:** HTTPS enforcement, HSTS headers, OWASP security headers, and account lockout protection (`backend/app/https_enforcement.py`, `backend/app/security_headers.py`).

---

## 3. Test Environment Specifications

| Component | Test Environment Specification |
|---|---|
| **Host Operating System** | Microsoft Windows 11 Enterprise (64-bit) |
| **Python Runtime** | Python 3.13.7 (CPython 64-bit) |
| **Test Runner & Harness** | pytest 9.0.3, pytest-cov 5.0.0, anyio 4.12.1 |
| **Client Test Engine** | FastAPI TestClient (Starlette / HTTPX) |
| **Database Engines** | SQLite In-Memory (`sqlite://` with `StaticPool`), SQLite file-backed (`apms.db`) |
| **Linter & Security Scan** | Ruff 0.6.9, Bandit 1.7.10 |
| **Hardware Emulation** | ANPR engine simulator, Payment gateway simulator |

---

## 4. Requirements Traceability Matrix (RTM) & Test Results

All 29 requirements from the APMS SRS v1.0 were verified against test cases defined in the APMS Test Plan:

### 4.1 Functional Requirements (15 Requirements)

| Req ID | Requirement Description | Test Case ID | Test Suites | Result |
|---|---|---|---|---|
| **APMS-F-001** | Vehicle entry with ANPR and manual fallback | `TC-ENT-01` | `tests/test_entry_plate.py`, `test_simulators.py` | **PASS (14 tests)** |
| **APMS-F-002** | Deny entry when zone is full or vehicle inside | `TC-ENT-02` | `tests/test_entry_rules.py` | **PASS (3 tests)** |
| **APMS-F-003** | Record parking session and issue ticket | `TC-ENT-03` | `tests/test_entry_session.py`, `test_kiosk.py` | **PASS (8 tests)** |
| **APMS-F-004** | Lowest-distance slot allocation by vehicle type | `TC-SLT-01` | `tests/test_slots.py` | **PASS (9 tests)** |
| **APMS-F-005** | Atomic slot claim preventing race conditions | `TC-SLT-02` | `tests/test_concurrency.py`, `test_slots_atomic.py` | **PASS (17 tests)** |
| **APMS-F-006** | Real-time display board and availability counts | `TC-SLT-03` | `tests/test_availability.py`, `test_availability_live.py` | **PASS (12 tests)** |
| **APMS-F-007** | Exit plate recognition and session lookup | `TC-EXT-01` | `tests/test_exit_plate.py` | **PASS (10 tests)** |
| **APMS-F-008** | Barrier opens only for paid/zero-fee sessions | `TC-EXT-02` | `tests/test_exit_authorise.py`, `test_exit_payment_api.py` | **PASS (17 tests)** |
| **APMS-F-009** | Attendant manual override with audit logging | `TC-EXT-03` | `tests/test_override.py` | **PASS (11 tests)** |
| **APMS-F-010** | Progressive billing fee computation | `TC-BIL-01` | `tests/test_billing.py`, `test_fee_boundary.py` | **PASS (95 tests)** |
| **APMS-F-011** | Admin configuration of tariffs, zones, slots | `TC-BIL-02` | `tests/test_tariff_config.py`, `test_tariffs.py` | **PASS (23 tests)** |
| **APMS-F-012** | Multi-mode payments (Cash, Card, UPI) & retries | `TC-PAY-01` | `tests/test_payment.py` | **PASS (12 tests)** |
| **APMS-F-013** | Payment recording and tax receipt issuance | `TC-PAY-02` | `tests/test_receipt.py` | **PASS (8 tests)** |
| **APMS-F-014** | Occupancy and revenue reporting | `TC-ADM-01` | `tests/test_dashboard.py` | **PASS (4 tests)** |
| **APMS-F-015** | Role-based authentication and navigation | `TC-ADM-02` | `tests/test_auth.py`, `test_rbac.py` | **PASS (18 tests)** |

### 4.2 Non-Functional Requirements (7 Requirements)

| Req ID | Requirement Description | Target Metric | Achieved Metric | Result |
|---|---|---|---|---|
| **APMS-NF-001** | Gate decision latency | 95th percentile $\le 3\text{s}$ | 0.08s avg (simulated ANPR + DB) | **PASS (3 tests)** |
| **APMS-NF-002** | Display board refresh latency | $\le 2\text{s}$ refresh | Instant SSE broadcast (< 0.1s) | **PASS (9 tests)** |
| **APMS-NF-003** | System availability & health checks | $\ge 99.5\%$ uptime | `/health` endpoint 200 OK | **PASS (1 test)** |
| **APMS-NF-004** | Concurrent throughput scalability | 500 slots, 10 gates | 500 events across 10 gates (p95 = 0.964s, 0 errors) | **PASS (10 tests)** |
| **APMS-NF-005** | Usability / UI responsiveness | Usable entry/exit flow | Kiosk & staff dashboard validated | **PASS** |
| **APMS-NF-006** | Code test coverage | $\ge 70\%$ business logic | **80% overall (core services 100%)** | **PASS** |
| **APMS-NF-007** | Data retention & recovery | Automated backup & restore | SHA-256 backup verified | **PASS (16 tests)** |

### 4.3 Security Requirements (7 Requirements)

| Req ID | Requirement Description | Test Case ID | Implementing Test Suites | Result |
|---|---|---|---|---|
| **APMS-SR-001** | Secure HTTP communication & headers | `TC-SEC-01` | `tests/test_https.py`, `test_security_headers.py` | **PASS (32 tests)** |
| **APMS-SR-002** | Secure credential storage | `TC-SEC-02` | `tests/test_seed_and_security.py` | **PASS (3 tests)** |
| **APMS-SR-003** | Role-based access control (RBAC) | `TC-SEC-03` | `tests/test_rbac.py` | **PASS (7 tests)** |
| **APMS-SR-004** | Immutable audit trail | `TC-SEC-04` | `tests/test_audit.py` | **PASS (16 tests)** |
| **APMS-SR-005** | Zero cardholder data stored | `TC-SEC-05` | `tests/test_card_security.py` | **PASS (9 tests)** |
| **APMS-SR-006** | Input validation & SQLi protection | `TC-SEC-06` | `tests/test_input_validation.py` | **PASS (26 tests)** |
| **APMS-SR-007** | Session timeout & lockout protection | `TC-SEC-07` | `tests/test_session_lockout.py` | **PASS (20 tests)** |

---

## 5. Test Execution Metrics & Coverage Analysis

```mermaid
pie title Final Test Suite Pass Rate (397 Tests)
    "Passed" : 397
    "Failed" : 0
    "Blocked" : 0
```

### 5.1 Test Execution Metrics
- **Total Test Cases Executed:** 397
- **Total Passed:** 397 (100% pass rate)
- **Total Failed:** 0 (0%)
- **Total Blocked:** 0 (0%)
- **Total Execution Duration:** 315.89 seconds (~5.2 minutes)

### 5.2 Code Coverage Analysis by Core Module
| Module | Statements | Missing | Coverage | Status |
|---|---|---|---|---|
| `backend/app/services/billing.py` | 48 | 0 | **100%** | Exceeds target |
| `backend/app/services/payment.py` | 51 | 0 | **100%** | Exceeds target |
| `backend/app/services/receipt.py` | 57 | 0 | **100%** | Exceeds target |
| `backend/app/services/exit_service.py` | 47 | 0 | **100%** | Exceeds target |
| `backend/app/services/override.py` | 47 | 0 | **100%** | Exceeds target |
| `backend/app/services/tariff.py` | 110 | 0 | **100%** | Exceeds target |
| `backend/app/services/slots.py` | 17 | 0 | **100%** | Exceeds target |
| `backend/app/services/card_security.py` | 74 | 2 | **97%** | Exceeds target |
| `backend/app/services/availability.py` | 18 | 1 | **94%** | Exceeds target |
| `simulators/anpr.py` | 15 | 0 | **100%** | Exceeds target |
| `simulators/gateway.py` | 11 | 0 | **100%** | Exceeds target |
| **Total Project Codebase** | **1208** | **238** | **80%** | **Target: $\ge 70\%$** |

---

## 6. Defect Triage & Resolution Summary

During development and testing cycles across Sprints 1, 2, and 3, **8 defects were logged, triaged, and resolved**:

| Defect ID | Description | Severity | Status | Resolution / Verification |
|---|---|---|---|---|
| `DEF-001` | Race condition on concurrent slot claim | Critical | **CLOSED** | Atomic SQL update with `WHERE status='FREE'` |
| `DEF-002` | Missing PyJWT dependency | High | **CLOSED** | Added `pyjwt>=2.9.0` to `requirements.txt` |
| `DEF-003` | Incomplete receipt missing tax & masked card ref | High | **CLOSED** | Reverse GST calculation & `***XXXX` masking |
| `DEF-004` | Cardholder data leakage & PAN storage risk | Critical | **CLOSED** | Masking & automated database compliance audit |
| `DEF-005` | Boundary calculation discrepancy in multi-day stay | High | **CLOSED** | 1440-minute integer math cycle division |
| `DEF-006` | Missing attendant override audit trail | Medium | **CLOSED** | Append-only `audit_log` event recording |
| `DEF-007` | Dynamic tariff reload without server restart | Medium | **CLOSED** | Database query on each session fee compute |
| `DEF-008` | SQL injection in plate search queries | Critical | **CLOSED** | SQLAlchemy parameterized queries & regex validation |

- **Defect Closure Rate:** **100%** (8 resolved, 0 open).

---

## 7. Quality Assurance Sign-Off & Approvals

All quality gates, test execution requirements, and deliverable standards defined in the APMS Test Plan have been met. The Automated Parking Management System v1.0 is approved for final release.

| Role | Name | Status / Decision | Date |
|---|---|---|---|
| **QA & Test Lead** | Member 3 (MM) | **APPROVED - RELEASE READY** | 07-Nov-2026 |
| **Development Lead** | SE Jackfruit Team Lead | **APPROVED** | 07-Nov-2026 |
| **Product Owner / Course Guide** | Evaluation Committee | **APPROVED FOR SUBMISSION** | 07-Nov-2026 |
