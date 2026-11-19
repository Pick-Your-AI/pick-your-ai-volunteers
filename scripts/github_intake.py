"""Runs on trusted default-branch issue_comment workflow; never executes issue text."""
import json
import os
import re
from pathlib import Path
import urllib.request
import urllib.error
from program import initial, transition, resolve_route

ROOT = Path(__file__).resolve().parents[1]
MARKER = '<!-- volunteer-ledger:v1 -->'
MAX_COMMAND_LENGTH = 8192
MAX_COMMAND_DEPTH = 16


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


def unchanged_comment(comment):
    created = comment.get('created_at')
    return isinstance(created, str) and bool(created) and comment.get('updated_at') == created


def parse_command(body):
    # Reject excessive input before decoding: json.loads can recurse before a
    # schema/type check is reached. Strings may contain escaped brackets.
    if len(body) > MAX_COMMAND_LENGTH:
        raise ValueError('Command resource limit')
    depth = 0
    quoted = escaped = False
    for char in body:
        if quoted:
            if escaped:
                escaped = False
            elif char == chr(92):
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in '[{':
            depth += 1
            if depth > MAX_COMMAND_DEPTH:
                raise ValueError('Command resource limit')
        elif char in ']}':
            depth -= 1
    return json.loads(body)


def read_ledger(items, applicant):
    state = initial(applicant)
    for c in items:
        if (c['user']['login'] == 'github-actions[bot]' and
            (c.get('performed_via_github_app') or {}).get('slug') == 'github-actions' and
            c['body'].startswith(MARKER)):
            # A later valid marker must not conceal a changed audit entry.
            if not unchanged_comment(c):
                raise ValueError('Ledger integrity requires manual review')
            state = json.loads(c['body'][len(MARKER):].strip())
            if state['applicant'] != applicant:
                raise ValueError('Ledger identity mismatch')
    return state


def initialize(issue, directory, policy):
    known = {r['id'] for kind in ('teams', 'repositories', 'projects', 'opportunities') for r in directory[kind]}
    selected = sorted(set(re.findall(r'[A-Za-z0-9_-]+', issue.get('body') or '')) & known)
    reviewer, reason = resolve_route(directory, policy, selected)
    preference = 'ask_each_time'
    if '### Referral preference\n\nDo not refer me' in (issue.get('body') or '').replace('\r\n', '\n'):
        preference = 'do_not_refer'
    state = initial(issue['user']['login'], reviewer, preference)
    state.update(initialized=True, selections=selected, routing_reason=reason,
                 routing_status='resolved' if reviewer else 'unresolved', processed=[])
    return state


def record_state(repo, number, state):
    api(f'repos/{repo}/issues/{number}/comments', {'body': MARKER + '\n' + json.dumps(state, sort_keys=True)})


def add_reviewer(repo, number, reviewer):
    if reviewer:
        # The additive endpoint preserves unrelated owners and prior assignees.
        api(f'repos/{repo}/issues/{number}/assignees', {'assignees': [reviewer]}, 'POST')


def run():
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text(encoding='utf-8'))
    issue = event['issue']
    if issue.get('pull_request') or not any(l['name'] == 'type:application' for l in issue['labels']):
        return
    repo, number = os.environ['GITHUB_REPOSITORY'], issue['number']
    policy = json.loads((ROOT / 'data/authority.v1.json').read_text(encoding='utf-8'))
    directory = json.loads((ROOT / 'data/directory.v1.json').read_text(encoding='utf-8'))
    all_comments = comments(repo, number)
    state = read_ledger(all_comments, issue['user']['login'])
    if not state.get('initialized'):
        # An old command-first ledger can have decisions but no form metadata.
        # Do not reset decisions or silently reinterpret historical consent.
        if state['history'] or state['events'] or state.get('processed'):
            raise ValueError('Ledger initialization requires manual review')
        state = initialize(issue, directory, policy)
        record_state(repo, number, state)
        add_reviewer(repo, number, state['reviewer'])
    if not event.get('comment'):
        return
    updated = state
    seen = set(state.get('processed', state['events']))
    # GitHub concurrency can replace a pending job. Replay unseen commands in API
    # order so cancellation cannot silently lose an earlier applicant decision.
    for c in all_comments:
        if c['user']['type'] == 'Bot' or not c['body'].startswith('/volunteer ') or str(c['id']) in seen:
            continue
        try:
            if not unchanged_comment(c):
                raise ValueError('Command integrity requires a fresh comment')
            command = parse_command(c['body'][len('/volunteer '):])
            if not isinstance(command, dict) or set(command) - {'action', 'reason', 'destination', 'receipt', 'unavailability'}:
                raise ValueError('Unknown command keys')
            command.update(id=str(c['id']), actor=c['user']['login'], at=c['created_at'], source=c['html_url'])
            updated = transition(updated, command, policy, directory=directory)
        except (ValueError, KeyError, TypeError, RecursionError):
            print('Decision rejected: invalid transition, command, consent, or authority. No state changed.')
        seen.add(str(c['id']))
    updated = dict(updated, processed=sorted(seen))
    if updated == state:
        return
    record_state(repo, number, updated)
    # The ledger is authoritative for lifecycle; issue Assignees are canonical responsibility.
    # Do not silently reassign unrelated work: only this application, only its authorized reviewer.
    if updated['reviewer'] and updated['reviewer'] != state['reviewer']:
        add_reviewer(repo, number, updated['reviewer'])


if __name__ == '__main__':
    run()
