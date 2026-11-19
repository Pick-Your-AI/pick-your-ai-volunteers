# Intake identity and authority v2

## Why the version changes

GitHub logins are display and routing labels. They are not the account identity used to authorize a decision. V2 binds the applicant, reviewers, audit actor and pending recipient to positive numeric GitHub account IDs. This prevents a rename from blocking withdrawal and prevents a reused login or reviewer alias from inheriting another account's mandate.

The authority file is now [data/authority.v2.json](../data/authority.v2.json), validated by [authority.v2.schema.json](../schemas/authority.v2.schema.json). Its `schema_version` is `2.0.0`; it remains disabled with no reviewers, routes or fallback appointments. The public directory and application schemas retain their v1 versions. The [decision command schema is v2](../schemas/decision.v2.schema.json): handoff resolutions now require the specific proposal ID. Research contracts and public exports are unaffected.

| Field | Meaning |
| --- | --- |
| Reviewer map key | Stable policy alias referenced by routes and escalation lists; never assigned as a GitHub login without identity resolution |
| `github_user_id` | Unique approved account ID attached to a reviewer mandate |
| `applicant_id` / `actor_id` | Account IDs from trusted GitHub issue/comment metadata |
| `reviewer_id` / `pending_reviewer_id` | Account identity bound when an assignment or handoff is proposed |
| `visited_ids` | Account identities already visited; aliases cannot evade loop prevention |
| `pending_proposal_id` / `pending_requester_id` | Trusted source comment ID and requester account ID for the pending proposal |
| `assignment_grant` | Initial scope-route grant or an approved continuing case handoff |
| `cursor` | Highest processed decision/recovery comment ID; replaces an ever-growing rejected-ID list |
| `ledger_version` | `2`, with the `volunteer-ledger:v2` comment marker |

Before an assignment, the runtime resolves the approved account through GitHub's [get-user-by-ID endpoint](https://docs.github.com/en/rest/users/users#get-a-user-using-their-id), verifies that the returned ID matches, and adds only its current safe login. Only the ID/login needed for this operation is used; profile/contact fields are not copied to ledger or Project records. This lookup is mocked in tests and has not been exercised live by this campaign.

## Consent and route selection

Initialization requires the explicit checked Visibility consent sentence and one allowed Referral preference from the generated form, taken from the trusted issue-opening event sent by that applicant or a fresh applicant-authored recovery comment. A later comment event never establishes consent from the issue body, because another actor could have edited it. Canonical interests are read only from the four Preferred sections. Mentioning an entity in skills, alternatives or another free-text section does not select it. Incomplete, duplicated, unknown or ambiguous fields produce a generic review failure before a ledger or assignee is written; they are not copied into an export.

An explicit Help/No preference choice may use the policy's approved global empty-route fallback. Absent preferences and `_No response_` stay unassigned. A named selected scope needs its own nonempty approved route; an absent or empty route is not permission to apply the global fallback. Multiple inconsistent routes require clarification. Stored consent and selections govern later commands so editing the issue body cannot silently change them or prevent withdrawal.

## Explicit recovery and withdrawal

If opening-event initialization was missed or the original form was incomplete, the applicant can post a **new, unedited comment** on the same issue starting with `/volunteer-apply` on its own line, followed by the desired Preferred sections, Referral preference and checked Visibility consent from the application form. The comment author must have the issue creator's numeric account ID. For example, the following confirms public review and an explicit absence of routing preference; it does not appoint a reviewer:

```text
/volunteer-apply
### Preferred team

No preference

### Referral preference

Do not refer me

### Visibility consent

- [x] I understand this is public and consent to public application review. Each proposed placement change needs my agreement.
```

Use exact generated dropdown labels to select named scopes instead. Recovery comments are limited to 8,192 characters; omit free-text material that is not needed to confirm consent and choices. Earlier rejected reviewer commands are not replayed as new approvals after recovery. An initialized application cannot be rerouted by editing its original body or posting another recovery comment.

An applicant can always submit a fresh `/volunteer {"action":"withdraw","reason":"I withdraw this application."}` command before successful form confirmation. This records a minimal terminal `withdrawal_only` ledger with `public_consent: false`, no selected scopes and no reviewer. It neither registers a consented application nor enters the public Project. A delayed opening event cannot reset it. A malformed existing trusted ledger still requires manual reconciliation rather than bypassing its history.

Project synchronization validates the ledger before any application Project write and requires both `initialized: true` and `public_consent: true`. Missing, edited, legacy, malformed or withdrawal-only ledgers are skipped with a generic operator signal where appropriate.

