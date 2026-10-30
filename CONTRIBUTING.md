# Contributing

Follow the [organization rules](https://github.com/Pick-Your-AI/.github/blob/main/CONTRIBUTING.md). Changes use branches and PRs. An independent approval of the latest push is required before merge. Never bypass reviews or protections to finish a task.

Search this hub, the organization and [prior work](docs/prior-work.md) before proposing changes. Record what you extend and preserve related owners. Schema and governance changes require explicit review; updating a JSON file is not authority to appoint people.

Use Python 3.12 in an isolated environment:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/generate.py
python scripts/validate.py
python -m unittest discover -s tests -v
python scripts/generate.py --check
```

On Windows use `.venv/Scripts/python.exe` instead of activation. All fixture identities are synthetic. Do not create fake public volunteers or send test invitations. Do not commit application exports, private data, secrets, or raw organization membership snapshots. The directory contains public entity metadata only.

Review changes to authority, workflow permissions, schemas, generated forms and public/private boundaries explicitly. Run live link verification and Project readback separately; unit tests do not establish GitHub access, delivery or legal status.
