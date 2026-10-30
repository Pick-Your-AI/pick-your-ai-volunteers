"""Operator-run Project sync. Requires an authenticated gh CLI with Project scope.

Reads only this public hub. Never grants access or infers decision authority.
"""
import json
import subprocess
from pathlib import Path
from github_intake import read_ledger

REPO = 'Pick-Your-AI/pick-your-ai-volunteers'
OWNER = 'Pick-Your-AI'
NUMBER = '14'
PROJECT = 'PVT_kwDOFHg4Xc4BpZWN'
ROOT = Path(__file__).resolve().parents[1]


def gh(*args):
    p = subprocess.run(['gh', *args], capture_output=True, text=True, encoding='utf-8', check=True)
    return json.loads(p.stdout) if p.stdout.strip() else None


def pages(path):
    return [item for page in gh('api', '--paginate', '--slurp', path) for item in page]


def main():
    fields = {f['name']: f for f in gh('project', 'field-list', NUMBER, '--owner', OWNER, '--format', 'json')['fields']}
    directory = json.loads((ROOT / 'data/directory.v1.json').read_text(encoding='utf-8'))
    opportunities = {o['id']: o for o in directory['opportunities']}
    for issue in pages(f'repos/{REPO}/issues?state=all&per_page=100'):
        if issue.get('pull_request'):
            continue
        labels = {l['name'] for l in issue['labels']}
        kinds = {'type:application': 'Application', 'type:opportunity': 'Opportunity', 'type:availability': 'Availability', 'type:referral': 'Referral'}
        kind = next((v for k, v in kinds.items() if k in labels), None)
        if not kind:
            continue
        item = gh('project', 'item-add', NUMBER, '--owner', OWNER, '--url', issue['html_url'], '--format', 'json')
        values = {'Kind': kind}
        if kind == 'Application':
            ledger = read_ledger(pages(f'repos/{REPO}/issues/{issue["number"]}/comments?per_page=100'), issue['user']['login'])
            state = ledger['state']
            values['Volunteer state'] = {'new': 'New', 'referral_pending': 'Awaiting information', 'awaiting_escalation_approval': 'Awaiting escalation approval'}.get(state, state.replace('_', ' ').capitalize())
            if not ledger['reviewer'] and state == 'new':
                values['Volunteer state'] = 'Awaiting reviewer'
        elif kind == 'Opportunity':
            # Only canonical stable IDs in the controlled title map to directory facts.
            matches = [o for id, o in opportunities.items() if issue['title'].startswith('[' + id + ']')]
            if len(matches) == 1:
                o = matches[0]
                values['Staffing need'] = o['staffing_need'].replace('_', ' ').capitalize()
                values['Readiness'] = 'Ready' if o['status'] == 'recruiting' and o['onboarding_capacity'] == 'confirmed' else 'Filled' if o['status'] == 'filled' else 'Capacity unknown'
        for name, value in values.items():
            f = fields[name]
            option = next(x['id'] for x in f['options'] if x['name'] == value)
            gh('project', 'item-edit', '--id', item['id'], '--project-id', PROJECT, '--field-id', f['id'], '--single-select-option-id', option)
    print('Project synchronized from public records; no ownership or access changes.')


if __name__ == '__main__':
    main()
