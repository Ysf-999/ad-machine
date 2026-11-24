# AI Ad Machine

An agentic system that makes 9:16 video ads with AI: you tell Claude Code what ad you want, and it writes the
script, makes the voice, images and video clips, edits them (captions, music, SFX, b-roll, hook box), checks the
result against your taste rules, and sends it to you for review. It also edits real creator footage. A cloud side
(Modal) can run many ads at once, and a local dashboard (the "ad board") shows what's in progress, what needs your
approval and what everything cost.

**New here? Open [SETUP.md](SETUP.md).** It walks you through everything in order (about an hour the first time).

## What's inside

| Folder | What it is |
|---|---|
| `brand/` | Your brand and product description (`brand.json`) and product photos. The only place you describe your brand. |
| `tools/` | All the scripts: `ad.py` (AI ads), `rawedit.py` (real footage), `preflight.py` (final checks), `feedback.py` (learning from your notes) |
| `cloud/` | The cloud controller (Modal) and the ad board dashboard |
| `skills/` | Claude Code skills: drama ads, animated ads, song ads, UGC talking heads, whiteboard/chalkboard, raw footage editor |
| `course/`, `knowledge/` | The course notes the methods come from |
| `feedback/` | Starter taste rules. They grow from your own review notes |
| `library/` | Free SFX and fonts. Add your own music to `library/music/` |

## What you pay for (your own accounts)

kie.ai (image, video and music generation, pay per credit) · ElevenLabs (voices) · Claude Code (Pro or Max plan;
no API key needed) · Modal (cloud, optional; capped at $10/month by default). Composio, Frame.io, Google Drive and
Slack are optional and have free tiers.
