"""Build public-only exports, directory pages and GitHub forms from canonical v1."""
import argparse
import json
from pathlib import Path
import yaml
from program import public_export

ROOT = Path(__file__).resolve().parents[1]


def field(kind, id, label, **attributes):
    required = attributes.pop('required', False)
    return {'type': kind, 'id': id, 'attributes': {'label': label, **attributes}, 'validations': {'required': required}}


def artifacts(d):
    result = {'public/directory.v1.json': json.dumps(public_export(d), indent=2, ensure_ascii=False) + '\n'}
    result['docs/directory.md'] = '# Team / Repository / Project directory\n\nGenerated from [canonical v1 records](../data/directory.v1.json). Team membership is distinct from decision authority. Relationships are many-to-many. Private repositories and member identities are excluded.\n\n' + '\n\n'.join('## ' + kind.title() + '\n\n| ID | Name | Related records |\n| --- | --- | --- |\n' + '\n'.join('| `' + r['id'] + '` | [' + r['name'] + '](' + r['github']['url'] + ') | ' + ', '.join(r.get('team_ids', []) + r.get('repository_ids', []) + r.get('project_ids', [])) + ' |' for r in d[kind]) for kind in ('teams', 'repositories', 'projects')) + '\n'
    result['docs/opportunities.md'] = '# Opportunities and staffing needs\n\nNo confirmed recruiting capacity is recorded yet. You can submit an expression of interest; acceptance waits for a designated reviewer. Null openings means unknown, never zero. These are work areas, not promises of placement.\n\n| Opportunity | Need | Priority | Recruiting | Onboarding | Evidence |\n| --- | --- | --- | --- | --- | --- |\n' + '\n'.join('| `' + o['id'] + '` — ' + o['name'] + ' | ' + o['staffing_need'] + ' | ' + o['priority'] + ' | ' + o['status'] + ' | ' + o['onboarding_capacity'] + ' | [source](' + o['evidence'][-1] + ') |' for o in d['opportunities']) + '\n'
    body = [{'type': 'markdown', 'attributes': {'value': '**Public submission:** your issue, edits, comments and status are visible to everyone. Use only your GitHub identity and public-safe information. Do not include legal name, email, phone, address, credentials, health or other sensitive details. There is no confidential intake or guaranteed deletion from history. Acceptance does not grant access.'}}]
    for kind, label in [('opportunities', 'Preferred opportunity'), ('teams', 'Preferred team'), ('repositories', 'Preferred repository'), ('projects', 'Preferred Project')]:
        body.append(field('dropdown', kind, label, options=['Help me find where I am most useful', 'No preference'] + [r['id'] + ' — ' + r['name'] for r in d[kind]], multiple=True))
    body += [field('dropdown', 'role', 'Desired role', options=['Help me choose'] + [r['id'] + ' — ' + r['name'] for r in d['roles']], required=True), field('textarea', 'alternatives', 'Alternative interests and useful skills', required=True, description='Mention public work examples only if you want to share them.'), field('textarea', 'availability', 'Availability', required=True, description='Approximate time and preferred pace, or to be agreed; no personal schedule details needed.'), field('textarea', 'mentoring', 'Mentoring and onboarding support', required=True, description='What support would help? Do not include sensitive personal information.'), field('dropdown', 'referral', 'Referral preference', required=True, options=['Ask me before each placement change', 'Do not refer me']), field('checkboxes', 'consent', 'Visibility consent', options=[{'label': 'I understand this is public and consent to public application review. Each proposed placement change needs my agreement.', 'required': True}])]
    forms = {'application.yml': {'name': 'Volunteer application / expression of interest', 'description': 'Public-safe volunteer interests and support needs', 'title': '[Application] ', 'labels': ['type:application'], 'body': body}}
    for file, title, label, description in [('opportunity.yml', 'Propose or update an opportunity', 'type:opportunity', 'A work need; do not include applicant details.'), ('referral.yml', 'Request referral or placement change', 'type:referral', 'Link your application and proposed destination; no change occurs without your agreement.'), ('availability.yml', 'Staffing or reviewer availability update', 'type:availability', 'Record evidence of role authority, availability and onboarding capacity; membership alone is insufficient.')]:
        forms[file] = {'name': title, 'description': description, 'labels': [label], 'body': [{'type': 'markdown', 'attributes': {'value': '**Public issue.** Do not include private applicant or personnel details.'}}, field('input', 'record', 'Canonical record ID or application issue URL', required=True), field('textarea', 'change', 'Proposed change and reason', required=True), field('textarea', 'evidence', 'Evidence, authority and receiving reviewer', required=True), field('textarea', 'capacity', 'Openings, time, onboarding capacity and verification date', description='Use unknown when not confirmed; do not infer a vacancy from member count.')]}
    for filename, form in forms.items():
        result['.github/ISSUE_TEMPLATE/' + filename] = yaml.safe_dump(form, sort_keys=False, allow_unicode=True, width=120)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    for name, content in artifacts(json.loads((ROOT / 'data/directory.v1.json').read_text(encoding='utf-8'))).items():
        path = ROOT / name
        if args.check:
            if not path.exists() or path.read_text(encoding='utf-8') != content:
                raise SystemExit('Generated file differs: ' + name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8', newline='\n')


if __name__ == '__main__':
    main()
