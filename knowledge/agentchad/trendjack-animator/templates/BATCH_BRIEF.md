# <AD NAME> - production brief for one batch of shots

> Template for long ads (60+ shots) that are split across several background helpers. Before use: replace the ad
> name, the ad folder path, the look line, the hero description and the Starpop ids below with this ad's own.
> The user has already said yes to the full estimate for every shot in this batch; the helper never asks again
> and never spends outside the list.

You produce stills and 5-second animated clips for a list of shots of an animated ad in the look
"<LOOK LINE FROM ad.json>", in the language <LANGUAGE>, using the Starpop MCP tools (load them with ToolSearch:
`select:mcp__starpop__create_image,mcp__starpop__create_video,mcp__starpop__wait_for_job,mcp__starpop__get_job`).

## Fixed scope (use exactly this in every Starpop call)

- organizationId `<<FILL>>`
- brandId `<<FILL>>`
- projectId `<<FILL>>`
- sessionId `<<FILL>>`
- productRef null, folderId null

## Inputs

- Your shot list: `batches/<batch>.json` in the ad folder `<AD FOLDER>` (the full path of this ad's project folder).
  Each shot has `id`, `still` (the full image prompt), `refs` (names), `ref_ids` (the `image:` references in the
  same order, attach them in that order), `motion` (the camera + action for the clip) and optionally `clip_model`.

## For every shot, in this order

1. **Still:** `create_image` with model `nano-banana-2.1`, aspectRatio `9:16`, resolution `1K`, quality null,
   background null, enhancePromptMode null, outputCount 1, prompt = `still`, references = `ref_ids`.
   clientRequestId = `<CODE>.<n>-still-<id>-v1` (use `-v2` for a retry).
   If the call goes to the background or returns status running, use `wait_for_job` with the jobId.
2. **Download** the still at once (links expire after 15 minutes) with curl to `stills/<id>.png` in the ad folder.
   If the link has expired, call `get_job` for a fresh one.
3. **Check it** (Read the png): the right people (the hero's face stays the same person: <HERO DESCRIPTION, e.g.
   dark wavy shoulder-length hair, light-brown eyes>), right clothes for the shot, no extra or missing fingers, no
   readable text except the product label, the action matches the prompt. If clearly wrong, regenerate ONCE with a
   sharpened prompt; if still wrong, keep the better one and note it.
4. **Clip:** `create_video` with model = the shot's `clip_model` if set, else `minimax-h3-max-turbo`, resolution
   `768p`, aspectRatio `9:16`, durationSeconds 5, outputCount 1, multiPrompt null,
   guidance `{"type":"frames","firstFrame":"<the still's image: ref>","lastFrame":null}`, prompt:

   ```
   Style: <LOOK LINE FROM ad.json>, filmic grade.

   Shot 1: <motion, minus the 'Camera:' sentence>
   Camera: <the 'Camera:' sentence from motion>

   Constraints: No captions. No text. Nobody talks or sings. Same characters, clothes and set as the first frame.
   ```

   clientRequestId = `<CODE>.<n>-clip-<id>-v1`. Wait for it, then download to `clips/<id>.mp4` at once.

5. Append one line per shot to `batches/<batch>_done.jsonl`:
   `{"id": ..., "still_ref": "image:...", "clip_ref": "video:...", "note": "..."}`

Run 3 shots in parallel at most (Starpop queues heavy load). `wait_for_job` may need to be called several times for one job.

## Rules

- Spend only on these shots: max 2 stills and 1 clip per shot. Never generate audio or music.
- Never print or store anything except into the ad folder files above. Do not edit ad.json.
- Report back in under 150 words: done count, retries, any shot you are unhappy with and why.
- Never ask the user anything; decide within these rules and note doubts in your report.
- A download that returns 403 or a non-image file means the link expired: call `get_job` for a fresh link and retry.
