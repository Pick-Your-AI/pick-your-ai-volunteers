"""Offline v2 policy validation and stable-identity consumer regressions."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from jsonschema import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from validate import validate_authority
from test_program import initial, policy, event, NOW
from program import transition
from github_intake import MARKER
import project_sync


class AuthorityContract(unittest.TestCase):
    def setUp(self):
        self.policy = policy()
        self.policy.update(schema_version='2.0.0', response_period_days=7,
                           notes='Synthetic test only', routes={})

    def test_enabled_policy_requires_stable_numeric_ids(self):
        validate_authority(self.policy, {'team-synthetic'})
        for value in (None, True, 0, -1, '201'):
            with self.subTest(value=value):
                changed = copy.deepcopy(self.policy)
                changed['reviewers']['reviewer-a']['github_user_id'] = value
                with self.assertRaises(ValidationError):
                    validate_authority(changed, {'team-synthetic'})

    def test_disabled_policy_cannot_imply_appointments(self):
        self.policy['enabled'] = False
        with self.assertRaises(ValidationError):
            validate_authority(self.policy, {'team-synthetic'})

    def test_duplicate_identity_and_dangling_relationships_are_rejected(self):
        changed = copy.deepcopy(self.policy)
        changed['reviewers']['reviewer-b']['github_user_id'] = 201
        with self.assertRaises(AssertionError):
            validate_authority(changed, {'team-synthetic'})
        changed = copy.deepcopy(self.policy)
        changed['reviewers']['reviewer-a']['destinations'] = ['missing-reviewer']
        with self.assertRaises(AssertionError):
            validate_authority(changed, {'team-synthetic'})

    def test_empty_selected_route_and_missing_response_period_are_rejected(self):
        changed = copy.deepcopy(self.policy)
        changed['routes'] = {'team-synthetic': []}
        with self.assertRaises(ValidationError):
            validate_authority(changed, {'team-synthetic'})
        self.policy['response_period_days'] = None
        with self.assertRaises(ValidationError):
            validate_authority(self.policy, {'team-synthetic'})


class ProjectIdentityConsumer(unittest.TestCase):
    def test_sync_reads_renamed_applicant_by_stable_id(self):
        state = initial('applicant', 'reviewer-a')
        for action in ('accept', 'begin_onboarding', 'complete_onboarding'):
            state = transition(state, event(action), policy(), NOW)
        state.update(ledger_version=2, initialized=True, public_consent=True, cursor=3,
                     history=state['history'][-1:], events=state['events'][-1:])
        issue = {'number': 1, 'user': {'login': 'renamed-applicant', 'id': 101},
                 'labels': [{'name': 'type:application'}],
                 'html_url': 'https://github.com/synthetic/repo/issues/1'}
        comment = {'user': {'login': 'github-actions[bot]'},
                   'performed_via_github_app': {'slug': 'github-actions'},
                   'created_at': NOW.isoformat(), 'updated_at': NOW.isoformat(),
                   'body': MARKER + '\n' + json.dumps(state)}
        edits = []

        def gh(*args):
            if args[:2] == ('project', 'field-list'):
                return {'fields': [
                    {'name': 'Kind', 'id': 'kind-field', 'options': [{'name': 'Application', 'id': 'application-option'}]},
                    {'name': 'Volunteer state', 'id': 'state-field', 'options': [{'name': 'Active', 'id': 'active-option'}]}]}
            if args[0] == 'api':
                return [[comment]] if '/comments?' in args[-1] else [[issue]]
            if args[:2] == ('project', 'item-add'):
                return {'id': 'synthetic-item'}
            if args[:2] == ('project', 'item-edit'):
                edits.append(args)
                return None
            self.fail('Unexpected mocked Project command')

        with patch.object(project_sync, 'gh', gh), contextlib.redirect_stdout(io.StringIO()):
            project_sync.main()
        self.assertEqual(len(edits), 2)
        self.assertTrue(any('active-option' in command for command in edits))


if __name__ == '__main__':
    unittest.main()
