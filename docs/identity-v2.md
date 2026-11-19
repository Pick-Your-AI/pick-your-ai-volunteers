# Intake identity and authority v2

## Why the version changes

GitHub logins are display and routing labels. They are not the account identity used to authorize a decision. V2 binds the applicant, reviewers, audit actor and pending recipient to positive numeric GitHub account IDs. This prevents a rename from blocking withdrawal and prevents a reused login or reviewer alias from inheriting another account's mandate.

The authority file is now [data/authority.v2.json](../data/authority.v2.json), validated by [authority.v2.schema.json](../schemas/authority.v2.schema.json). Its `schema_version` is `2.0.0`; it remains disabled with no reviewers, routes or fallback appointments. The public directory and application/decision content schemas retain their own v1 versions. Research contracts and public exports are unaffected.

| Field | Meaning |
| --- | --- |
| Reviewer map key | Stable policy alias referenced by routes and escalation lists; never assigned as a GitHub login without identity resolution |
| `github_user_id` | Unique approved account ID attached to a reviewer mandate |
| `applicant_id` / `actor_id` | Account IDs from trusted GitHub issue/comment metadata |
| `reviewer_id` / `pending_reviewer_id` | Account identity bound when an assignment or handoff is proposed |
| `visited_ids` | Account identities already visited; aliases cannot evade loop prevention |
| `ledger_version` | `2`, with the `volunteer-ledger:v2` comment marker |

Before an assignment, the runtime resolves the approved account through GitHub's [get-user-by-ID endpoint](https://docs.github.com/en/rest/users/users#get-a-user-using-their-id), verifies that the returned ID matches, and adds only its current safe login. Only the ID/login needed for this operation is used; profile/contact fields are not copied to ledger or Project records. This lookup is mocked in tests and has not been exercised live by this campaign.

## Consent and route selection

Initialization requires the explicit checked Visibility consent sentence and one allowed Referral preference from the generated form. Canonical interests are read only from the four Preferred sections. Mentioning an entity in skills, alternatives or another free-text section does not select it. Incomplete, duplicated, unknown or ambiguous fields produce a generic review failure before a ledger or assignee is written; they are not copied into an export.

An explicit Help/No preference choice may use the policy's approved global empty-route fallback. Absent preferences and `_No response_` stay unassigned. A named selected scope needs its own nonempty approved route; an absent or empty route is not permission to apply the global fallback. Multiple inconsistent routes require clarification. Stored consent and selections govern later commands so editing the issue body cannot silently change them or prevent withdrawal.

## Pending handoffs and invitation evidence

Applicant-requested reviewer escalation is available in each nonterminal application, accepted, onboarding, invitation and active lifecycle state. The current reviewer may be unavailable; a distinct currently authorized escalation approver is still required. Approval or rejection restores the original lifecycle state. A pending destination must retain both its approved account ID and the originating mandate's authorization at completion. Revocation blocks transfer; cancellation remains available under the documented applicant/approver rules.

Commands validate scalar types and required per-action fields before changing state or adding audit history. Invitation records require a public HTTP(S) receipt reference. A recorded receipt is the operator's attestation; the workflow does not independently verify the invitation or contact the referenced site. Numeric IDs and boolean flags must have their declared types, not merely truthy values.

## Historical data and migration

PR #1 was unmerged when v2 was introduced; this campaign performed no live ledger migration. The old policy remains available in Git history. An operator must not activate an old v1 policy or copy a login into `github_user_id`. Obtain an explicit reviewed mandate tied to the actual account ID, fresh availability, approved routes and response period before proposing an enabled v2 policy.

Trusted v1 ledger markers, missing v2 identity metadata, mismatched applicant IDs or visibly edited audit comments stop processing for manual reconciliation. Existing records are never silently reset to `new`, and a v2 comment cannot conceal an earlier detected legacy/edited comment. Preserve the old issue and audit; resolve historical identity and consent through a separately reviewed migration or a new linked consented application. Do not edit a bot comment to manufacture provenance.

GitHub comments remain an operational audit: these checks cannot establish that no comment was deleted or modified in an undetectable way. Actual data recovery or migration requires separately authorized handling. Unit tests and the inactive policy do not appoint a reviewer or establish live capacity.
