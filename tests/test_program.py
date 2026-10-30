"""Synthetic fixtures only: no actual applicants, reviewers or invitations."""
import copy
import json
from pathlib import Path
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from program import initial, transition, recommend, public_export, resolve_route
from github_intake import read_ledger, MARKER
from generate import artifacts

NOW = datetime(2026, 10, 30, tzinfo=timezone.utc)
ACTIONS = ['accept', 'decline', 'request_information', 'refer', 'request_escalation', 'approve_escalation', 'reject_escalation', 'begin_onboarding', 'request_invitation', 'record_invitation_sent', 'record_invitation_accepted', 'complete_onboarding', 'close']


def policy():
    return {'enabled': True, 'approval_reference': 'synthetic-test-only', 'fallbacks': {'empty': 'reviewer-a'}, 'reviewers': {a: {'availability': 'available', 'verified_at': NOW.isoformat(), 'approval_reference': 'synthetic-test-only', 'actions': ACTIONS, 'destinations': [x for x in ['reviewer-a', 'reviewer-b', 'reviewer-c'] if x != a], 'escalation_approvers': ['reviewer-c']} for a in ['reviewer-a', 'reviewer-b', 'reviewer-c']}}


def event(action, actor='reviewer-a', id=None, **extra):
    return {'action': action, 'actor': actor, 'id': id or action, 'at': NOW.isoformat(), 'source': 'synthetic-test-only', 'reason': 'Synthetic fixture', **extra}


class Decisions(unittest.TestCase):
    def setUp(self):
        self.p = policy()
        self.s = initial('applicant', 'reviewer-a')

    def move(self, action, actor='reviewer-a', **extra):
        self.s = transition(self.s, event(action, actor, **extra), self.p, NOW)
        return self.s

    def test_accept_does_not_grant_access(self):
        self.assertEqual(self.move('accept')['state'], 'accepted')
        self.assertEqual(self.move('begin_onboarding')['state'], 'onboarding')
        self.assertEqual(self.move('complete_onboarding')['state'], 'active')

    def test_separate_invitation_receipts(self):
        for a in ['accept', 'begin_onboarding', 'request_invitation']:
            self.move(a)
        with self.assertRaises(ValueError): self.move('record_invitation_sent')
        self.move('record_invitation_sent', receipt='https://github.com/example')
        self.move('record_invitation_accepted', receipt='https://github.com/example')
        self.assertEqual(self.move('complete_onboarding')['state'], 'active')

    def test_unauthorized(self):
        with self.assertRaises(ValueError): self.move('accept', actor='intruder')
        with self.assertRaises(ValueError): self.move('accept', actor='reviewer-b')

    def test_policy_disabled(self):
        self.p['enabled'] = False
        with self.assertRaises(ValueError): self.move('accept')

    def test_stale_absent_missing_reviewer(self):
        for value in ['absent', 'unknown', 'conflict']:
            self.p['reviewers']['reviewer-a']['availability'] = value
            with self.assertRaises(ValueError): self.move('accept')
        self.p['reviewers']['reviewer-a']['availability'] = 'available'
        self.p['reviewers']['reviewer-a']['verified_at'] = '2020-01-01T00:00:00+00:00'
        with self.assertRaises(ValueError): self.move('accept')
        del self.p['reviewers']['reviewer-a']
        with self.assertRaises(ValueError): self.move('accept')

    def test_empty_route_needs_approved_fallback(self):
        self.s = initial('applicant')
        self.assertEqual(self.move('accept')['reviewer'], 'reviewer-a')
        self.s = initial('applicant'); self.p['fallbacks'] = {}
        with self.assertRaises(ValueError): self.move('accept')

    def test_referral_requires_agreement_and_prevents_loop(self):
        self.move('refer', destination='reviewer-b')
        self.assertEqual(self.s['reviewer'], 'reviewer-a')
        with self.assertRaises(ValueError): self.move('agree_referral', actor='reviewer-b')
        self.move('agree_referral', actor='applicant')
        self.assertEqual(self.s['reviewer'], 'reviewer-b')
        with self.assertRaises(ValueError): self.move('refer', actor='reviewer-b', destination='reviewer-a', id='loop')

    def test_decline_referral(self):
        self.move('refer', destination='reviewer-b')
        self.assertEqual(self.move('decline_referral', actor='applicant')['reviewer'], 'reviewer-a')

    def test_opted_out_of_referral(self):
        self.s['referral_preference'] = 'do_not_refer'
        with self.assertRaises(ValueError): self.move('refer', destination='reviewer-b')

    def test_absent_reviewer_does_not_block_applicant_escalation_request(self):
        self.p['reviewers']['reviewer-a']['availability'] = 'absent'
        self.move('request_escalation', actor='applicant', destination='reviewer-b', unavailability='recorded_absence')
        self.assertEqual(self.move('approve_escalation', actor='reviewer-c')['reviewer'], 'reviewer-b')

    def test_escalation_never_self_approves(self):
        self.move('request_escalation', destination='reviewer-b', unavailability='response_period_expired')
        with self.assertRaises(ValueError): self.move('approve_escalation')
        self.assertEqual(self.s['reviewer'], 'reviewer-a')
        self.assertEqual(self.move('approve_escalation', actor='reviewer-c')['reviewer'], 'reviewer-b')

    def test_reject_escalation(self):
        self.move('request_escalation', destination='reviewer-b', unavailability='conflict_of_interest')
        self.assertEqual(self.move('reject_escalation', actor='reviewer-c')['reviewer'], 'reviewer-a')

    def test_escalation_requires_reason_and_allowed_destination(self):
        with self.assertRaises(ValueError): self.move('request_escalation', destination='reviewer-b')
        self.p['reviewers']['reviewer-a']['destinations'] = []
        with self.assertRaises(ValueError): self.move('refer', destination='reviewer-b')

    def test_withdraw_while_disabled(self):
        self.p['enabled'] = False
        self.assertEqual(self.move('withdraw', actor='applicant')['state'], 'withdrawn')
        with self.assertRaises(ValueError): self.move('accept')

    def test_cannot_withdraw_someone_else(self):
        with self.assertRaises(ValueError): self.move('withdraw')

    def test_duplicate_is_idempotent(self):
        self.move('accept'); before = copy.deepcopy(self.s)
        self.move('accept'); self.assertEqual(before, self.s)

    def test_audit_complete(self):
        self.move('accept')
        self.assertTrue({'previous', 'new', 'actor', 'at', 'reason', 'source', 'receiving_reviewer'} <= self.s['history'][0].keys())

    def test_invalid_transition(self):
        with self.assertRaises(ValueError): self.move('complete_onboarding')

    def test_spoofed_ledger_ignored(self):
        fake = {'user': {'login': 'intruder'}, 'body': MARKER + json.dumps({'state': 'active'})}
        self.assertEqual(read_ledger([fake], 'applicant')['state'], 'new')


