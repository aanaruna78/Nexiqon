# Usability test: Phase 1 (UX-07)

**Goal:** check that a first-time admin can get oriented and do the foundation tasks without help.
**Participants:** 5, mixing support leads/knowledge managers (P1), IT admins (P2) and developers (P3).
**Setup:** local stack (`make dev-up PROFILES=platform,apps`), Studio on `localhost:3100`, a fresh Keycloak
user per participant. Moderated, think-aloud, 30 minutes, screen recording with consent.

| # | Task (read to participant) | Success | Target |
|---|---|---|---|
| T1 | "Sign in and create an organization for your company." | Lands on Home with the org name shown | < 2 min, no help |
| T2 | "Invite a colleague as an editor." | Invite listed as *Invited* with role Editor | < 1 min |
| T3 | "Your developer needs a key for the backend. Create one and keep it safe." | Copies the key before closing the dialog | < 2 min; understands it is shown once |
| T4 | "Find out who changed what in your organization today, and check nothing was tampered with." | Opens Audit log, runs *Verify chain* | < 1 min |
| T5 | "Create a retention profile that keeps conversations for 30 days and make it live in dev." | Draft → publish → deploy to dev | < 3 min |
| T6 | "Go to the API keys page without using the mouse." | Uses ⌘K / Ctrl+K or Tab navigation | Discovers within 1 min |
| T7 | "Switch Studio to Arabic and back." | Finds language in the user menu or palette | < 1 min |

**Measure:** task success, time, errors, SUS questionnaire after the session (target ≥ 80, UX.md §6).
**Watch for:** wording that confuses ("publish" vs "deploy"), anything skipped in the key dialog, where
people look for settings, keyboard traps, RTL layout glitches.

Log findings in a table (severity 1–4, screen, observation, suggested change) and triage them into the
first week of the next phase (UX.md §7).
