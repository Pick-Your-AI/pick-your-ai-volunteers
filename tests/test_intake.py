"""Controlled GitHub transport fixtures; no network requests or real volunteers."""
import contextlib
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
        self.issue = {'number': 1, 'user': {'login': 'synthetic-applicant'}, 'labels': [{'name': 'type:application'}], 'body': '### Referral preference\n\nDo not refer me'}
        self.comments = []
        self.writes = []

    def tearDown(self):
        self.tmp.cleanup()

    def api(self, path, payload=None, method=None):
        if payload is None:
            return self.comments[:]
        self.writes.append((path, payload))
        if path.endswith('/comments'):
            self.comments.append({'id': 1000 + len(self.writes), 'user': {'login': 'github-actions[bot]', 'type': 'Bot'}, 'performed_via_github_app': {'slug': 'github-actions'}, 'body': payload['body']})
        return {}

    def run_event(self, comment=None):
        event = {'issue': self.issue}
        if comment:
            event['comment'] = comment
        p = self.root / 'event.json'
        p.write_text(json.dumps(event))
        with patch.object(github_intake, 'ROOT', self.root), patch.object(github_intake, 'api', self.api), patch.dict(os.environ, {'GITHUB_EVENT_PATH': str(p), 'GITHUB_REPOSITORY': 'synthetic/repo'}), contextlib.redirect_stdout(io.StringIO()):
            github_intake.run()

    def command(self, id, action, actor='synthetic-applicant'):
        c = {'id': id, 'user': {'login': actor, 'type': 'User'}, 'body': '/volunteer ' + json.dumps({'action': action, 'reason': 'Synthetic fixture'}), 'created_at': '2026-10-30T00:00:00Z', 'html_url': 'https://github.com/synthetic/repo/issues/1#' + str(id)}
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

    def test_other_issue_kind_ignored(self):
        self.issue['labels'] = [{'name': 'type:opportunity'}]
        self.run_event()
        self.assertFalse(self.writes)


if __name__ == '__main__':
    unittest.main()
