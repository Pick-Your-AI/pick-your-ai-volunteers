"""Independent, offline acceptance tests for stable identity and consented handoffs.

All actors, account IDs, routes and references below are synthetic.  Tests use
only the public program API and do not call GitHub or send invitations.
"""

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import program


NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
REFERENCE = "https://github.com/synthetic/repo/issues/1#issuecomment-1"
APPLICANT = "applicant-synthetic"
PRIMARY = "reviewer-synthetic-a"
TARGET = "reviewer-synthetic-b"
APPROVER = "reviewer-synthetic-c"
ACTIONS = [
    "accept", "decline", "request_information", "refer", "agree_referral",
    "decline_referral", "request_escalation", "approve_escalation",
    "reject_escalation", "withdraw", "begin_onboarding", "request_invitation",
    "record_invitation_sent", "record_invitation_accepted",
    "complete_onboarding", "close",
]


def directory():
    return {
        "teams": [{"id": "team-synthetic"}, {"id": "team-synthetic-other"}],
        "repositories": [], "projects": [], "opportunities": [],
    }


def enabled_policy():
    reviewers = {}
    for alias, account_id in ((PRIMARY, 201), (TARGET, 202), (APPROVER, 203)):
        reviewers[alias] = {
            "github_user_id": account_id,
            "availability": "available",
            "verified_at": NOW.isoformat(),
            "approval_reference": REFERENCE,
            "actions": list(ACTIONS),
            "destinations": [TARGET],
            "escalation_approvers": [APPROVER],
        }
    return {
        "enabled": True,
        "approval_reference": REFERENCE,
        "fallbacks": {"empty": PRIMARY},
        "routes": {
            "team-synthetic": [{
                "role": "team_reviewer", "reviewer": PRIMARY,
                "approval_reference": REFERENCE,
            }],
        },
        "reviewers": reviewers,
    }


class IdentityHandoffAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.policy = enabled_policy()
        self.event_number = 0

    def initial(self, reviewer=PRIMARY, reviewer_id=201):
        return program.initial(
            APPLICANT, reviewer, applicant_id=101, reviewer_id=reviewer_id,
        )

    def event(self, action, actor=PRIMARY, actor_id=201, **extra):
        self.event_number += 1
        return {
            "id": f"synthetic-event-{self.event_number}",
            "actor": actor, "actor_id": actor_id,
            "at": NOW.isoformat(), "source": REFERENCE,
            "action": action, "reason": "Synthetic acceptance test.",
            **extra,
        }

    def apply(self, state, action, actor=PRIMARY, actor_id=201, policy=None, **extra):
        return program.transition(
            state, self.event(action, actor, actor_id, **extra),
            self.policy if policy is None else policy, now=NOW,
            directory=directory(),
        )

    def assert_rejected(self, state, action, actor=PRIMARY, actor_id=201,
                        policy=None, **extra):
        before = deepcopy(state)
        with self.assertRaises(ValueError):
            self.apply(state, action, actor, actor_id, policy, **extra)
        self.assertEqual(state, before, "Rejected commands must not mutate their input")

    def resolve(self, state, action, actor, actor_id, **extra):
        return self.apply(
            state, action, actor, actor_id,
            proposal_id=state["pending_proposal_id"], **extra,
        )

    def assert_resolution_rejected(self, state, action, actor, actor_id, **extra):
        self.assert_rejected(
            state, action, actor, actor_id,
            proposal_id=state["pending_proposal_id"], **extra,
        )

    def lifecycle(self, name):
        """Reach a lifecycle state through commands rather than editing history."""
        state = self.initial()
        if name == "new":
            return state
        state = self.apply(state, "accept")
        self.assertEqual(state["state"], "accepted")
        if name == "accepted":
            return state
        state = self.apply(state, "begin_onboarding")
        self.assertEqual(state["state"], "onboarding")
        if name == "onboarding":
            return state
        if name == "active":
            state = self.apply(state, "complete_onboarding")
            self.assertEqual(state["state"], "active")
            return state
        state = self.apply(state, "request_invitation")
        self.assertEqual(state["state"], "invitation_requested")
        if name == "invitation_requested":
            return state
        state = self.apply(state, "record_invitation_sent", receipt=REFERENCE)
        self.assertEqual(state["state"], "invitation_sent")
        if name == "invitation_sent":
            return state
        state = self.apply(state, "record_invitation_accepted", receipt=REFERENCE)
        self.assertEqual(state["state"], "invitation_accepted")
        self.assertEqual(name, "invitation_accepted")
        return state

    def pending(self, kind, origin="active"):
        state = self.lifecycle(origin)
        return self.propose(state, kind)

    def propose(self, state, kind, actor=APPLICANT, actor_id=101):
        if kind == "referral":
            event = self.event("refer", destination=TARGET)
        else:
            self.policy["reviewers"][PRIMARY]["availability"] = "absent"
            event = self.event(
                "request_escalation", actor, actor_id,
                destination=TARGET, unavailability="recorded_absence",
            )
        origin = state["state"]
        state = program.transition(state, event, self.policy, now=NOW, directory=directory())
        if kind == "referral":
            self.assertEqual(state["state"], "referral_pending")
        else:
            self.assertNotEqual(state["state"], origin)
        self.assertEqual(state["reviewer"], PRIMARY)
        self.assertEqual(state["pending_proposal_id"], event["id"])
        self.assertEqual(state["pending_requester_id"], event["actor_id"])
        return state

    def test_renamed_applicant_can_withdraw_while_policy_disabled(self):
        result = self.apply(
            self.initial(), "withdraw", "renamed-applicant-synthetic", 101,
            policy={"enabled": False},
        )
        self.assertEqual(result["state"], "withdrawn")

    def test_recycled_applicant_login_cannot_withdraw(self):
        self.assert_rejected(
            self.initial(), "withdraw", APPLICANT, 999,
            policy={"enabled": False},
        )

    def test_renamed_reviewer_keeps_account_mandate(self):
        result = self.apply(self.initial(), "accept", "renamed-reviewer-synthetic", 201)
        self.assertEqual(result["state"], "accepted")
        self.assertEqual(result["reviewer"], PRIMARY)

    def test_recycled_reviewer_alias_cannot_inherit_assignment(self):
        state = self.initial()
        self.policy["reviewers"][PRIMARY]["github_user_id"] = 202
        self.assert_rejected(state, "accept", PRIMARY, 202)

    def test_former_account_cannot_use_revoked_alias_mandate(self):
        state = self.initial()
        self.policy["reviewers"][PRIMARY]["github_user_id"] = 202
        self.assert_rejected(state, "accept", PRIMARY, 201)

    def test_referral_target_can_act_after_its_login_changes(self):
        state = self.pending("referral", "new")
        state = self.resolve(state, "agree_referral", "renamed-applicant-synthetic", 101)
        self.assertEqual(state["state"], "new")
        self.assertEqual(state["reviewer"], TARGET)
        state = self.apply(state, "accept", "renamed-target-synthetic", 202)
        self.assertEqual(state["state"], "accepted")

    def test_referral_agreement_rechecks_origin_destination_authorization(self):
        state = self.pending("referral")
        self.policy["reviewers"][PRIMARY]["destinations"] = []
        self.assert_resolution_rejected(state, "agree_referral", APPLICANT, 101)

    def test_referral_agreement_rejects_replacement_target_account(self):
        state = self.pending("referral")
        self.policy["reviewers"][TARGET]["github_user_id"] = 203
        self.assert_resolution_rejected(state, "agree_referral", APPLICANT, 101)

    def test_applicant_can_decline_referral_after_destination_revocation(self):
        state = self.pending("referral")
        self.policy["reviewers"][PRIMARY]["destinations"] = []
        self.policy["reviewers"][TARGET]["github_user_id"] = 203
        state = self.resolve(state, "decline_referral", APPLICANT, 101)
        self.assertEqual(state["state"], "active")
        self.assertEqual(state["reviewer"], PRIMARY)

    def test_escalation_approval_rechecks_origin_destination_authorization(self):
        state = self.pending("escalation")
        self.policy["reviewers"][PRIMARY]["destinations"] = []
        self.assert_resolution_rejected(state, "approve_escalation", APPROVER, 203)

    def test_escalation_approval_rejects_replacement_target_account(self):
        state = self.pending("escalation")
        self.policy["reviewers"][TARGET]["github_user_id"] = 201
        self.assert_resolution_rejected(state, "approve_escalation", APPROVER, 203)

    def test_escalation_rejection_restores_origin_after_target_revocation(self):
        state = self.pending("escalation")
        self.policy["reviewers"][PRIMARY]["destinations"] = []
        self.policy["reviewers"][TARGET]["github_user_id"] = 201
        state = self.resolve(state, "reject_escalation", APPROVER, 203)
        self.assertEqual(state["state"], "active")
        self.assertEqual(state["reviewer"], PRIMARY)

    def test_escalation_restores_every_existing_placement_lifecycle(self):
        for origin in (
            "accepted", "onboarding", "invitation_requested", "invitation_sent",
            "invitation_accepted", "active",
        ):
            with self.subTest(origin=origin):
                self.policy = enabled_policy()
                state = self.pending("escalation", origin)
                state = self.resolve(state, "approve_escalation", "renamed-approver-synthetic", 203)
                self.assertEqual(state["state"], origin)
                self.assertEqual(state["reviewer"], TARGET)

    def test_escalation_approver_must_be_distinct_from_target(self):
        state = self.pending("escalation", "new")
        self.policy["reviewers"][PRIMARY]["escalation_approvers"] = [TARGET]
        self.assert_resolution_rejected(state, "approve_escalation", TARGET, 202)

    def test_new_application_escalation_does_not_accept_applicant(self):
        state = self.pending("escalation", "new")
        state = self.resolve(state, "approve_escalation", APPROVER, 203)
        self.assertEqual(state["state"], "new")
        self.assertEqual(state["reviewer"], TARGET)

    def test_every_resolution_requires_the_exact_current_proposal_string(self):
        for kind, actions, actor, actor_id in (
            ("referral", ("agree_referral", "decline_referral"), APPLICANT, 101),
            ("escalation", ("approve_escalation", "reject_escalation"), APPROVER, 203),
        ):
            self.policy = enabled_policy()
            state = self.pending(kind, "new")
            wrong_ids = (
                {}, {"proposal_id": "synthetic-unrelated-proposal"},
                {"proposal_id": state["pending_proposal_id"] + " "},
                {"proposal_id": None}, {"proposal_id": True},
                {"proposal_id": 1}, {"proposal_id": []}, {"proposal_id": {}},
            )
            for action in actions:
                for fields in wrong_ids:
                    with self.subTest(kind=kind, action=action, fields=fields):
                        self.assert_rejected(state, action, actor, actor_id, **fields)

    def test_every_resolution_rejects_a_mismatched_optional_destination(self):
        for kind, actions, actor, actor_id in (
            ("referral", ("agree_referral", "decline_referral"), APPLICANT, 101),
            ("escalation", ("approve_escalation", "reject_escalation"), APPROVER, 203),
        ):
            self.policy = enabled_policy()
            state = self.pending(kind, "new")
            for action in actions:
                with self.subTest(kind=kind, action=action):
                    self.assert_resolution_rejected(
                        state, action, actor, actor_id, destination=PRIMARY,
                    )

    def test_matching_optional_destination_resolves_each_handoff_action(self):
        for kind, action, actor, actor_id, reviewer in (
            ("referral", "agree_referral", APPLICANT, 101, TARGET),
            ("referral", "decline_referral", APPLICANT, 101, PRIMARY),
            ("escalation", "approve_escalation", APPROVER, 203, TARGET),
            ("escalation", "reject_escalation", APPROVER, 203, PRIMARY),
        ):
            with self.subTest(action=action):
                self.policy = enabled_policy()
                state = self.pending(kind, "active")
                state = self.resolve(state, action, actor, actor_id, destination=TARGET)
                self.assertEqual(state["state"], "active")
                self.assertEqual(state["reviewer"], reviewer)

    def test_cancelled_proposal_cannot_resolve_a_later_request_to_same_recipient(self):
        for kind, cancel, actions, actor, actor_id in (
            ("referral", "decline_referral", ("agree_referral", "decline_referral"), APPLICANT, 101),
            ("escalation", "reject_escalation", ("approve_escalation", "reject_escalation"), APPROVER, 203),
        ):
            self.policy = enabled_policy()
            state = self.pending(kind, "active")
            cancelled_id = state["pending_proposal_id"]
            state = self.resolve(state, cancel, actor, actor_id)
            self.assertEqual(state["state"], "active")
            self.assertEqual(state["reviewer"], PRIMARY)
            state = self.propose(state, kind)
            self.assertNotEqual(state["pending_proposal_id"], cancelled_id)
            for action in actions:
                with self.subTest(kind=kind, action=action):
                    self.assert_rejected(
                        state, action, actor, actor_id,
                        proposal_id=cancelled_id, destination=TARGET,
                    )

    def test_applicant_requester_cannot_approve_even_with_separate_reviewer_mandate(self):
        state = program.initial(APPLICANT, PRIMARY, applicant_id=203, reviewer_id=201)
        state = self.propose(state, "escalation", APPLICANT, 203)
        self.assertEqual(state["pending_requester_id"], 203)
        for action in ("approve_escalation", "reject_escalation"):
            with self.subTest(action=action):
                self.assert_resolution_rejected(
                    state, action, "renamed-approver-synthetic", 203,
                )

    def test_current_reviewer_cannot_approve_own_replacement_with_named_mandate(self):
        state = self.pending("escalation", "new")
        self.policy["reviewers"][PRIMARY]["availability"] = "available"
        self.policy["reviewers"][PRIMARY]["escalation_approvers"] = [PRIMARY, APPROVER]
        self.assert_resolution_rejected(state, "approve_escalation", PRIMARY, 201)

    def test_reviewer_decisions_on_own_application_fail_in_each_lifecycle(self):
        for origin, action, fields in (
            ("new", "accept", {}),
            ("new", "decline", {}),
            ("new", "request_information", {}),
            ("new", "refer", {"destination": TARGET}),
            ("accepted", "begin_onboarding", {}),
            ("onboarding", "request_invitation", {}),
            ("invitation_requested", "record_invitation_sent", {"receipt": REFERENCE}),
            ("invitation_sent", "record_invitation_accepted", {"receipt": REFERENCE}),
            ("onboarding", "complete_onboarding", {}),
            ("active", "close", {}),
        ):
            with self.subTest(origin=origin, action=action):
                state = self.lifecycle(origin)
                control = self.apply(deepcopy(state), action, **fields)
                self.assertNotEqual(control, state, "Control decision must be otherwise valid")
                # A pre-existing ledger can belong to the assigned reviewer's
                # account; this fixture preserves its lifecycle and assignment.
                state["applicant_id"] = 201
                state["applicant"] = PRIMARY
                self.assert_rejected(state, action, PRIMARY, 201, **fields)

    def test_self_reviewer_applicant_can_still_withdraw(self):
        state = program.initial(PRIMARY, PRIMARY, applicant_id=201, reviewer_id=201)
        state = self.apply(state, "withdraw", PRIMARY, 201, policy={"enabled": False})
        self.assertEqual(state["state"], "withdrawn")

    def test_self_reviewer_applicant_can_request_unavailable_reviewer_escalation(self):
        state = program.initial(PRIMARY, PRIMARY, applicant_id=201, reviewer_id=201)
        state = self.propose(state, "escalation", "renamed-primary-synthetic", 201)
        self.assertEqual(state["pending_requester_id"], 201)
        state = self.resolve(state, "approve_escalation", APPROVER, 203)
        self.assertEqual(state["state"], "new")
        self.assertEqual(state["reviewer"], TARGET)

    def test_applicant_with_target_reviewer_mandate_can_agree_or_decline_referral(self):
        for action, expected in (("agree_referral", TARGET), ("decline_referral", PRIMARY)):
            with self.subTest(action=action):
                state = program.initial(APPLICANT, PRIMARY, applicant_id=202, reviewer_id=201)
                state = self.propose(state, "referral")
                state = self.resolve(state, action, "renamed-target-synthetic", 202)
                self.assertEqual(state["state"], "new")
                self.assertEqual(state["reviewer"], expected)

    def test_referral_requires_explicit_ask_each_time_preference(self):
        for preference in (None, "unknown", "always", "", True, [], {}):
            with self.subTest(preference=preference):
                state = self.initial()
                state["referral_preference"] = preference
                self.assert_rejected(state, "refer", destination=TARGET)
        state = self.initial()
        del state["referral_preference"]
        self.assert_rejected(state, "refer", destination=TARGET)

    def test_missing_selected_routes_do_not_use_global_empty_fallback(self):
        cases = (
            ({}, ["team-synthetic"]),
            (deepcopy(self.policy["routes"]), ["team-synthetic", "team-synthetic-other"]),
            ({"team-synthetic": []}, ["team-synthetic"]),
        )
        for routes, selections in cases:
            with self.subTest(routes=routes, selections=selections):
                self.policy["routes"] = routes
                reviewer, _ = program.resolve_route(directory(), self.policy, selections, now=NOW)
                self.assertIsNone(reviewer)

    def test_genuinely_unselected_application_uses_approved_empty_fallback(self):
        reviewer, _ = program.resolve_route(directory(), self.policy, [], now=NOW)
        self.assertEqual(reviewer, PRIMARY)

    def test_invitation_receipts_require_public_http_reference_strings(self):
        invalid_receipts = (
            True, False, [], [REFERENCE], {}, {"url": REFERENCE}, None, 123,
            "", "synthetic-receipt", "file:///tmp/synthetic-receipt",
            "javascript:synthetic", "mailto:synthetic@example.invalid",
            "https://", "ftp://example.invalid/synthetic",
        )
        for origin, action in (
            ("invitation_requested", "record_invitation_sent"),
            ("invitation_sent", "record_invitation_accepted"),
        ):
            state = self.lifecycle(origin)
            for receipt in invalid_receipts:
                with self.subTest(origin=origin, receipt=receipt):
                    self.assert_rejected(state, action, receipt=receipt)

    def test_public_https_receipts_record_manual_invitation_attestations(self):
        state = self.lifecycle("invitation_requested")
        state = self.apply(state, "record_invitation_sent", receipt=REFERENCE)
        self.assertEqual(state["state"], "invitation_sent")
        self.assertEqual(state["history"][-1]["receipt"], REFERENCE)
        state = self.apply(state, "record_invitation_accepted", receipt=REFERENCE)
        self.assertEqual(state["state"], "invitation_accepted")
        self.assertEqual(state["history"][-1]["receipt"], REFERENCE)

    def test_invalid_initial_account_ids_fail_closed(self):
        for field, values in (
            ("applicant_id", (None, True, False, 0, -1, "101", [], {})),
            ("reviewer_id", (True, False, 0, -1, "201", [], {})),
        ):
            for value in values:
                with self.subTest(field=field, value=value):
                    kwargs = {"applicant_id": 101, "reviewer_id": 201, field: value}
                    with self.assertRaises(ValueError):
                        program.initial(APPLICANT, PRIMARY, **kwargs)

    def test_unknown_and_boolean_event_account_ids_fail_closed(self):
        for actor_id in (None, True, False, 0, -1, "101", [], {}):
            with self.subTest(actor_id=actor_id):
                self.assert_rejected(self.initial(), "withdraw", APPLICANT, actor_id)
        state = self.initial()
        event = self.event("withdraw", APPLICANT, 101)
        del event["actor_id"]
        before = deepcopy(state)
        with self.assertRaises(ValueError):
            program.transition(state, event, self.policy, now=NOW)
        self.assertEqual(state, before)

    def test_unknown_and_boolean_policy_account_ids_cannot_authorize_review(self):
        for reviewer_id in (None, True, False, 0, -1, "201", [], {}):
            with self.subTest(reviewer_id=reviewer_id):
                self.policy = enabled_policy()
                self.policy["reviewers"][PRIMARY]["github_user_id"] = reviewer_id
                self.assert_rejected(self.initial(), "accept")

    def test_unassigned_rerouting_requires_explicit_initialization_and_selections(self):
        cases = (
            {},
            {"initialized": True},
            {"initialized": False, "selections": ["team-synthetic"]},
            {"initialized": "true", "selections": ["team-synthetic"]},
            {"initialized": 1, "selections": ["team-synthetic"]},
            {"initialized": True, "selections": None},
            {"initialized": True, "selections": "team-synthetic"},
            {"initialized": True, "selections": {"team-synthetic": True}},
            {"initialized": True, "selections": []},
            {"initialized": True, "selections": [], "allow_empty_route": False},
            {"initialized": True, "selections": [], "allow_empty_route": "true"},
            {"initialized": True, "selections": ["team-synthetic-other"], "allow_empty_route": True},
        )
        for metadata in cases:
            with self.subTest(metadata=metadata):
                state = self.initial(None, None)
                state.update(metadata)
                self.assert_rejected(state, "accept")

    def test_initialized_unassigned_canonical_selection_can_route(self):
        state = self.initial(None, None)
        state.update(initialized=True, selections=["team-synthetic"])
        state = self.apply(state, "accept")
        self.assertEqual(state["state"], "accepted")
        self.assertEqual(state["reviewer"], PRIMARY)

    def test_deliberate_empty_unassigned_selection_can_use_explicit_fallback(self):
        state = self.initial(None, None)
        state.update(initialized=True, selections=[], allow_empty_route=True)
        state = self.apply(state, "accept")
        self.assertEqual(state["state"], "accepted")
        self.assertEqual(state["reviewer"], PRIMARY)


if __name__ == "__main__":
    unittest.main()
