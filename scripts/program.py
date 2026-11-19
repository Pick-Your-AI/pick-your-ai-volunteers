"""Volunteer program: pure, deterministic policy enforcement. No network side effects."""
import copy
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit


def fresh(value, now, days=30):
    try:
        observed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return timedelta(0) <= now - observed <= timedelta(days=days)
    except (ValueError, TypeError, AttributeError):
        return False


def recommend(directory, interests, skills, hours=None, needs_mentor=False, now=None):
    """Ranks opportunities, never people; ineligible opportunities remain browsable."""
    now = now or datetime.now(timezone.utc)
    results = []
    for o in directory['opportunities']:
        if o['status'] != 'recruiting' or not fresh(o['verified_at'], now):
            continue
        if o['onboarding_capacity'] != 'confirmed':
            continue
        if needs_mentor and o['mentoring_capacity'] != 'confirmed':
            continue
        if o['minimum_hours'] is not None and (hours is None or hours < o['minimum_hours']):
            continue
        matches = sorted(set(interests) & set(o['team_ids'] + o['repository_ids'] + o['project_ids'] + o['role_ids'] + [o['id']]))
        skill_matches = sorted(set(skills) & set(o['skills']))
        reasons = []
        if matches:
            reasons.append('Matches your selected interests')
        if skill_matches:
            reasons.append('Uses your skills: ' + ', '.join(skill_matches))
        if o['beginner_suitability'] == 'yes':
            reasons.append('Beginner-friendly')
        reasons.append('Onboarding support confirmed')
        if needs_mentor:
            reasons.append('Mentoring support confirmed')
        if o['staffing_need'] in ('confirmed_vacancy', 'leader_needed', 'maintainer_needed', 'additional_help_wanted'):
            reasons.append('Documented staffing need: ' + o['staffing_need'].replace('_', ' '))
        results.append({'id': o['id'], 'reasons': reasons, '_order': (-bool(matches), -len(skill_matches), o['priority'] != 'high', o['id'])})
    results.sort(key=lambda r: r['_order'])
    return [{k: v for k, v in r.items() if k != '_order'} for r in results]


REVIEW_STATES = {'new', 'awaiting_reviewer', 'awaiting_information', 'accepted',
                 'onboarding', 'invitation_requested', 'invitation_sent',
                 'invitation_accepted', 'active'}
TARGETS = {
    'request_information': ({'new', 'awaiting_reviewer', 'awaiting_information'}, 'awaiting_information'),
    'accept': ({'new', 'awaiting_reviewer', 'awaiting_information'}, 'accepted'),
    'decline': ({'new', 'awaiting_reviewer', 'awaiting_information'}, 'declined'),
    'begin_onboarding': ({'accepted'}, 'onboarding'),
    'request_invitation': ({'onboarding'}, 'invitation_requested'),
    'record_invitation_sent': ({'invitation_requested'}, 'invitation_sent'),
    'record_invitation_accepted': ({'invitation_sent'}, 'invitation_accepted'),
    'complete_onboarding': ({'onboarding', 'invitation_accepted'}, 'active'),
    'close': ({'active'}, 'closed'),
}
ACTIONS = set(TARGETS) | {'withdraw', 'refer', 'agree_referral', 'decline_referral',
                         'request_escalation', 'approve_escalation', 'reject_escalation'}
UNAVAILABILITY = {'no_designated_reviewer', 'recorded_absence',
                  'conflict_of_interest', 'response_period_expired'}


def account_id(value):
    if type(value) is not int or value <= 0:
        raise ValueError('Stable account identity required')
    return value


def initial(applicant, route=None, referral_preference='ask_each_time', *, applicant_id, reviewer_id=None):
    account_id(applicant_id)
    if route is not None:
        account_id(reviewer_id)
    elif reviewer_id is not None:
        raise ValueError('Unassigned application cannot have reviewer identity')
    return {'state': 'new', 'applicant': applicant, 'applicant_id': applicant_id,
            'reviewer': route, 'reviewer_id': reviewer_id,
            'visited': [route] if route else [], 'visited_ids': [reviewer_id] if route else [],
            'pending': None, 'pending_reviewer_id': None, 'pending_origin': None,
            'history': [], 'events': [], 'referral_preference': referral_preference}


