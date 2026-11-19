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


IDS = {'synthetic-applicant': 101, 'synthetic-reviewer-a': 201, 'synthetic-reviewer-b': 202,
       'synthetic-approver': 203, 'intruder': 301, 'unapproved-reviewer': 302}
CONSENT = '### Visibility consent\n\n' + github_intake.VISIBILITY_CONSENT


class Intake(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'data').mkdir()
        (self.root / 'data/authority.v2.json').write_text(json.dumps({'enabled': False, 'approval_reference': None, 'reviewers': {}, 'fallbacks': {}}))
        (self.root / 'data/directory.v1.json').write_text(json.dumps({k: [] for k in ('teams', 'repositories', 'projects', 'opportunities')}))
        self.issue = {'number': 1, 'user': {'login': 'synthetic-applicant', 'id': IDS['synthetic-applicant']}, 'labels': [{'name': 'type:application'}], 'body': '### Referral preference\n\nDo not refer me\n\n' + CONSENT}
        self.comments = []
        self.writes = []
        self.assignees = {'synthetic-existing-owner'}
        self.identities = {user_id: {'id': user_id, 'login': login} for login, user_id in IDS.items()}

    def tearDown(self):
        self.tmp.cleanup()

    def api(self, path, payload=None, method=None):
        if payload is None:
            if path.startswith('user/'):
                return self.identities[int(path.split('/')[1])]
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
        c = {'id': id, 'user': {'login': actor, 'id': IDS[actor], 'type': 'User'}, 'body': '/volunteer ' + json.dumps({'action': action, 'reason': 'Synthetic fixture'}), 'created_at': '2026-10-30T00:00:00Z', 'updated_at': '2026-10-30T00:00:00Z', 'html_url': 'https://github.com/synthetic/repo/issues/1#' + str(id)}
        self.comments.append(c)
        return c

    def test_bootstrap_retry_and_opt_out(self):
        self.run_event(); self.run_event()
        self.assertEqual(len(self.writes), 1)
        self.assertEqual(github_intake.read_ledger(self.comments, self.issue['user']['login'], self.issue['user']['id'])['referral_preference'], 'do_not_refer')

    def test_withdraw_replayed_once_after_replaced_pending_run(self):
        self.run_event()
        self.command(1, 'accept', actor='unapproved-reviewer')
        self.command(2, 'withdraw')
        last = self.command(3, 'accept', actor='unapproved-reviewer')
        self.run_event(last)
        ledger = github_intake.read_ledger(self.comments, self.issue['user']['login'], self.issue['user']['id'])
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
        self.assertEqual(github_intake.read_ledger(self.comments, self.issue['user']['login'], self.issue['user']['id'])['state'], 'new')

    def ledger(self):
        return github_intake.read_ledger(self.comments, self.issue['user']['login'], self.issue['user']['id'])

    def active_policy(self):
        reviewers = {}
        for name in ['synthetic-reviewer-a', 'synthetic-reviewer-b', 'synthetic-approver']:
            reviewers[name] = {
                'github_user_id': IDS[name], 'availability': 'available', 'verified_at': datetime.now(timezone.utc).isoformat(),
                'approval_reference': 'synthetic-test-only',
                'actions': ['accept', 'refer', 'request_escalation', 'approve_escalation'],
                'destinations': [other for other in ['synthetic-reviewer-a', 'synthetic-reviewer-b'] if other != name],
                'escalation_approvers': ['synthetic-approver']}
        policy = {'enabled': True, 'approval_reference': 'synthetic-test-only', 'reviewers': reviewers,
                  'fallbacks': {}, 'routes': {'team-synthetic': [{'role': 'team_reviewer',
                  'reviewer': 'synthetic-reviewer-a', 'approval_reference': 'synthetic-test-only'}]}}
        (self.root / 'data/authority.v2.json').write_text(json.dumps(policy))
        directory = {k: [] for k in ('teams', 'repositories', 'projects', 'opportunities')}
        directory['teams'] = [{'id': 'team-synthetic', 'name': 'Synthetic Team'}]
        (self.root / 'data/directory.v1.json').write_text(json.dumps(directory))
        self.issue['body'] += '\n\n### Preferred team\n\nteam-synthetic — Synthetic Team'

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
        policy_path = self.root / 'data/authority.v2.json'
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
        with self.assertRaisesRegex(ValueError, 'Ledger identity requires manual review'):
            self.run_event(command)
        self.assertEqual(count, len(self.writes))
        retained = json.loads(self.comments[-1]['body'][len(github_intake.MARKER):])
        self.assertEqual(retained['state'], 'withdrawn')
        self.assertEqual(retained['events'], ['45'])

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

    def test_missing_unchecked_or_duplicate_consent_has_no_writes(self):
        self.active_policy()
        original = self.issue['body']
        for body in [original.replace(CONSENT, ''), original.replace('- [x]', '- [ ]'),
                     original + '\n\n' + CONSENT,
                     original.replace(github_intake.VISIBILITY_CONSENT, '- [x] I agree')]:
            with self.subTest(body_kind=len(body)):
                self.issue['body'] = body
                with self.assertRaisesRegex(ValueError, 'Application (consent|form) requires review'):
                    self.run_event()
                self.assertFalse(self.writes)

    def test_rendered_uppercase_checked_consent_is_accepted(self):
        self.issue['body'] = self.issue['body'].replace('- [x]', '- [X]')
        self.run_event()
        self.assertTrue(self.ledger()['public_consent'])

    def test_missing_ambiguous_or_unknown_referral_has_no_writes(self):
        original = self.issue['body']
        for body in [CONSENT, original + '\n\n### Referral preference\n\nAsk me before each placement change',
                     original.replace('Do not refer me', 'Maybe'),
                     original.replace('Do not refer me', 'Do not refer me\nAsk me before each placement change')]:
            with self.subTest(body_kind=len(body)):
                self.issue['body'] = body
                with self.assertRaises(ValueError):
                    self.run_event()
                self.assertFalse(self.writes)

    def test_free_text_ids_are_not_selections_or_routing_consent(self):
        self.active_policy()
        self.issue['body'] = self.issue['body'].split('### Preferred team')[0]
        self.issue['body'] += ('### Alternative interests and useful skills\n\n'
                               'team-synthetic and No preference are free text only.')
        self.run_event()
        ledger = self.ledger()
        self.assertEqual(ledger['selections'], [])
        self.assertFalse(ledger['allow_empty_route'])
        self.assertIsNone(ledger['reviewer'])
        self.assertNotIn('free text only', json.dumps(ledger))
        self.assertEqual(self.assignees, {'synthetic-existing-owner'})

    def test_exact_multiselect_options_include_commas_in_labels(self):
        records = [{'id': 'team-a', 'name': 'Alpha, Beta'}, {'id': 'team-b', 'name': 'Gamma'}]
        self.assertEqual(github_intake.dropdown_ids('team-a — Alpha, Beta, team-b — Gamma', records),
                         ['team-a', 'team-b'])
        self.assertEqual(github_intake.dropdown_ids('No preference', records), [])
        self.assertEqual(github_intake.dropdown_ids('Help me find where I am most useful', records), [])
        self.assertEqual(github_intake.dropdown_ids('_No response_', records), [])
        for value in ['team-a', 'team-a — Wrong label', 'None', 'team-unknown — Unknown',
                      'No preference, team-unknown — Unknown', 'team-a — Alpha, Beta, ']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                github_intake.dropdown_ids(value, records)

    def test_unknown_choices_never_trigger_empty_fallback(self):
        self.active_policy()
        path = self.root / 'data/authority.v2.json'
        policy = json.loads(path.read_text()); policy['fallbacks'] = {'empty': 'synthetic-reviewer-a'}
        path.write_text(json.dumps(policy))
        original = self.issue['body']
        for value in ['None', 'team-unknown — Unknown', 'No preference, team-unknown — Unknown']:
            self.issue['body'] = original.split('### Preferred team')[0] + '### Preferred team\n\n' + value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.run_event()
            self.assertFalse(self.writes)

    def test_only_explicit_no_preference_or_help_allows_empty_fallback(self):
        self.active_policy()
        path = self.root / 'data/authority.v2.json'
        policy = json.loads(path.read_text()); policy['fallbacks'] = {'empty': 'synthetic-reviewer-a'}
        path.write_text(json.dumps(policy))
        base = self.issue['body'].split('### Preferred team')[0]
        for choice in [None, '_No response_', 'No preference', 'Help me find where I am most useful']:
            with self.subTest(choice=choice):
                self.comments = []; self.writes = []; self.assignees = {'synthetic-existing-owner'}
                self.issue['body'] = base + ('### Preferred team\n\n' + choice if choice else '')
                self.run_event()
                expected = choice in {'No preference', 'Help me find where I am most useful'}
                self.assertEqual(self.ledger()['allow_empty_route'], expected)
                self.assertEqual(self.ledger()['reviewer'], 'synthetic-reviewer-a' if expected else None)

    def test_duplicate_preferred_sections_are_rejected(self):
        self.active_policy()
        self.issue['body'] += '\n\n### Preferred team\n\nNo preference'
        with self.assertRaises(ValueError):
            self.run_event()
        self.assertFalse(self.writes)

    def test_applicant_id_is_required_and_boolean_is_not_an_id(self):
        for value in [None, True, 0, -1, '101']:
            with self.subTest(value=value):
                self.issue['user']['id'] = value
                with self.assertRaises(ValueError):
                    self.run_event()
                self.assertFalse(self.writes)

    def test_stable_id_preserves_withdrawal_after_login_rename(self):
        self.run_event()
        self.issue['user']['login'] = 'synthetic-renamed-applicant'
        self.issue['body'] = 'Applicant removed form text after initialization.'
        command = self.command(60, 'withdraw')
        command['user']['login'] = 'synthetic-renamed-applicant'
        self.run_event(command)
        self.assertEqual(self.ledger()['state'], 'withdrawn')
        self.assertEqual(self.ledger()['applicant_id'], 101)
        self.assertEqual(self.ledger()['history'][-1]['actor_id'], 101)
        self.assertEqual(self.ledger()['history'][-1]['actor'], 'synthetic-renamed-applicant')

    def test_same_login_with_different_id_cannot_withdraw(self):
        self.run_event()
        command = self.command(61, 'withdraw'); command['user']['id'] = 999
        self.run_event(command)
        self.assertEqual(self.ledger()['state'], 'new')
        self.assertEqual(self.ledger()['processed'], ['61'])
        self.issue['user']['id'] = 999
        count = len(self.writes)
        with self.assertRaisesRegex(ValueError, 'Ledger identity mismatch'):
            self.run_event(command)
        self.assertEqual(count, len(self.writes))

    def test_same_reviewer_login_with_different_id_cannot_accept(self):
        self.active_policy(); self.run_event()
        command = self.command(64, 'accept', actor='synthetic-reviewer-a')
        command['user']['id'] = IDS['intruder']
        self.run_event(command)
        self.assertEqual(self.ledger()['state'], 'new')
        self.assertEqual(self.ledger()['processed'], ['64'])
        fresh = self.command(65, 'accept', actor='synthetic-reviewer-a')
        fresh['user']['login'] = 'synthetic-renamed-reviewer'
        self.run_event(fresh)
        self.assertEqual(self.ledger()['state'], 'accepted')
        self.assertEqual(self.ledger()['history'][-1]['actor_id'], 201)
        self.assertEqual(self.ledger()['history'][-1]['actor'], 'synthetic-renamed-reviewer')

    def test_missing_or_boolean_command_id_is_checkpointed(self):
        self.run_event()
        for number, value in [(62, None), (63, True)]:
            command = self.command(number, 'withdraw'); command['user']['id'] = value
        self.run_event(command)
        self.assertEqual(self.ledger()['state'], 'new')
        self.assertEqual(self.ledger()['processed'], ['62', '63'])

    def test_legacy_marker_or_missing_stable_ledger_identity_is_not_reset(self):
        self.run_event()
        original = self.comments[-1]['body']
        for marker, remove_id in [(github_intake.LEGACY_MARKER, False), (github_intake.MARKER, True)]:
            ledger = json.loads(original[len(github_intake.MARKER):])
            if remove_id:
                del ledger['applicant_id']
            self.comments[-1]['body'] = marker + '\n' + json.dumps(ledger)
            count = len(self.writes)
            with self.subTest(marker=marker), self.assertRaises(ValueError):
                self.run_event()
            self.assertEqual(count, len(self.writes))

    def test_reviewer_lookup_mismatch_or_unsafe_login_never_assigns(self):
        self.active_policy()
        for result in [{'id': 999, 'login': 'synthetic-reviewer-a'},
                       {'id': True, 'login': 'synthetic-reviewer-a'},
                       {'id': 201, 'login': '../unsafe'}, {'id': 201, 'login': None}]:
            self.comments = []; self.writes = []
            self.identities[201] = result
            with self.subTest(result=result), self.assertRaisesRegex(ValueError, 'Reviewer identity requires review'):
                self.run_event()
            self.assertEqual(self.assignees, {'synthetic-existing-owner'})
            self.assertFalse(any(path.endswith('/assignees') for path, payload in self.writes))

    def test_reviewer_assignment_uses_current_login_bound_to_stable_id(self):
        self.active_policy()
        self.identities[201] = {'id': 201, 'login': 'synthetic-renamed-reviewer'}
        self.run_event()
        self.assertEqual(self.ledger()['reviewer'], 'synthetic-reviewer-a')
        self.assertEqual(self.ledger()['reviewer_id'], 201)
        self.assertEqual(self.assignees, {'synthetic-existing-owner', 'synthetic-renamed-reviewer'})

    def test_other_issue_kind_ignored(self):
        self.issue['labels'] = [{'name': 'type:opportunity'}]
        self.run_event()
        self.assertFalse(self.writes)


if __name__ == '__main__':
    unittest.main()
