"""Runs on trusted default-branch issue_comment workflow; never executes issue text."""
import json
import os
from pathlib import Path
import urllib.request
import urllib.error
from program import initial, transition

ROOT = Path(__file__).resolve().parents[1]
MARKER = '<!-- volunteer-ledger:v1 -->'


def api(path, payload=None, method=None):
    request = urllib.request.Request('https://api.github.com/' + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method, headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
        'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def comments(repo, number):
    result = []
    page = 1
    while True:
        batch = api(f'repos/{repo}/issues/{number}/comments?per_page=100&page={page}')
        result.extend(batch)
        if len(batch) < 100:
            return result
        page += 1


def read_ledger(items, applicant):
    state = initial(applicant)
    for c in items:
        if (c['user']['login'] == 'github-actions[bot]' and
            c.get('performed_via_github_app', {}).get('slug') == 'github-actions' and
            c['body'].startswith(MARKER)):
            state = json.loads(c['body'][len(MARKER):].strip())
            if state['applicant'] != applicant:
                raise ValueError('Ledger identity mismatch')
    return state


def run():
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text(encoding='utf-8'))
    issue = event['issue']
    if issue.get('pull_request') or not any(l['name'] == 'type:application' for l in issue['labels']):
        return
    repo, number = os.environ['GITHUB_REPOSITORY'], issue['number']
    policy = json.loads((ROOT / 'data/authority.v1.json').read_text(encoding='utf-8'))
    all_comments = comments(repo, number)
    state = read_ledger(all_comments, issue['user']['login'])
    comment = event.get('comment')
    if not comment:
        if not state['history']:
            # One bootstrap marker per issue. A retry observes the previous marker.
            if not any(c['body'].startswith(MARKER) and c['user']['login'] == 'github-actions[bot]' for c in all_comments):
                if '### Referral preference\n\nDo not refer me' in (issue.get('body') or '').replace('\r\n', '\n'):
                    state['referral_preference'] = 'do_not_refer'
                api(f'repos/{repo}/issues/{number}/comments', {'body': MARKER + '\n' + json.dumps(state, sort_keys=True)})
        return
    updated = state
    seen = set(state.get('processed', state['events']))
    # GitHub concurrency can replace a pending job. Replay unseen commands in API
    # order so cancellation cannot silently lose an earlier applicant decision.
    for c in all_comments:
        if c['user']['type'] == 'Bot' or not c['body'].startswith('/volunteer ') or str(c['id']) in seen:
            continue
        try:
            command = json.loads(c['body'][len('/volunteer '):])
            if not isinstance(command, dict) or set(command) - {'action', 'reason', 'destination', 'receipt', 'unavailability'}:
                raise ValueError('Unknown command keys')
            command.update(id=str(c['id']), actor=c['user']['login'], at=c['created_at'], source=c['html_url'])
            updated = transition(updated, command, policy)
        except (ValueError, KeyError, TypeError):
            print('Decision rejected: invalid transition, command, consent, or authority. No state changed.')
        seen.add(str(c['id']))
    updated = dict(updated, processed=sorted(seen))
    if updated == state:
        return
    api(f'repos/{repo}/issues/{number}/comments', {'body': MARKER + '\n' + json.dumps(updated, sort_keys=True)})
    # The ledger is authoritative for lifecycle; issue Assignees are canonical responsibility.
    # Do not silently reassign unrelated work: only this application, only its authorized reviewer.
    if updated['reviewer'] and updated['reviewer'] != state['reviewer']:
        api(f'repos/{repo}/issues/{number}', {'assignees': [updated['reviewer']]}, 'PATCH')


if __name__ == '__main__':
    run()
