"""Synthetic consent provenance, revocation and bounded audit regressions."""
import contextlib
import copy
import io
import json
import unittest
from unittest.mock import patch

import github_intake
import project_sync
import test_intake as intake_fixtures

CONSENT = intake_fixtures.CONSENT


class ConsentRecovery(unittest.TestCase):
    def setUp(self):
        self.h = intake_fixtures.Intake(methodName='runTest')
        self.h.setUp()

    def tearDown(self):
        self.h.tearDown()

    def decision(self, number, action, actor='synthetic-applicant', **extra):
        c = self.h.command(number, action, actor)
        c['body'] = '/volunteer ' + json.dumps({'action': action, 'reason': 'Synthetic fixture', **extra})
        return c

    def recovery(self, number, body=None, actor='synthetic-applicant'):
        c = self.h.command(number, 'confirm', actor)
        c['body'] = github_intake.RECOVERY_PREFIX + (self.h.issue['body'] if body is None else body)
        return c

    def policy(self, transform):
        path = self.h.root / 'data/authority.v2.json'
        value = json.loads(path.read_text())
        transform(value)
        path.write_text(json.dumps(value))

    def test_later_issue_body_never_establishes_consent(self):
        self.h.active_policy()
        self.h.issue.update(created_at='2026-10-30T00:00:00Z', updated_at='2026-10-31T00:00:00Z')
        for actor in ('intruder', 'synthetic-reviewer-a', 'synthetic-applicant'):
            c = self.decision(len(self.h.comments) + 1, 'accept', actor)
            self.h.run_event(c)
        self.assertFalse(self.h.writes)
        self.assertEqual(self.h.assignees, {'synthetic-existing-owner'})

    def test_explicit_recovery_binds_applicant_comment_not_edited_issue(self):
        self.h.active_policy()
        confirmed = self.h.issue['body']
        c = self.recovery(10, confirmed)
        self.h.issue['body'] = '### Referral preference\n\nAsk me before each placement change\n\n' + CONSENT
        self.h.run_event(c)
        state = self.h.ledger()
        self.assertEqual(state['selections'], ['team-synthetic'])
        self.assertEqual(state['referral_preference'], 'do_not_refer')
        self.assertEqual(state['consent_source'], c['html_url'])
        self.assertEqual(state['cursor'], 10)

    def test_recovery_requires_fresh_same_account_and_explicit_consent(self):
        for variant in ('intruder', 'reused_login', 'edited', 'unchecked', 'ambiguous'):
            with self.subTest(variant=variant):
                self.h.comments = []
                c = self.recovery(11, actor='intruder' if variant == 'intruder' else 'synthetic-applicant')
                if variant == 'reused_login':
                    c['user']['id'] = 999
                elif variant == 'edited':
                    c['updated_at'] = '2026-10-31T00:00:00Z'
                elif variant == 'unchecked':
                    c['body'] = c['body'].replace('[x]', '[ ]')
                elif variant == 'ambiguous':
                    c['body'] += '\n\n' + CONSENT
                self.h.run_event(c)
                self.assertFalse(self.h.writes)

    def test_preconfirmation_withdrawal_needs_no_form_and_cannot_be_reset(self):
        self.h.issue['body'] = None
        c = self.decision(12, 'withdraw')
        self.h.run_event(c)
        state = self.h.ledger()
        self.assertEqual(state['state'], 'withdrawn')
        self.assertIs(state['public_consent'], False)
        self.assertIs(state['withdrawal_only'], True)
        self.assertIsNone(state['reviewer'])
        self.assertEqual(state['selections'], [])
        self.h.issue['body'] = '### Referral preference\n\nDo not refer me\n\n' + CONSENT
        self.h.run_event()
        self.h.run_event(self.recovery(13))
        self.assertEqual(self.h.ledger()['state'], 'withdrawn')
        self.assertEqual(self.h.assignees, {'synthetic-existing-owner'})

    def test_delayed_open_event_replays_existing_withdrawal(self):
        self.decision(14, 'withdraw')
        self.h.run_event()
        self.assertEqual(self.h.ledger()['state'], 'withdrawn')
        self.assertEqual(self.h.ledger()['cursor'], 14)

    def test_rejected_preconfirmation_decisions_do_not_replay_after_recovery(self):
        self.h.active_policy()
        bad = self.decision(15, 'accept', 'synthetic-reviewer-a')
        self.h.run_event(bad)
        self.assertFalse(self.h.writes)
        self.h.run_event(self.recovery(16))
        self.assertEqual(self.h.ledger()['state'], 'new')
        self.assertEqual(self.h.ledger()['cursor'], 16)
        self.h.run_event(bad)
        self.assertEqual(self.h.ledger()['state'], 'new')
        self.h.run_event(self.decision(17, 'accept', 'synthetic-reviewer-a'))
        self.assertEqual(self.h.ledger()['state'], 'accepted')

    def test_malformed_consent_or_preference_ledger_stops_before_writes(self):
        self.h.run_event()
        original = self.h.ledger()
        for field, value in [('public_consent', None), ('public_consent', False),
                             ('public_consent', 1), ('public_consent', 'true'),
                             ('referral_preference', None), ('referral_preference', 'unknown')]:
            with self.subTest(field=field, value=value):
                invalid = copy.deepcopy(original)
                if value is None:
                    invalid.pop(field)
                else:
                    invalid[field] = value
                self.h.comments[-1]['body'] = github_intake.MARKER + '\n' + json.dumps(invalid)
                count = len(self.h.writes)
                with self.assertRaisesRegex(ValueError, 'Ledger consent'):
                    self.h.run_event()
                self.assertEqual(len(self.h.writes), count)

    def test_checkpoint_cannot_be_missing_boolean_or_go_backwards(self):
        self.h.run_event()
        self.h.run_event(self.decision(20, 'accept', 'intruder'))
        original = self.h.ledger()
        for value in (None, True, -1):
            with self.subTest(value=value):
                invalid = copy.deepcopy(original)
                invalid['cursor'] = value
                self.h.comments[-1]['body'] = github_intake.MARKER + '\n' + json.dumps(invalid)
                with self.assertRaisesRegex(ValueError, 'Ledger checkpoint'):
                    self.h.run_event()

    def test_long_case_keeps_audit_entries_small_and_withdrawal_available(self):
        self.h.active_policy()
        self.policy(lambda p: p['reviewers']['synthetic-reviewer-a']['actions'].append('request_information'))
        self.h.run_event()
        for n in range(1, 301):
            self.decision(n, 'request_information', 'synthetic-reviewer-a', reason='x' * 500)
        self.h.run_event(self.h.comments[-1])
        self.h.run_event(self.decision(301, 'withdraw'))
        self.assertEqual(self.h.ledger()['state'], 'withdrawn')
        ledgers = [c for c in self.h.comments if c['body'].startswith(github_intake.MARKER)]
        history = [entry for c in ledgers for entry in json.loads(c['body'][len(github_intake.MARKER):])['history']]
        self.assertEqual(len(history), 301)
        self.assertEqual([entry['id'] for entry in history], [str(n) for n in range(1, 302)])
        self.assertLess(max(len(c['body'].encode()) for c in ledgers), 6000)
        count = len(self.h.writes)
        self.h.run_event(self.h.comments[-2])
        self.assertEqual(len(self.h.writes), count)

    def test_rejected_command_volume_uses_one_bounded_cursor_checkpoint(self):
        self.h.run_event()
        for n in range(10000, 12000):
            self.decision(n, 'accept', 'intruder')
        self.h.run_event(self.h.comments[-1])
        self.assertEqual(len(self.h.writes), 2)
        self.assertEqual(self.h.ledger()['cursor'], 11999)
        self.assertNotIn('processed', self.h.ledger())
        self.assertLess(len(self.h.comments[-1]['body']), 2000)
        self.h.run_event(self.decision(12000, 'withdraw'))
        self.assertEqual(self.h.ledger()['state'], 'withdrawn')
        count = len(self.h.writes)
        self.h.run_event(self.h.comments[-2])
        self.assertEqual(len(self.h.writes), count)

    def test_oversized_entry_is_not_sent_to_github(self):
        self.h.run_event()
        state = self.h.ledger()
        state['history'] = [{'reason': 'x' * github_intake.MAX_LEDGER_BYTES}]
        with patch.object(github_intake, 'api') as api, self.assertRaises(ValueError):
            github_intake.record_state('synthetic/repo', 1, state)
        api.assert_not_called()

    def test_lost_post_response_does_not_overwrite_a_committed_decision(self):
        self.h.run_event()
        command = self.decision(25, 'withdraw')
        original_api = self.h.api

        def lose_response(path, payload=None, method=None):
            result = original_api(path, payload, method)
            if payload is not None and path.endswith('/comments'):
                raise ValueError('Synthetic response decode failure after successful POST')
            return result

        with patch.object(self.h, 'api', lose_response), self.assertRaises(ValueError):
            self.h.run_event(command)
        self.assertEqual(self.h.ledger()['state'], 'withdrawn')
        self.assertEqual(self.h.ledger()['cursor'], 25)
        count = len(self.h.writes)
        self.h.run_event(command)
        self.assertEqual(len(self.h.writes), count)

    def test_revoked_initial_scope_cannot_decide_using_another_scope_mandate(self):
        self.h.active_policy()
        self.h.run_event()
        self.policy(lambda p: p['routes'].clear())
        self.h.run_event(self.decision(30, 'accept', 'synthetic-reviewer-a'))
        self.assertEqual(self.h.ledger()['state'], 'new')
        self.h.run_event(self.decision(31, 'withdraw'))
        self.assertEqual(self.h.ledger()['state'], 'withdrawn')

    def prepare_referral(self):
        self.h.active_policy()
        self.h.issue['body'] = self.h.issue['body'].replace('Do not refer me', 'Ask me before each placement change')
        self.h.run_event()
        self.h.run_event(self.decision(40, 'refer', 'synthetic-reviewer-a', destination='synthetic-reviewer-b'))

    def test_pending_transfer_stops_after_source_scope_revocation(self):
        self.prepare_referral()
        self.policy(lambda p: p['routes'].clear())
        self.h.run_event(self.decision(41, 'agree_referral', proposal_id='40'))
        self.assertEqual(self.h.ledger()['reviewer'], 'synthetic-reviewer-a')
        self.assertEqual(self.h.ledger()['state'], 'referral_pending')
        self.h.run_event(self.decision(42, 'decline_referral', proposal_id='40'))
        self.assertEqual(self.h.ledger()['state'], 'new')

    def test_completed_handoff_has_explicit_case_mandate_after_initial_route_changes(self):
        self.prepare_referral()
        self.h.run_event(self.decision(41, 'agree_referral', proposal_id='40'))
        self.policy(lambda p: p['routes'].clear())
        self.h.run_event(self.decision(42, 'accept', 'synthetic-reviewer-b'))
        self.assertEqual(self.h.ledger()['state'], 'accepted')
        self.assertEqual(self.h.ledger()['assignment_grant']['proposal_id'], '40')

    def test_revoked_case_handoff_mandate_blocks_recipient(self):
        self.prepare_referral()
        self.h.run_event(self.decision(41, 'agree_referral', proposal_id='40'))
        self.policy(lambda p: p['reviewers']['synthetic-reviewer-a']['destinations'].clear())
        self.h.run_event(self.decision(42, 'accept', 'synthetic-reviewer-b'))
        self.assertEqual(self.h.ledger()['state'], 'new')
        self.assertEqual(self.h.ledger()['reviewer'], 'synthetic-reviewer-b')


