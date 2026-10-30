import json
import re
from pathlib import Path
from datetime import datetime, timezone
from jsonschema import Draft202012Validator, FormatChecker
from program import fresh

ROOT = Path(__file__).resolve().parents[1]


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
    policy = json.loads((ROOT / 'data/authority.v1.json').read_text(encoding='utf-8'))
    if policy['enabled']:
        assert policy['approval_reference'] and policy['reviewers'], 'Authority cannot activate without a decision'
        for name, r in policy['reviewers'].items():
            assert r['approval_reference'] and r['availability'] in ('available', 'absent', 'unknown', 'conflict')
            assert set(r['destinations'] + r['escalation_approvers']) <= policy['reviewers'].keys()
        assert set(policy['fallbacks'].values()) <= policy['reviewers'].keys()
    else:
        assert not policy['reviewers'] and not policy['fallbacks'], 'Inactive policy must not imply appointments'
    # Prevent accidentally exporting internal-directory or application fields.
    assert 'internal-discussion' not in json.dumps(d)
    for page in [ROOT / 'README.md', ROOT / 'CONTRIBUTING.md', * (ROOT / 'docs').glob('*.md')]:
        for target in re.findall(r'\]\(([^)]+)\)', page.read_text(encoding='utf-8')):
            if '://' not in target and not target.startswith('#'):
                assert (page.parent / target.split('#')[0]).exists(), f'Broken local link in {page.name}: {target}'
    print(f'Validated {len(ids)} canonical records; no private application data loaded.')


if __name__ == '__main__':
    validate()
