## assets/icon.png
- Date: 2026-10-30
- Tool and model: Codex CLI 0.164.0 image_generation (built-in)
- Seed: not supported
- Reference images: none
- Prompt:

```text
Use your image generation capability to create ONE image. Do not modify any other files.

Square 1024x1024, flat plain white background, transparent-style empty margin of 15% on all sides. Palette hex values: outline #0F766E, glow #14B8A6, one spark #FBBF24, ground #042F2E not used in the image. Negative list: no text, letters, numbers, words, logos or brand marks, no people, faces, hands, no gradients on background, no photo realism, no extra objects, no third-party IP.

NEON NIGHT REPO ICON · Pick-Your-AI/pick-your-ai-volunteers

Create one square 1024 × 1024 px image of a single repository glyph.
Use a simple geometric silhouette with a luminous outline and one accent spark.
Keep the background empty and the glyph inside the central 688 × 688 px square.
Size class TALL: spans close to the full 688 px height and is about 400 to 600 px wide.

GLYPH: Volunteer roster clipboard. A rounded-rectangle clipboard outline seen face-on with a small clip tab at the top centre, and three roster rows inside, each a small circle bullet followed by a short horizontal line; a check mark sits inside the first bullet to suggest placement and onboarding. No people or faces.
SPARK PLACEMENT: A small filled four-point spark just outside the top right corner of the clipboard.
PALETTE: outline #0F766E, glow #14B8A6; one spark in #FBBF24.
The spark is the only filled shape and the only element in #FBBF24; keep the
glyph outline in #0F766E so the spark remains distinct at small sizes.

No text, letters, numbers, words, logos, brand marks, human figures or third-party IP.

Produce four candidates. Use the tool's default seed.
The lock pass renders assets/icon.png as a flat glyph in the family's light-surface
inks, without a tile or glow. Do not render the repository name in the image.
```

- Candidates: 1; selected: 1 (reason: passes icon QA, no text, teal/amber only)
- Post-processing: showcase.py 1.0.0 content icon normalize --ground transparent; output sha256 bd8d294fb42f30a6ff6b4194aa1e7f42946f669bb410345cc26170912781c131; size 185941 bytes