def resolve_route(directory, policy, selections, now=None):
    """Resolve only approved routes; membership and access never imply authority.

    Conflicting multi-select routes require operator clarification. Lower roles
    are only used automatically when a prior decision approved that fallback.
    """
    now = now or datetime.now(timezone.utc)
    known = {r['id'] for kind in ('teams', 'repositories', 'projects', 'opportunities') for r in directory[kind]}
    if policy.get('enabled') is not True or not policy.get('approval_reference'):
        return None, 'Decision authority not activated'
    if not isinstance(selections, list) or any(not isinstance(value, str) or not value for value in selections):
        return None, 'Invalid selected scopes; operator clarification required'
    chosen = sorted(set(selections))
    if not set(chosen) <= known:
        return None, 'Unknown selected scope; operator clarification required'
    routes = [policy.get('routes', {}).get(id) for id in chosen]
    if chosen and not all(routes):
        return None, 'Selected interests include an unresolved route; operator clarification required'
    routes = [route for route in routes if route]
    if routes and any(route != routes[0] for route in routes[1:]):
        return None, 'Selected interests have different routes; operator clarification required'
    route = routes[0] if routes else []
    for index, step in enumerate(route):
        if not step.get('approval_reference') or (index and not step.get('fallback_approved')):
            continue
        try:
            _available(policy, step['reviewer'], now)
            return step['reviewer'], 'Approved ' + step['role'] + ' route'
        except ValueError:
            continue
    # The empty route is not a missing leader: an explicit mandate must cover it.
    fallback = policy['fallbacks'].get('empty') if not chosen else None
    if fallback:
        try:
            _available(policy, fallback, now)
            return fallback, 'Explicitly approved empty-route fallback'
        except ValueError:
            pass
    return None, 'No available approved route; request escalation authorization'


def transition(current, event, policy, now=None, directory=None):
    """Numeric actor identity and source are trusted metadata, never user JSON."""
    now = now or datetime.now(timezone.utc)
    _validate_event(event)
    account_id(current.get('applicant_id'))
    if event['id'] in current['events']:
        return copy.deepcopy(current)
    action, actor = event['action'], event['actor']
    is_applicant = event['actor_id'] == current['applicant_id']
    old = current['state']
    s = copy.deepcopy(current)
    terminal = old in ('withdrawn', 'declined', 'closed')
    if terminal:
        raise ValueError('Terminal state')
    if action == 'withdraw':
        if not is_applicant:
            raise ValueError('Only applicant may withdraw')
        s.update(state='withdrawn', pending=None, pending_reviewer_id=None, pending_origin=None)
    elif action == 'agree_referral':
        if not is_applicant or old != 'referral_pending':
            raise ValueError('Applicant agreement required')
        _pending_authorized(policy, s, now, 'refer')
        _complete_handoff(s, transfer=True)
    elif action == 'decline_referral':
        if not is_applicant or old != 'referral_pending':
            raise ValueError('Applicant decision required')
        _complete_handoff(s, transfer=False)
    elif action == 'request_escalation' and is_applicant:
        if old not in REVIEW_STATES or policy.get('enabled') is not True or not policy.get('approval_reference'):
            raise ValueError('Escalation request unavailable')
        _request_handoff(s, event, policy, now, 'awaiting_escalation_approval')
    else:
        actor_key = _reviewer_key(policy, event['actor_id'])
        reviewer = _available(policy, actor_key, now)
        if action not in reviewer['actions']:
            raise ValueError('Action outside mandate')
        if action not in ('approve_escalation', 'reject_escalation'):
            if s['reviewer'] is None:
                if old != 'new' or directory is None or s.get('initialized') is not True or 'selections' not in s:
                    raise ValueError('Not current reviewer; approved route required')
                if not s['selections'] and s.get('allow_empty_route') is not True:
                    raise ValueError('Explicit routing choice required')
                resolved, reason = resolve_route(directory, policy, s['selections'], now)
                if resolved != actor_key:
                    raise ValueError('Not current reviewer; approved route required')
                s.update(reviewer=resolved, reviewer_id=event['actor_id'],
                         routing_status='resolved', routing_reason=reason)
                s['visited'].append(resolved)
                s['visited_ids'].append(event['actor_id'])
            _bound_reviewer(policy, s)
            if actor_key != s['reviewer'] or event['actor_id'] != s['reviewer_id']:
                raise ValueError('Not current reviewer')
        if action in ('refer', 'request_escalation'):
            if action == 'refer' and s.get('referral_preference') == 'do_not_refer':
                raise ValueError('Applicant opted out of referrals')
            allowed = {'new', 'awaiting_reviewer', 'awaiting_information', 'active'} if action == 'refer' else REVIEW_STATES
            if old not in allowed:
                raise ValueError('Invalid source state')
            _request_handoff(s, event, policy, now,
                             'referral_pending' if action == 'refer' else 'awaiting_escalation_approval')
        elif action in ('approve_escalation', 'reject_escalation'):
            origin_reviewer = _bound_reviewer(policy, s)
            if (old != 'awaiting_escalation_approval' or
                    actor_key not in origin_reviewer['escalation_approvers'] or
                    event['actor_id'] in (s['reviewer_id'], s['pending_reviewer_id'])):
                raise ValueError('Escalation approval required')
            if action == 'approve_escalation':
                _pending_authorized(policy, s, now, 'request_escalation')
            _complete_handoff(s, transfer=action == 'approve_escalation')
        else:
            if action not in TARGETS or old not in TARGETS[action][0]:
                raise ValueError('Invalid transition')
            s['state'] = TARGETS[action][1]
    if is_applicant:
        s['applicant'] = actor  # Display only; authorization is bound to applicant_id.
    s['history'].append({'previous': old, 'new': s['state'], **event,
                         'receiving_reviewer': s['reviewer'], 'receiving_reviewer_id': s['reviewer_id']})
    s['events'].append(event['id'])
    return s


