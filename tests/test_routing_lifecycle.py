"""Regressions for unresolved routing and placement-preserving handoffs."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from program import initial, resolve_route, transition
from test_program import NOW, event, policy


class RoutingGuards(unittest.TestCase):
    def setUp(self):
        self.directory = json.loads((Path(__file__).resolve().parents[1] /
                                     'data/directory.v1.json').read_text())
        self.scope = self.directory['opportunities'][0]['id']
        self.policy = policy()

    def route(self, reviewer):
        return [{'role': 'team_reviewer', 'reviewer': reviewer,
                 'approval_reference': 'synthetic-test-only'}]

    def assert_unassigned_cannot_be_claimed(self, selections):
        reviewer, _ = resolve_route(self.directory, self.policy, selections, NOW)
        self.assertIsNone(reviewer)
        state = initial('applicant', reviewer)
        state.update(initialized=True, selections=selections)
        with self.assertRaises(ValueError):
            transition(state, event('accept'), self.policy, NOW, directory=self.directory)
        self.assertEqual(state['state'], 'new')
        self.assertIsNone(state['reviewer'])

    def test_unavailable_nonempty_route_cannot_use_empty_fallback(self):
        self.policy['routes'] = {self.scope: self.route('reviewer-b')}
        self.policy['reviewers']['reviewer-b']['availability'] = 'absent'
        self.assert_unassigned_cannot_be_claimed([self.scope])

    def test_conflicting_routes_cannot_use_empty_fallback(self):
        other = self.directory['teams'][0]['id']
        self.policy['routes'] = {self.scope: self.route('reviewer-a'),
                                 other: self.route('reviewer-b')}
        self.assert_unassigned_cannot_be_claimed([self.scope, other])

    def test_partial_route_does_not_silently_drop_selected_scope(self):
        other = self.directory['teams'][0]['id']
        self.policy['routes'] = {self.scope: self.route('reviewer-a')}
        self.assert_unassigned_cannot_be_claimed([self.scope, other])

    def test_missing_routing_context_cannot_be_claimed(self):
        with self.assertRaises(ValueError):
            transition(initial('applicant'), event('accept'), self.policy, NOW)

    def test_resolved_empty_route_still_accepts_with_explicit_fallback(self):
        reviewer, _ = resolve_route(self.directory, self.policy, [], NOW)
        self.assertEqual(reviewer, 'reviewer-a')
        state = transition(initial('applicant', reviewer), event('accept'),
                           self.policy, NOW)
        self.assertEqual(state['state'], 'accepted')


class PlacementHandoffs(unittest.TestCase):
    def setUp(self):
        self.policy = policy()
        self.active = initial('applicant', 'reviewer-a')
        for action in ('accept', 'begin_onboarding', 'complete_onboarding'):
            self.active = transition(self.active, event(action), self.policy, NOW)

    def escalate(self, state):
        return transition(state, event('request_escalation', destination='reviewer-b',
                          unavailability='conflict_of_interest'), self.policy, NOW)

    def test_escalation_approval_preserves_active_placement_and_close(self):
        state = self.escalate(self.active)
        state = transition(state, event('approve_escalation', actor='reviewer-c'),
                           self.policy, NOW)
        self.assertEqual((state['state'], state['reviewer']), ('active', 'reviewer-b'))
        self.assertIsNone(state['pending'])
        self.assertEqual(transition(state, event('close', actor='reviewer-b'),
                                    self.policy, NOW)['state'], 'closed')

    def test_escalation_rejection_preserves_active_placement_and_close(self):
        state = self.escalate(self.active)
        state = transition(state, event('reject_escalation', actor='reviewer-c'),
                           self.policy, NOW)
        self.assertEqual((state['state'], state['reviewer']), ('active', 'reviewer-a'))
        self.assertEqual(transition(state, event('close'), self.policy, NOW)['state'],
                         'closed')

    def test_referral_decision_preserves_active_placement(self):
        for action, reviewer in [('agree_referral', 'reviewer-b'),
                                 ('decline_referral', 'reviewer-a')]:
            with self.subTest(action=action):
                state = transition(self.active, event('refer', destination='reviewer-b'),
                                   self.policy, NOW)
                state = transition(state, event(action, actor='applicant'),
                                   self.policy, NOW)
                self.assertEqual((state['state'], state['reviewer']), ('active', reviewer))
                self.assertIsNone(state['pending'])

    def test_rejected_escalation_restores_each_application_state(self):
        for original in ('new', 'awaiting_information', 'awaiting_reviewer'):
            with self.subTest(original=original):
                before = initial('applicant', 'reviewer-a')
                before['state'] = original
                pending = self.escalate(before)
                restored = transition(pending, event('reject_escalation', actor='reviewer-c'),
                                      self.policy, NOW)
                self.assertEqual(restored['state'], original)

    def test_pending_state_without_origin_cannot_change_placement(self):
        pending = self.escalate(self.active)
        pending.pop('pending_origin', None)
        before = copy.deepcopy(pending)
        with self.assertRaises(ValueError):
            transition(pending, event('approve_escalation', actor='reviewer-c'),
                       self.policy, NOW)
        self.assertEqual(pending, before)


if __name__ == '__main__':
    unittest.main()
