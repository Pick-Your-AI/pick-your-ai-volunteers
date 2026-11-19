import json
import re
from pathlib import Path
from datetime import datetime, timezone
from jsonschema import Draft202012Validator, FormatChecker
from program import fresh

ROOT = Path(__file__).resolve().parents[1]


def validate_authority(policy, ids):
    schema = json.loads((ROOT / 'schemas/authority.v2.schema.json').read_text(encoding='utf-8'))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(policy)
    identities = [record['github_user_id'] for record in policy['reviewers'].values()]
    assert len(identities) == len(set(identities)), 'Reviewer account IDs must be unique'
    for record in policy['reviewers'].values():
        assert set(record['destinations'] + record['escalation_approvers']) <= policy['reviewers'].keys()
    assert set(policy['fallbacks'].values()) <= policy['reviewers'].keys()
    order = ['team_reviewer', 'repository_maintainer', 'repository_lead', 'parent_team_reviewer', 'organization_fallback']
    for scope, route in policy['routes'].items():
        assert scope in ids, 'Unknown routing scope'
        ranks = [order.index(step['role']) for step in route]
        assert ranks == sorted(ranks), 'Routing roles out of order'
        assert len({step['reviewer'] for step in route}) == len(route), 'Repeated routing recipient'
        assert all(step['reviewer'] in policy['reviewers'] for step in route)


def validate():
    d = json.loads((ROOT / 'data/directory.v1.json').read_text(encoding='utf-8'))
    schema = json.loads((ROOT / 'schemas/directory.v1.schema.json').read_text(encoding='utf-8'))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(d)
    kinds = ('teams', 'repositories', 'projects', 'roles', 'opportunities', 'routing_policies')
    ids = [r['id'] for kind in kinds for r in d[kind]]
    assert len(ids) == len(set(ids)), 'Duplicate ID'
    for kind in kinds:
        for r in d[kind]:
            for key, target in [('team_ids', 'teams'), ('repository_ids', 'repositories'), ('project_ids', 'projects'), ('role_ids', 'roles')]:
                assert set(r.get(key, [])) <= {v['id'] for v in d[target]}, 'Dangling relation'
            if r.get('parent_team_id'):
                assert r['parent_team_id'] in {v['id'] for v in d['teams']}
            if 'github' in r:
                assert r['github']['url'].startswith(('https://github.com/Pick-Your-AI/', 'https://github.com/orgs/Pick-Your-AI/'))
                assert fresh(r['verified_at'], datetime.now(timezone.utc)), 'Stale directory evidence: refresh live source'
    assert all(o['routing_policy_id'] in {r['id'] for r in d['routing_policies']} for o in d['opportunities'])
    policy = json.loads((ROOT / 'data/authority.v2.json').read_text(encoding='utf-8'))
    validate_authority(policy, ids)
    # Prevent accidentally exporting internal-directory or application fields.
    assert 'internal-discussion' not in json.dumps(d)
    for page in [ROOT / 'README.md', ROOT / 'CONTRIBUTING.md', * (ROOT / 'docs').glob('*.md')]:
        for target in re.findall(r'\]\(([^)]+)\)', page.read_text(encoding='utf-8')):
            if '://' not in target and not target.startswith('#'):
                assert (page.parent / target.split('#')[0]).exists(), f'Broken local link in {page.name}: {target}'
    print(f'Validated {len(ids)} canonical records; no private application data loaded.')


if __name__ == '__main__':
    validate()