## Pending handoffs and invitation evidence

Applicant-requested reviewer escalation is available in each nonterminal application, accepted, onboarding, invitation and active lifecycle state. The current reviewer may be unavailable; a distinct currently authorized escalation approver is still required. Approval or rejection restores the original lifecycle state. A pending destination must retain both its approved account ID and the originating mandate's authorization at completion. Revocation blocks transfer; cancellation remains available under the documented applicant/approver rules.

Every resolution (`agree_referral`, `decline_referral`, `approve_escalation`, `reject_escalation`) requires `proposal_id` equal to the source comment ID recorded as `pending_proposal_id`. For example: `/volunteer {"action":"agree_referral","proposal_id":"12345","reason":"I agree to this specific proposed placement change."}`. Replace the example ID with the actual current proposal. An optional destination must also match. A delayed resolution for a canceled or superseded proposal cannot authorize its replacement. The applicant, original requester, current reviewer and prospective receiver cannot approve that escalation; applicants cannot exercise reviewer decision authority on their own case.

Initial assignments remain conditional on the current approved route for **every selected scope**, or the specifically approved empty-route fallback. Removing a selected scope's grant prevents subsequent reviewer decisions and pending transfers even if the same reviewer still has authority elsewhere. Applicant withdrawal and cancellation remain available.

A completed, consented referral or independently approved escalation creates an explicit continuing **case handoff grant**, recorded with its originating reviewer/account, action and proposal ID. The receiver does not need to become the initial route for that scope. The grant remains conditional on the receiver's current identity, action mandate and availability, plus the origin's current identity, approval, allowed handoff action and destination authorization. Revoking those conditions blocks further decisions. Changing only the original route does not erase an already approved case handoff. This interpretation separates ongoing case responsibility from new-application routing and is encoded in tests.

Commands validate scalar types and required per-action fields before changing state or adding audit history. Invitation records require a public HTTP(S) receipt reference. A recorded receipt is the operator's attestation; the workflow does not independently verify the invitation or contact the referenced site. Numeric IDs and boolean flags must have their declared types, not merely truthy values.

## Bounded audit entries

Each accepted command appends one state snapshot containing only that transition's audit entry. Earlier audit entries stay in their original comments. Rejected commands advance one numeric cursor checkpoint instead of growing a list of rejected IDs. The worker processes [GitHub issue comments in ascending ID order](https://docs.github.com/en/rest/issues/comments#list-issue-comments), and rejects a checkpoint that goes backwards. It never rewrites older audit comments. Consumers requiring full history must read all trusted ledger comments; the latest `history` array is only the latest delta, not the complete case history.

An entry is limited to 40,000 UTF-8 bytes before any write. Oversized proposed transitions are rejected without losing the ability to process later withdrawal. Terminal withdrawal clears routing selections and visited-recipient lists from its current snapshot; prior audit comments retain their history. Network/write failures stop the run rather than being misclassified as rejected commands. If a write may have succeeded before its response was lost, the next run reads the durable ledger and cursor before retrying.

Synthetic tests exercise 300 accepted review steps followed by withdrawal, 2,000 rejected commands followed by withdrawal, paginated comment reads and a lost POST response. These tests do not establish live throughput, rate-limit behavior or delivery guarantees. A large issue still requires paginated reads; API availability or execution limits can require a later retry or manual reconciliation.

## Historical data and migration

PR #1 was unmerged when v2 was introduced; this campaign performed no live ledger migration. The old policy remains available in Git history. An operator must not activate an old v1 policy or copy a login into `github_user_id`. Obtain an explicit reviewed mandate tied to the actual account ID, fresh availability, approved routes and response period before proposing an enabled v2 policy.

Trusted v1 ledger markers, missing v2 identity/consent/checkpoint metadata, mismatched applicant IDs or visibly edited audit comments stop processing for manual reconciliation. Pre-cursor v2 snapshots also require explicit migration; this unmerged campaign has performed none. Existing records are never silently reset to `new`, and a v2 comment cannot conceal an earlier detected legacy/edited comment. Preserve the old issue and audit; resolve historical identity and consent through a separately reviewed migration or a new linked consented application. Do not edit a bot comment to manufacture provenance.

GitHub comments remain an operational audit: these checks cannot establish that no comment was deleted or modified in an undetectable way. Actual data recovery or migration requires separately authorized handling. Unit tests and the inactive policy do not appoint a reviewer or establish live capacity.