def _pending_origin(state):
    origin = state.get('pending_origin')
    if origin not in REVIEW_STATES:
        raise ValueError('Missing handoff origin; operator reconciliation required')
    return origin


def _reviewer_key(policy, github_user_id):
    account_id(github_user_id)
    matches = [key for key, r in policy['reviewers'].items()
               if type(r.get('github_user_id')) is int and r['github_user_id'] == github_user_id]
    if len(matches) != 1:
        raise ValueError('Unique approved account identity required')
    return matches[0]


def _bound_reviewer(policy, state):
    reviewer = policy['reviewers'].get(state['reviewer'])
    if (not reviewer or not reviewer.get('approval_reference') or
            account_id(reviewer.get('github_user_id')) != account_id(state.get('reviewer_id'))):
        raise ValueError('Reviewer identity requires reconciliation')
    return reviewer


def _available(policy, actor, now):
    if policy.get('enabled') is not True or not policy.get('approval_reference'):
        raise ValueError('Decision authority not activated')
    reviewer = policy['reviewers'].get(actor)
    if not reviewer or reviewer['availability'] != 'available' or not fresh(reviewer['verified_at'], now) or not reviewer.get('approval_reference'):
        raise ValueError('No current available authorized reviewer')
    if _reviewer_key(policy, account_id(reviewer.get('github_user_id'))) != actor:
        raise ValueError('Reviewer identity requires reconciliation')
    return reviewer


def _request_handoff(state, event, policy, now, pending_state):
    origin = _bound_reviewer(policy, state)
    destination = event.get('destination')
    receiver = _available(policy, destination, now)
    if destination not in origin['destinations']:
        raise ValueError('Destination outside mandate')
    if destination in state['visited'] or receiver['github_user_id'] in state['visited_ids']:
        raise ValueError('Routing loop')
    state.update(pending=destination, pending_reviewer_id=receiver['github_user_id'],
                 pending_origin=state['state'], state=pending_state)


def _pending_authorized(policy, state, now, action):
    origin = _bound_reviewer(policy, state)
    receiver = _available(policy, state['pending'], now)
    if (state['pending'] not in origin['destinations'] or action not in origin['actions'] or
            receiver['github_user_id'] != account_id(state.get('pending_reviewer_id'))):
        raise ValueError('Pending transfer authorization requires reconciliation')


def _complete_handoff(state, transfer):
    origin = _pending_origin(state)
    if transfer:
        state['reviewer'], state['reviewer_id'] = state['pending'], state['pending_reviewer_id']
        state['visited'].append(state['reviewer'])
        state['visited_ids'].append(state['reviewer_id'])
    state.update(state=origin, pending=None, pending_reviewer_id=None, pending_origin=None)


def _validate_event(event):
    required = {'id', 'actor', 'actor_id', 'at', 'source', 'action', 'reason'}
    optional = {'destination', 'receipt', 'unavailability'}
    if not required <= event.keys() or set(event) - required - optional:
        raise ValueError('Incomplete or unknown decision fields')
    account_id(event['actor_id'])
    if any(not isinstance(event[k], str) or not event[k].strip()
           for k in (required - {'actor_id'}) | (optional & event.keys())):
        raise ValueError('Decision fields must be nonempty strings')
    if len(event['reason']) > 500 or event['action'] not in ACTIONS:
        raise ValueError('Invalid action or oversized reason')
    if 'destination' in event and len(event['destination']) > 128:
        raise ValueError('Oversized destination')
    if 'receipt' in event:
        receipt = event['receipt']
        parsed = urlsplit(receipt)
        if (len(receipt) > 2048 or parsed.scheme not in ('https', 'http') or not parsed.hostname or
                parsed.username is not None or parsed.password is not None or
                any(c.isspace() for c in receipt)):
            raise ValueError('Public HTTP(S) receipt reference required')
    if event['action'].startswith('record_invitation') and 'receipt' not in event:
        raise ValueError('Operator receipt reference required')
    if 'unavailability' in event and event['unavailability'] not in UNAVAILABILITY:
        raise ValueError('Invalid unavailability reason')
    if event['action'] == 'request_escalation' and 'unavailability' not in event:
        raise ValueError('Unavailability reason required')
    if event['action'] in ('refer', 'request_escalation') and 'destination' not in event:
        raise ValueError('Destination required')


def public_export(directory):
    """Strict public catalog allowlist: never exports application content or policy identities."""
    return {key: copy.deepcopy(directory[key]) for key in ('schema_version', 'verified_at', 'teams', 'repositories', 'projects', 'roles', 'opportunities', 'routing_policies')}
