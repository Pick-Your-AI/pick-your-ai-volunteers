# Completing the volunteer program safely

This is the offline evidence packet for the opportunity issues and implementation PR. It is not a reviewer appointment, a staffing commitment or authorization to run live intake or Project synchronization. Recruiting remains paused and `data/authority.v2.json` remains disabled.

## Opportunity records

| Issue | Canonical opportunity | Missing operational evidence |
| --- | --- | --- |
| [#2](https://github.com/Pick-Your-AI/pick-your-ai-volunteers/issues/2) | `op-lead-maintainers-ai-builder` | Approved leadership mandate, receiving reviewer and capacity |
| [#3](https://github.com/Pick-Your-AI/pick-your-ai-volunteers/issues/3) | `op-lead-maintainers-ai-papers-index` | Approved leadership mandate, receiving reviewer and capacity |
| [#4](https://github.com/Pick-Your-AI/pick-your-ai-volunteers/issues/4) | `op-lead-maintainers-catalog-pipeline` | Approved leadership mandate, receiving reviewer and capacity |
| [#5](https://github.com/Pick-Your-AI/pick-your-ai-volunteers/issues/5) | `op-lead-maintainers-datasets-benchmarks` | Approved leadership mandate, receiving reviewer and capacity |
| [#6](https://github.com/Pick-Your-AI/pick-your-ai-volunteers/issues/6) | `op-education` | Confirmed recruiting need, bounded scope and receiving capacity |
| [#7](https://github.com/Pick-Your-AI/pick-your-ai-volunteers/issues/7) | `op-funding-grants-sustainability` | Confirmed recruiting need, bounded scope and receiving capacity; no financial authority is implied |
| [#8](https://github.com/Pick-Your-AI/pick-your-ai-volunteers/issues/8) | `op-organization-maintainers` | Confirmed recruiting need, bounded scope and receiving capacity; administrative access is not volunteer selection authority |

All seven stay open with `status:blocked` until evidence establishes their actual outcome. An implemented directory entry does not fill a position.

## Information to supply together

Organization governance must explicitly designate and approve volunteer authority. This repository does not establish which individual can make that decision. Each selected receiver must confirm their own availability and capacity. Use the existing [availability template](../.github/ISSUE_TEMPLATE/availability.yml) with the following public-safe facts; retain unknowns until confirmed:

| Field | Required evidence |
| --- | --- |
| Canonical opportunity ID | One of the exact stable IDs above |
| Role or task scope | Bounded responsibilities, success criteria and accepted operational ownership |
| Recruiting decision | Whether to recruit, with openings and time commitment if established |
| Receiving support | Approved reviewer alias and stable numeric `github_user_id`, onboarding owner, mentoring commitment and beginner suitability |
| Availability | Actual available/absent/conflict/unknown disposition and verification date |
| Authority | Approval reference, allowed actions and destination scope |
| Route | Ordered approved route, per-step references, explicit fallback and escalation approvers |
| Timing | Approved response period; no assumed response guarantee |

Do not submit personal contact information, sensitive support needs, member exports or private operational details. Public account identities required for an approved policy are separate from the synthetic identities used in tests.

After actual decisions, an authorized maintainer updates canonical `data/directory.v1.json` and, only with an activation decision, `data/authority.v2.json` through a reviewed PR. Generated forms and exports come from the generator:

```sh
python scripts/generate.py
python scripts/validate.py
python -m unittest discover -s tests -v
python scripts/generate.py --check
```

These commands validate proposed data and offline behavior; they cannot establish consent, availability, a filled opening or live delivery. Refresh expired source evidence with authorized source reads, rather than changing dates to pass validation. Actual invitations, access grants and Project writes require separate operational authorization.

## Integration gate

The active `Volunteer program: reviewed main` ruleset requires an up-to-date branch, successful `validate`, resolved review threads and eligible approval of the latest push. An independent agent review comment is engineering evidence; it does not satisfy a required approving vote from another eligible GitHub account. Do not bypass this gate or alter access under the guise of completing a code change.

Once those gates are met, a maintainer can merge PR #1 through the ordinary GitHub merge control, or with `gh pr merge 1 --repo Pick-Your-AI/pick-your-ai-volunteers --squash --match-head-commit <reviewed-head-sha>`. Then verify the resulting main commit's `validate` run. This is an unblock instruction, not a record of a merge having occurred.

The optional Project workflow needs a separately approved dedicated `VOLUNTEER_PROJECT_TOKEN`; this credential is unnecessary for the offline checks above and must never be included in an issue or commit. Live Project synchronization, Paseo UI acceptance, a new fresh-VM run and a website API are not established by this campaign's local checks.
