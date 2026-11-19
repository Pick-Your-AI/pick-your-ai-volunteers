"""Runs on trusted default-branch issue_comment workflow; never executes issue text."""
import json
import os
import re
from pathlib import Path
import urllib.request
import urllib.error
from program import initial, transition, resolve_route

ROOT = Path(__file__).resolve().parents[1]
MARKER = '<!-- volunteer-ledger:v2 -->'
LEGACY_MARKER = '<!-- volunteer-ledger:v1 -->'
VISIBILITY_CONSENT = '- [x] I understand this is public and consent to public application review. Each proposed placement change needs my agreement.'
REFERRAL_CHOICES = {'Ask me before each placement change': 'ask_each_time', 'Do not refer me': 'do_not_refer'}
EMPTY_CHOICES = {'Help me find where I am most useful', 'No preference', '_No response_'}
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


def positive_id(value):
    return type(value) is int and value > 0


def read_ledger(items, applicant_login, applicant_id):
    if not positive_id(applicant_id):
        raise ValueError('Application identity requires manual review')
    state = initial(applicant_login, applicant_id=applicant_id)
    for c in items:
        if (c['user']['login'] == 'github-actions[bot]' and
            (c.get('performed_via_github_app') or {}).get('slug') == 'github-actions'):
            if c['body'].startswith(LEGACY_MARKER):
                raise ValueError('Legacy ledger requires manual review')
            if not c['body'].startswith(MARKER):
                continue
            # A later valid marker must not conceal a changed audit entry.
            if not unchanged_comment(c):
                raise ValueError('Ledger integrity requires manual review')
            state = json.loads(c['body'][len(MARKER):].strip())
            if (state.get('ledger_version') != 2 or state.get('initialized') is not True or
                not positive_id(state.get('applicant_id'))):
                raise ValueError('Ledger identity requires manual review')
            if state['applicant_id'] != applicant_id:
                raise ValueError('Ledger identity mismatch')
    return state


def form_sections(body):
    if not isinstance(body, str):
        raise ValueError('Application form requires review')
    sections = {}
    current = None
    for line in body.replace('\r\n', '\n').splitlines():
        if line.startswith('### '):
            current = line[4:]
            if current in sections:
                raise ValueError('Application form requires review')
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return {name: '\n'.join(lines).strip() for name, lines in sections.items()}


def dropdown_ids(value, records):
    # Match complete generated options, including labels containing commas.
    options = {record['id'] + ' — ' + record['name']: record['id'] for record in records}
    options.update({choice: None for choice in EMPTY_CHOICES})
    selected = []
    rest = value
    while rest:
        matches = [choice for choice in options if rest == choice or rest.startswith(choice + ', ')]
        if len(matches) != 1:
            raise ValueError('Application choices require review')
        choice = matches[0]
        if options[choice] is not None:
            selected.append(options[choice])
        rest = rest[len(choice):]
        if rest:
            rest = rest[2:]
            if not rest:
                raise ValueError('Application choices require review')
    return selected


def initialize(issue, directory, policy):
    applicant_id = issue['user'].get('id')
    if not positive_id(applicant_id):
        raise ValueError('Application identity requires review')
    sections = form_sections(issue.get('body'))
    if (sections.get('Visibility consent') not in {VISIBILITY_CONSENT, VISIBILITY_CONSENT.replace('[x]', '[X]')} or
        sections.get('Referral preference') not in REFERRAL_CHOICES):
        raise ValueError('Application consent requires review')
    selected = []
    explicit_empty = False
    for kind, label in [('opportunities', 'Preferred opportunity'), ('teams', 'Preferred team'),
                        ('repositories', 'Preferred repository'), ('projects', 'Preferred Project')]:
        if label in sections:
            choices = sections[label]
            selected.extend(dropdown_ids(choices, directory[kind]))
            explicit_empty = explicit_empty or any(choice in choices for choice in EMPTY_CHOICES - {'_No response_'})
    selected = sorted(set(selected))
    allow_empty_route = explicit_empty and not selected
    if selected or allow_empty_route:
        reviewer, reason = resolve_route(directory, policy, selected)
    else:
        reviewer, reason = None, 'No explicit routing preference; operator clarification required'
    reviewer_id = policy['reviewers'][reviewer]['github_user_id'] if reviewer else None
    state = initial(issue['user']['login'], reviewer, REFERRAL_CHOICES[sections['Referral preference']],
                    applicant_id=applicant_id, reviewer_id=reviewer_id)
    state.update(initialized=True, ledger_version=2, selections=selected, allow_empty_route=allow_empty_route, routing_reason=reason,
                 routing_status='resolved' if reviewer else 'unresolved', public_consent=True, processed=[])
    return state


def record_state(repo, number, state):
    api(f'repos/{repo}/issues/{number}/comments', {'body': MARKER + '\n' + json.dumps(state, sort_keys=True)})


def add_reviewer(repo, number, reviewer, record):
    if reviewer:
        reviewer_id = record.get('github_user_id')
        if not positive_id(reviewer_id):
            raise ValueError('Reviewer identity requires review')
        current = api(f'user/{reviewer_id}')
        login = current.get('login')
        if (not positive_id(current.get('id')) or current['id'] != reviewer_id or
            not isinstance(login, str) or
            not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?', login)):
            raise ValueError('Reviewer identity requires review')
        # Resolve current login from the immutable ID; never use the policy alias
        # as a GitHub assignee. The additive endpoint preserves existing owners.
        api(f'repos/{repo}/issues/{number}/assignees', {'assignees': [login]}, 'POST')


def run():
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text(encoding='utf-8'))
    issue = event['issue']
    if issue.get('pull_request') or not any(l['name'] == 'type:application' for l in issue['labels']):
        return
    repo, number = os.environ['GITHUB_REPOSITORY'], issue['number']
    policy = json.loads((ROOT / 'data/authority.v2.json').read_text(encoding='utf-8'))
    directory = json.loads((ROOT / 'data/directory.v1.json').read_text(encoding='utf-8'))
    all_comments = comments(repo, number)
    state = read_ledger(all_comments, issue['user']['login'], issue['user'].get('id'))
    if not state.get('initialized'):
        # Only a new issue without a trusted V2 ledger can initialize.
        # Never reset decisions or reinterpret historical consent.
        if state['history'] or state['events'] or state.get('processed'):
            raise ValueError('Ledger initialization requires manual review')
        state = initialize(issue, directory, policy)
        record_state(repo, number, state)
        if state['reviewer']:
            add_reviewer(repo, number, state['reviewer'], policy['reviewers'][state['reviewer']])
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
            if not positive_id(c['user'].get('id')):
                raise ValueError('Command identity requires review')
            command.update(id=str(c['id']), actor=c['user']['login'], actor_id=c['user']['id'],
                           at=c['created_at'], source=c['html_url'])
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
        add_reviewer(repo, number, updated['reviewer'], policy['reviewers'][updated['reviewer']])


if __name__ == '__main__':
    run()
