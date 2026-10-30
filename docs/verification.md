# Verification record

Implementation is tested with synthetic identities only. No real application, invitation, membership or permission change is part of verification. Unit tests cover authority, disabled policy, stale/missing/absent reviewer, approved empty-route fallback, invalid actions, duplicate events, consented referrals and loops, escalation approvals/rejection, withdrawal, distinct invitation receipts, public exports and recommendation readiness. Schema and generated-file checks run in CI.

Fresh VM and GitHub readback results are recorded here after execution. A passing test does not establish reviewer availability, independent approval, completed legal work or a live website API. Actual reviewer mandates and fallback approval remain dependencies. No claim of end-to-end acceptance is made while those are absent.

## Executed 2026-10-30

A newly created isolated Ubuntu 24.04.5 KVM guest ran Python 3.12 with dependencies in a fresh virtual environment: **28 tests passed**, canonical validation passed for **134 records**, and generated forms/export consistency passed. Tests include the actual HTTP adapter under a mocked GitHub transport; they do not create public fake applicants. The [verification manifest](../data/verification.v1.json) binds tested source file hashes.

The initial Hyper-V guest attempts exposed boot/connectivity problems and were not counted as passes. The separate clean KVM guest completed the recorded checks. No WSL restart or termination was used.

Live authenticated GitHub reads verified 92 teams, repository relationships, the 13 prior Projects and new Volunteer Operations Project. The new public hub and Project are included in the 134-record directory. Team pages can require organization access; API verification does not promise public browser access. Private coordination contents and member identities are excluded from the export.

The operator Project has ten filtered views plus All volunteer records. Publication/merge, CI and final Project items are checked separately after publication. Main-branch application forms and intake workflows cannot be exercised before an independently approved merge. No live end-to-end intake pass is claimed.