class Directory(unittest.TestCase):
    def setUp(self):
        self.d = json.loads((Path(__file__).resolve().parents[1] / 'data/directory.v1.json').read_text(encoding='utf-8'))
        self.o = self.d['opportunities'][0]
        self.o.update(status='recruiting', verified_at=NOW.isoformat(), onboarding_capacity='confirmed', mentoring_capacity='confirmed', beginner_suitability='yes')

    def test_matching_reasons(self):
        found = recommend(self.d, [self.o['id']], ['review'], 10, True, NOW)
        self.assertEqual(found[0]['id'], self.o['id'])
        self.assertIn('Beginner-friendly', found[0]['reasons'])

    def test_capacity_stale_and_time_filters(self):
        self.o['mentoring_capacity'] = 'unknown'
        self.assertFalse(recommend(self.d, [], [], 10, True, NOW))
        self.o['mentoring_capacity'] = 'confirmed'; self.o['minimum_hours'] = 20
        self.assertFalse(recommend(self.d, [], [], 10, True, NOW))
        self.o['minimum_hours'] = None; self.o['verified_at'] = '2020-01-01T00:00:00+00:00'
        self.assertFalse(recommend(self.d, [], [], 10, True, NOW))

    def test_high_need_without_onboarding_not_recommended(self):
        self.o['onboarding_capacity'] = 'unknown'
        self.assertFalse(recommend(self.d, [], [], now=NOW))

    def test_public_export_drops_applications(self):
        self.d['applications'] = [{'private': 'must not export'}]
        self.assertNotIn('applications', public_export(self.d))

    def test_form_options_match_records(self):
        forms = artifacts(self.d)
        self.assertIn(self.o['id'], forms['.github/ISSUE_TEMPLATE/application.yml'])
        self.assertNotIn('must not export', forms['public/directory.v1.json'])

    def test_route_resolution_requires_explicit_fallback_approval(self):
        p = policy()
        p['reviewers']['reviewer-a']['availability'] = 'absent'
        route = [{'role': 'team_reviewer', 'reviewer': 'reviewer-a', 'approval_reference': 'synthetic'}, {'role': 'repository_maintainer', 'reviewer': 'reviewer-b', 'approval_reference': 'synthetic', 'fallback_approved': False}]
        p['routes'] = {self.o['id']: route}
        self.assertIsNone(resolve_route(self.d, p, [self.o['id']], NOW)[0])
        route[1]['fallback_approved'] = True
        self.assertEqual(resolve_route(self.d, p, [self.o['id']], NOW)[0], 'reviewer-b')

    def test_route_resolution_empty_and_ambiguous(self):
        p = policy()
        self.assertEqual(resolve_route(self.d, p, [], NOW)[0], 'reviewer-a')
        p['fallbacks'] = {}
        self.assertIsNone(resolve_route(self.d, p, [], NOW)[0])
        p['routes'] = {self.o['id']: [{'reviewer': 'reviewer-a'}], self.d['teams'][0]['id']: [{'reviewer': 'reviewer-b'}]}
        self.assertIsNone(resolve_route(self.d, p, list(p['routes']), NOW)[0])


if __name__ == '__main__':
    unittest.main()
