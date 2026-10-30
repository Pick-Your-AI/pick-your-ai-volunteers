"""Volunteer program v1: pure, deterministic policy enforcement. No network side effects."""
import copy
from datetime import datetime, timezone, timedelta


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


def initial(applicant, route=None, referral_preference='ask_each_time'):
    return {'state': 'new', 'applicant': applicant, 'reviewer': route, 'visited': [route] if route else [], 'pending': None, 'history': [], 'events': [], 'referral_preference': referral_preference}


def resolve_route(directory, policy, selections, now=None):
    """Resolve only approved routes; membership and access never imply authority.

    Conflicting multi-select routes require operator clarification. Lower roles
    are only used automatically when a prior decision approved that fallback.
    """
    now = now or datetime.now(timezone.utc)
    known = {r['id'] for kind in ('teams', 'repositories', 'projects', 'opportunities') for r in directory[kind]}
    if not policy['enabled'] or not policy.get('approval_reference'):
        return None, 'Decision authority not activated'
    chosen = sorted(set(selections) & known)
    routes = [policy.get('routes', {}).get(id) for id in chosen]
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
    fallback = policy['fallbacks'].get('empty') if not route else None
    if fallback:
        try:
            _available(policy, fallback, now)
            return fallback, 'Explicitly approved empty-route fallback'
        except ValueError:
            pass
    return None, 'No available approved route; request escalation authorization'


def transition(current, event, policy, now=None):
    """Actor and source come from trusted GitHub metadata, never user JSON."""
    now = now or datetime.now(timezone.utc)
    required = {'id', 'actor', 'at', 'source', 'action', 'reason'}
    if not required <= event.keys() or not isinstance(event['reason'], str) or not event['reason'].strip() or len(event['reason']) > 500:
        raise ValueError('Incomplete or oversized decision')
    if event['id'] in current['events']:
        return copy.deepcopy(current)
    action, actor = event['action'], event['actor']
    old = current['state']
    s = copy.deepcopy(current)
    terminal = old in ('withdrawn', 'declined', 'closed')
    if terminal:
        raise ValueError('Terminal state')
    if action == 'withdraw':
        if actor != s['applicant']:
            raise ValueError('Only applicant may withdraw')
        s['state'], s['pending'] = 'withdrawn', None
    elif action == 'agree_referral':
        if actor != s['applicant'] or old != 'referral_pending':
            raise ValueError('Applicant agreement required')
        destination = s['pending']
        _available(policy, destination, now)
        s.update(state='awaiting_reviewer', reviewer=destination, pending=None)
        s['visited'].append(destination)
    elif action == 'decline_referral':
        if actor != s['applicant'] or old != 'referral_pending':
            raise ValueError('Applicant decision required')
        s.update(state='awaiting_reviewer', pending=None)
    elif action == 'request_escalation' and actor == s['applicant']:
        if old not in ('new', 'awaiting_reviewer', 'awaiting_information') or not policy['enabled'] or not policy.get('approval_reference'):
            raise ValueError('Escalation request unavailable')
        reviewer = policy['reviewers'].get(s['reviewer'])
        dest = event.get('destination')
        if not reviewer or dest not in reviewer['destinations'] or dest in s['visited']:
            raise ValueError('No approved escalation destination')
        if event.get('unavailability') not in ('no_designated_reviewer', 'recorded_absence', 'conflict_of_interest', 'response_period_expired'):
            raise ValueError('Unavailability reason required')
        _available(policy, dest, now)
        s.update(state='awaiting_escalation_approval', pending=dest)
    else:
        _available(policy, actor, now)
        reviewer = policy['reviewers'][actor]
        if action not in reviewer['actions']:
            raise ValueError('Action outside mandate')
        if action not in ('approve_escalation', 'reject_escalation') and actor != s['reviewer']:
            # An explicitly approved empty-route fallback may receive a new application.
            if not (old == 'new' and s['reviewer'] is None and policy['fallbacks'].get('empty') == actor):
                raise ValueError('Not current reviewer')
            s['reviewer'] = actor
            s['visited'].append(actor)
        if action in ('refer', 'request_escalation'):
            if action == 'refer' and s.get('referral_preference') == 'do_not_refer':
                raise ValueError('Applicant opted out of referrals')
            if old not in ('new', 'awaiting_reviewer', 'awaiting_information', 'active'):
                raise ValueError('Invalid source state')
            dest = event.get('destination')
            if dest in s['visited'] or dest == actor:
                raise ValueError('Routing loop')
            _available(policy, dest, now)
            if dest not in reviewer['destinations']:
                raise ValueError('Destination outside mandate')
            if action == 'request_escalation' and event.get('unavailability') not in ('no_designated_reviewer', 'recorded_absence', 'conflict_of_interest', 'response_period_expired'):
                raise ValueError('Unavailability reason required')
            s.update(state='referral_pending' if action == 'refer' else 'awaiting_escalation_approval', pending=dest)
        elif action in ('approve_escalation', 'reject_escalation'):
            if old != 'awaiting_escalation_approval' or actor not in policy['reviewers'][s['reviewer']]['escalation_approvers']:
                raise ValueError('Escalation approval required')
            if action == 'approve_escalation':
                _available(policy, s['pending'], now)
                # Escalation changes reviewer, not volunteer placement.
                s['reviewer'] = s['pending']
                s['visited'].append(s['pending'])
            s.update(state='awaiting_reviewer', pending=None)
        else:
            targets = {
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
            if action not in targets or old not in targets[action][0]:
                raise ValueError('Invalid transition')
            if action.startswith('record_invitation') and not event.get('receipt'):
                raise ValueError('Verified invitation receipt required')
            s['state'] = targets[action][1]
    s['history'].append({'previous': old, 'new': s['state'], **event, 'receiving_reviewer': s['reviewer']})
    s['events'].append(event['id'])
    return s


def _available(policy, actor, now):
    if not policy['enabled'] or not policy.get('approval_reference'):
        raise ValueError('Decision authority not activated')
    reviewer = policy['reviewers'].get(actor)
    if not reviewer or reviewer['availability'] != 'available' or not fresh(reviewer['verified_at'], now) or not reviewer.get('approval_reference'):
        raise ValueError('No current available authorized reviewer')


def public_export(directory):
    """Strict public catalog allowlist: never exports application content or policy identities."""
    return {key: copy.deepcopy(directory[key]) for key in ('schema_version', 'verified_at', 'teams', 'repositories', 'projects', 'roles', 'opportunities', 'routing_policies')}