class ProjectConsentBoundary(unittest.TestCase):
    def sync(self, comments):
        writes = []
        issue = {'number': 1, 'user': {'login': 'synthetic-applicant', 'id': 101},
                 'labels': [{'name': 'type:application'}],
                 'html_url': 'https://github.com/synthetic/repo/issues/1'}

        def gh(*args):
            if args[:2] == ('project', 'field-list'):
                return {'fields': []}
            if args[0] == 'api':
                return [comments] if '/comments?' in args[-1] else [[issue]]
            writes.append(args)
            self.fail('Unconsented application caused a Project mutation')

        with patch.object(project_sync, 'gh', gh), contextlib.redirect_stdout(io.StringIO()):
            project_sync.main()
        self.assertEqual(writes, [])

    def test_absent_ledger_never_creates_project_item(self):
        self.sync([])

    def test_legacy_edited_or_unconsented_ledger_never_creates_project_item(self):
        fixture = intake_fixtures.Intake(methodName='runTest')
        fixture.setUp()
        try:
            fixture.run_event()
            valid = fixture.comments[-1]
            for variant in ('legacy', 'edited', 'missing_consent', 'false_consent', 'missing_preference'):
                with self.subTest(variant=variant):
                    comment = copy.deepcopy(valid)
                    state = json.loads(comment['body'][len(github_intake.MARKER):])
                    if variant == 'legacy':
                        comment['body'] = comment['body'].replace(github_intake.MARKER, github_intake.LEGACY_MARKER)
                    elif variant == 'edited':
                        comment['updated_at'] = '2026-10-31T00:00:00Z'
                    else:
                        if variant == 'missing_consent':
                            del state['public_consent']
                        elif variant == 'false_consent':
                            state['public_consent'] = False
                        else:
                            del state['referral_preference']
                        comment['body'] = github_intake.MARKER + '\n' + json.dumps(state)
                    self.sync([comment])
        finally:
            fixture.tearDown()

    def test_preconfirmation_withdrawal_is_not_registered_in_project(self):
        fixture = intake_fixtures.Intake(methodName='runTest')
        fixture.setUp()
        try:
            fixture.issue['body'] = None
            fixture.run_event(fixture.command(1, 'withdraw'))
            self.sync([fixture.comments[-1]])
        finally:
            fixture.tearDown()


if __name__ == '__main__':
    unittest.main()
