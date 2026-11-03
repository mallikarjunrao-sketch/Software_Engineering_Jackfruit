# PARK-43 — APMS Usability Test Plan and Results Sheet

## Objective
Evaluate whether five first-time users can complete the main Automated Parking Management System (APMS) kiosk and availability-board tasks without assistance. Record observed outcomes; do not fill in results before each participant completes the tasks.

## Test setup
- Application: local APMS build from this repository.
- Interfaces: `/kiosk` and `/board` (availability board).
- Use a clean/test database or reset the test data between participants.
- Use fictional test registration numbers only.
- The payment gateway is simulated; no real money or card details are used.
- Ask permission before taking screenshots or recording a participant.

## Participant task script
Give each participant the task, but do not explain the interface unless they become stuck. Record completion time and any assistance.

| ID | Task | Expected outcome |
|---|---|---|
| U1 | Enter a vehicle using a manually typed valid plate and choose the vehicle type. | Entry succeeds, a ticket number and slot are displayed, and the entry gate indicator opens. |
| U2 | Enter another vehicle using a supported simulated ANPR image reference. | Plate is recognised and a ticket/slot is displayed. |
| U3 | Try to enter a plate that already has an active session. | Entry is denied with a clear duplicate-session message. |
| U4 | Find an active vehicle at exit using its plate or exit-camera image. | The active session and amount due are displayed. |
| U5 | Complete a paid exit using the simulated successful payment option. | Payment succeeds, receipt number is shown, session closes, gate opens and slot becomes free. |
| U6 | Complete an exit within the free grace period. | No payment is requested; session closes and gate opens. |
| U7 | View the availability board and identify the free spaces for a vehicle type. | Current availability is understandable and matches the backend state. |

Optional error checks (if time permits): unreadable/low-confidence image with manual fallback; unknown exit plate; simulated payment failure and timeout. The gate must remain closed after a failed/timed-out payment.

## Per-participant record

Copy this section once for each of the five participants. Use anonymous labels P1–P5.

| Field | Record |
|---|---|
| Participant ID | P__ |
| Date/time | |
| Completed tasks | |
| Tasks not completed | |
| Total task time | |
| Assistance required | |
| Overall ease rating (1 = very difficult, 5 = very easy) | |
| Interface clarity rating (1 = unclear, 5 = very clear) | |
| Confusing/difficult part (participant's words) | |
| Suggested improvement (participant's words) | |
| Observed defects / screenshots (with permission) | |

## Consolidated results (complete after all five sessions)

| Metric | Result |
|---|---|
| Participants tested | __ / 5 |
| Total tasks attempted | |
| Tasks completed without help | |
| Tasks completed with help | |
| Tasks not completed | |
| Mean ease rating | |
| Most common issue | |
| Highest-priority improvement | |

## Issue log

| Issue ID | Participant | Task | Actual behaviour | Expected behaviour | Severity | Screenshot/evidence | Status |
|---|---|---|---|---|---|---|---|
| UX-01 | | | | | | | Open |

## Completion criteria
- Five real participants have attempted the task script.
- Each participant's completion, timing, assistance and feedback are recorded.
- Observed defects are logged with evidence where permission was given.
- The consolidated results and improvement actions are completed from the actual observations.

**Important:** This file is a test protocol and blank results sheet. It is not evidence that five participants have already tested the system.
