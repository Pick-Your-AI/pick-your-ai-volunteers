"""Controlled GitHub transport fixtures; no network requests or real volunteers."""
import contextlib
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import github_intake


class Intake(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'data').mkdir()
        (self.root / 'data/authority.v1.json').write_text(json.dumps({'enabled': False, 'approval_reference': None, 'reviewers': {}, 'fallbacks': {}}))
        (self.root / 'data/directory.v1.json').write_text(json.dumps({k: [] for k in ('teams', 'repositories', 'projects', 'opportunities')}))
        self.issue = {'number': 1, 'user': {'login': 'synthetic-applicant'}, 'labels': [{'name': 'type:application'}], 'body': '### Referral preference\n\nDo not refer me'}
        self.comments = []
        self.writes = []
        self.assignees = {'synthetic-existing-owner'}

    def tearDown(self):
        self.tmp.cleanup()

    def api(self, path, payload=None, method=None):
        if payload is None:
            return self.comments[:]
        self.writes.append((path, payload))
        if path.endswith('/comments'):
            self.comments.append({'id': 1000 + len(self.writes), 'user': {'login': 'github-actions[bot]', 'type': 'Bot'}, 'performed_via_github_app': {'slug': 'github-actions'}, 'body': payload['body'], 'created_at': '2026-10-30T00:00:00Z', 'updated_at': '2026-10-30T00:00:00Z'})
        elif path.endswith('/assignees'):
            self.assertEqual(method, 'POST')
            self.assignees.update(payload['assignees'])
        else:
            self.fail('Unexpected write endpoint')
        return {}

    def run_event(self, comment=None):
        event = {'issue': self.issue}
        if comment:
            event['comment'] = comment
        p = self.root / 'event.json'
        p.write_text(json.dumps(event))
        with patch.object(github_intake, 'ROOT', self.root), patch.object(github_intake, 'api', self.api), patch.dict(os.environ, {'GITHUB_EVENT_PATH': str(p), 'GITHUB_REPOSITORY': 'synthetic/repo'}), contextlib.redirect_stdout(io.StringIO()) as output:
            github_intake.run()
        return output.getvalue()

    def command(self, id, action, actor='synthetic-applicant'):
        c = {'id': id, 'user': {'login': actor, 'type': 'User'}, 'body': '/volunteer ' + json.dumps({'action': action, 'reason': 'Synthetic fixture'}), 'created_at': '2026-10-30T00:00:00Z', 'updated_at': '2026-10-30T00:00:00Z', 'html_url': 'https://github.com/synthetic/repo/issues/1#' + str(id)}
        self.comments.append(c)
        return c

    def test_bootstrap_retry_and_opt_out(self):
        self.run_event(); self.run_event()
        self.assertEqual(len(self.writes), 1)
        self.assertEqual(github_intake.read_ledger(self.comments, 'synthetic-applicant')['referral_preference'], 'do_not_refer')

    def test_withdraw_replayed_once_after_replaced_pending_run(self):
        self.run_event()
        self.command(1, 'accept', actor='unapproved-reviewer')
        self.command(2, 'withdraw')
        last = self.command(3, 'accept', actor='unapproved-reviewer')
        self.run_event(last)
        ledger = github_intake.read_ledger(self.comments, 'synthetic-applicant')
        self.assertEqual(ledger['state'], 'withdrawn')
        self.assertEqual(ledger['events'], ['2'])
        self.assertEqual(ledger['processed'], ['1', '2', '3'])
        count = len(self.writes); self.run_event(last)
        self.assertEqual(count, len(self.writes))

    def test_actor_cannot_be_injected(self):
        self.run_event()
        c = self.command(5, 'withdraw', actor='intruder')
        c['body'] = '/volunteer {"action":"withdraw","reason":"fixture","actor":"synthetic-applicant"}'
        self.run_event(c)
        self.assertEqual(github_intake.read_ledger(self.comments, 'synthetic-applicant')['state'], 'new')

    def ledger(self):
        return github_intake.read_ledger(self.comments, 'synthetic-applicant')

    def active_policy(self):
        reviewers = {}
        for name in ['synthetic-reviewer-a', 'synthetic-reviewer-b', 'synthetic-approver']:
            reviewers[name] = {
                'availability': 'available', 'verified_at': datetime.now(timezone.utc).isoformat(),
                'approval_reference': 'synthetic-test-only',
                'actions': ['accept', 'refer', 'request_escalation', 'approve_escalation'],
                'destinations': [other for other in ['synthetic-reviewer-a', 'synthetic-reviewer-b'] if other != name],
                'escalation_approvers': ['synthetic-approver']}
        policy = {'enabled': True, 'approval_reference': 'synthetic-test-only', 'reviewers': reviewers,
                  'fallbacks': {}, 'routes': {'team-synthetic': [{'role': 'team_reviewer',
                  'reviewer': 'synthetic-reviewer-a', 'approval_reference': 'synthetic-test-only'}]}}
        (self.root / 'data/authority.v1.json').write_text(json.dumps(policy))
        directory = {k: [] for k in ('teams', 'repositories', 'projects', 'opportunities')}
        directory['teams'] = [{'id': 'team-synthetic'}]
        (self.root / 'data/directory.v1.json').write_text(json.dumps(directory))
        self.issue['body'] += '\n\n### Team interests\n\nteam-synthetic'

    def test_bad_commands_do_not_block_withdrawal_and_retry(self):
        self.run_event()
        bad_bodies = ['{"action":', '[' * 2000 + '0' + ']' * 2000,
                      '{"reason":"' + 'x' * github_intake.MAX_COMMAND_LENGTH + '"}']
        for number, body in enumerate(bad_bodies, 10):
            self.command(number, 'accept')['body'] = '/volunteer ' + body
        final = self.command(20, 'withdraw')
        output = self.run_event(final)
        self.assertEqual(output.count('Decision rejected:'), 3)
        self.assertNotIn('xxxxx', output)
        self.assertEqual(self.ledger()['state'], 'withdrawn')
        self.assertEqual(self.ledger()['events'], ['20'])
        self.assertEqual(self.ledger()['processed'], ['10', '11', '12', '20'])
        count = len(self.writes)
        self.run_event(final)
        self.assertEqual(count, len(self.writes))

    def test_parser_recursion_rejection_is_checkpointed(self):
        self.run_event()
        bad = self.command(21, 'withdraw')
        with patch.object(github_intake, 'parse_command', side_effect=RecursionError):
            self.run_event(bad)
        self.assertEqual(self.ledger()['processed'], ['21'])
        good = self.command(22, 'withdraw')
        self.run_event(good)
        self.assertEqual(self.ledger()['events'], ['22'])

    def test_brackets_in_reason_are_not_nesting(self):
        command = {'action': 'withdraw', 'reason': '[' * 30 + '"escaped"' + ']' * 30}
        self.assertEqual(github_intake.parse_command(json.dumps(command)), command)

    def test_comment_first_preserves_form_routing_and_opt_out(self):
        self.active_policy()
        first = self.command(30, 'refer', actor='synthetic-reviewer-a')
        first['body'] = '/volunteer ' + json.dumps({'action': 'refer', 'reason': 'Synthetic fixture',
                                                   'destination': 'synthetic-reviewer-b'})
        self.run_event(first)
        ledger = self.ledger()
        self.assertTrue(ledger['initialized'])
        self.assertEqual(ledger['selections'], ['team-synthetic'])
        self.assertEqual(ledger['reviewer'], 'synthetic-reviewer-a')
        self.assertEqual(ledger['routing_status'], 'resolved')
        self.assertEqual(ledger['routing_reason'], 'Approved team_reviewer route')
        self.assertEqual(ledger['referral_preference'], 'do_not_refer')
        self.assertEqual(ledger['state'], 'new')
        self.assertEqual(ledger['processed'], ['30'])
        count = len(self.writes)
        self.run_event()  # delayed issues.opened cannot reset the command-first ledger
        self.assertEqual(count, len(self.writes))

    def test_comment_first_withdrawal_initializes_and_remains_withdrawn(self):
        first = self.command(31, 'withdraw')
        self.run_event(first)
        self.assertEqual(self.ledger()['state'], 'withdrawn')
        self.assertEqual(self.ledger()['referral_preference'], 'do_not_refer')
        self.assertEqual(self.ledger()['routing_status'], 'unresolved')
        count = len(self.writes)
        self.run_event(); self.run_event(first)
        self.assertEqual(count, len(self.writes))

    def test_new_application_reresolves_only_its_current_approved_route(self):
        self.active_policy()
        policy_path = self.root / 'data/authority.v1.json'
        approved = policy_path.read_text()
        policy_path.write_text(json.dumps({'enabled': False, 'approval_reference': None,
                                           'reviewers': {}, 'fallbacks': {}}))
        self.run_event()
        self.assertIsNone(self.ledger()['reviewer'])
        self.assertEqual(self.ledger()['selections'], ['team-synthetic'])
        policy_path.write_text(approved)
        command = self.command(32, 'accept', actor='synthetic-reviewer-a')
        self.run_event(command)
        self.assertEqual(self.ledger()['state'], 'accepted')
        self.assertEqual(self.ledger()['reviewer'], 'synthetic-reviewer-a')
        self.assertEqual(self.ledger()['history'][-1]['receiving_reviewer'], 'synthetic-reviewer-a')
        self.assertEqual(self.assignees, {'synthetic-existing-owner', 'synthetic-reviewer-a'})

    def test_null_app_metadata_cannot_create_a_trusted_ledger(self):
        self.comments.append({'id': 999, 'user': {'login': 'github-actions[bot]', 'type': 'Bot'},
                              'performed_via_github_app': None,
                              'body': github_intake.MARKER + '{"state":"active"}'})
        self.run_event()
        self.assertEqual(self.ledger()['state'], 'new')
        self.assertTrue(self.ledger()['initialized'])

    def test_edited_commands_cannot_borrow_original_creator_identity(self):
        self.active_policy(); self.run_event()
        for number, action, creator in [(40, 'withdraw', 'synthetic-applicant'),
                                         (41, 'accept', 'synthetic-reviewer-a')]:
            command = self.command(number, action, actor=creator)
            command['updated_at'] = '2026-10-30T00:01:00Z'
            # The REST object still names the original creator after another
            # actor changes its body; editor identity is not an authorization.
        self.run_event(command)
        self.assertEqual(self.ledger()['state'], 'new')
        self.assertEqual(self.ledger()['processed'], ['40', '41'])
        count = len(self.writes)
        self.run_event(command)
        self.assertEqual(count, len(self.writes))
        fresh = self.command(42, 'withdraw')
        self.run_event(fresh)
        self.assertEqual(self.ledger()['events'], ['42'])

    def test_missing_command_timestamp_is_rejected(self):
        command = self.command(43, 'withdraw')
        del command['updated_at']
        self.run_event(command)
        self.assertEqual(self.ledger()['state'], 'new')
        self.assertEqual(self.ledger()['processed'], ['43'])

    def test_edited_trusted_ledger_stops_even_before_later_valid_marker(self):
        self.run_event()
        first_ledger = self.comments[0]
        command = self.command(44, 'withdraw'); self.run_event(command)
        first_ledger['updated_at'] = '2026-10-30T00:01:00Z'
        count = len(self.writes)
        with self.assertRaisesRegex(ValueError, 'Ledger integrity requires manual review'):
            self.run_event(command)
        self.assertEqual(count, len(self.writes))

    def test_ambiguous_legacy_decisions_are_preserved_for_manual_review(self):
        self.run_event()
        command = self.command(45, 'withdraw'); self.run_event(command)
        legacy = self.ledger(); del legacy['initialized']
        self.comments[-1]['body'] = github_intake.MARKER + '\n' + json.dumps(legacy)
        count = len(self.writes)
        with self.assertRaisesRegex(ValueError, 'Ledger initialization requires manual review'):
            self.run_event(command)
        self.assertEqual(count, len(self.writes))
        self.assertEqual(self.ledger()['state'], 'withdrawn')
        self.assertEqual(self.ledger()['events'], ['45'])

    def test_bootstrap_and_handoff_add_assignees_preserving_owners(self):
        self.active_policy(); self.run_event()
        self.assertEqual(self.assignees, {'synthetic-existing-owner', 'synthetic-reviewer-a'})
        command = self.command(50, 'request_escalation', actor='synthetic-reviewer-a')
        command['body'] = '/volunteer ' + json.dumps({'action': 'request_escalation',
            'reason': 'Synthetic fixture', 'destination': 'synthetic-reviewer-b',
            'unavailability': 'recorded_absence'})
        self.run_event(command)
        approval = self.command(51, 'approve_escalation', actor='synthetic-approver')
        self.run_event(approval)
        self.assertEqual(self.ledger()['reviewer'], 'synthetic-reviewer-b')
        self.assertEqual(self.assignees, {'synthetic-existing-owner', 'synthetic-reviewer-a',
                                        'synthetic-reviewer-b'})

    def test_other_issue_kind_ignored(self):
        self.issue['labels'] = [{'name': 'type:opportunity'}]
        self.run_event()
        self.assertFalse(self.writes)


if __name__ == '__main__':
    unittest.main()
