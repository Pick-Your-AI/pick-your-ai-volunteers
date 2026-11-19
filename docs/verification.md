# Verification record

Implementation is tested with synthetic identities only. No real application, invitation, membership or permission change is part of verification. Unit tests cover authority, disabled policy, stale/missing/absent reviewer, approved empty-route fallback, invalid actions, duplicate events, consented referrals and loops, escalation approvals/rejection, withdrawal, distinct invitation receipts, public exports and recommendation readiness. Schema and generated-file checks run in CI.

Fresh VM and GitHub readback results are recorded here after execution. A passing test does not establish reviewer availability, independent approval, completed legal work or a live website API. Actual reviewer mandates and fallback approval remain dependencies. No claim of end-to-end acceptance is made while those are absent.

## Executed 2026-10-30

A newly created isolated Ubuntu 24.04.5 KVM guest ran Python 3.12 with dependencies in a fresh virtual environment: **30 tests passed**, canonical validation passed for **134 records**, and generated forms/export consistency passed. Tests include the actual HTTP adapter under a mocked GitHub transport; they do not create public fake applicants. The [verification manifest](../data/verification.v1.json) binds tested source file hashes.

The initial Hyper-V guest attempts exposed boot/connectivity problems and were not counted as passes. The separate clean KVM guest completed the recorded checks. No WSL restart or termination was used.

Live authenticated GitHub reads verified 92 teams, repository relationships, the 13 prior Projects and new Volunteer Operations Project. The new public hub and Project are included in the 134-record directory. Team pages can require organization access; API verification does not promise public browser access. Private coordination contents and member identities are excluded from the export.

The operator Project has ten filtered views plus All volunteer records. Publication/merge, CI and final Project items are checked separately after publication. Main-branch application forms and intake workflows cannot be exercised before an independently approved merge. No live end-to-end intake pass is claimed.

GitHub publication readback: implementation PR #1 passed hosted `validate`; it remains review-required. Organization navigation PR #25 is also review-required and awaits the hub merge. Seven opportunity issues (#2–#8) were created from canonical records and synchronized to the public operator Project. No application issues or invitations were created. At this historical verification, the new hub had no independently eligible writer besides the author; an access decision outside that task was required to satisfy its review rule.

The 2026-10-30 manifest above is historical evidence for source at `f6669f7af335b4a6c120984e406093954fdff96b`. Its source hashes must not be represented as covering later repairs.

## Executed 2026-11-19

The repository completion campaign used the available Linux workspace with Python 3.12.14 and a virtual environment exposing the already installed pinned jsonschema 4.26.0 and PyYAML 6.0.3 packages. It did not create a new VM. Canonical validation passed for 134 records, all 98 tests passed, and generated files matched their source. The [current offline manifest](../data/verification.2026-11-19.json) binds the tested source, policy and schema hashes and records commands and limitations.

Independent source review identified additional malformed-input, explicit consent, unresolved-route, mutable account identity and placement-handoff cases beyond the original passing suite. Regressions cover those cases, visibly edited commands/ledgers, additive assignment with verified numeric identity, current destination mandates, typed invitation receipt references and later approved routing of a previously unassigned application. A separate test author wrote 25 acceptance tests without reading the implementation or its tests; these exposed four malformed routing metadata cases, all repaired before this run. The v2 authority contract and the mocked Project consumer are also exercised. Network transport remains mocked and all applicant/reviewer fixtures are synthetic. A route/capacity decision is not being activated by these tests.

Showcase PNGs were decoded and visually inspected; their bytes remain those from PR #9. The SVG's embedded icon was re-encoded to PNG with identical decoded pixels to repair the observed Inkscape WebP rendering issue. Its metadata now records the updated card and social-preview hashes. Paseo setup/teardown and all menu shell commands were executed locally after preparing the virtual environment. These are shell and repository checks, not Paseo application, fresh-VM, public GitHub rendering or live intake acceptance.

GitHub CI and approval are checked separately on the published candidate. Main initially contains only the README at `cddd346f447386ee452241c16c9a3079c3d64d5e`; local implementation checks do not make that default branch green. [The campaign tracker](https://github.com/Pick-Your-AI/pick-your-ai-volunteers/issues/11) records exact PR heads, remote check results, review disposition and remaining gates. See [the unblock packet](unblocking.md) for the actual authority, staffing and receiving-capacity evidence still needed for issues #2–#8.
