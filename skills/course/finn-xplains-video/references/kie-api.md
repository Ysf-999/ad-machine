# KIE image and optional video generation

Documentation checked 2026-09-05. Before the first paid submission in a new session, refresh the selected model's schema from [KIE's index](https://docs.kie.ai/llms.txt). These are concrete starting settings, not a promise that names, prices or limits never change. Fetch the linked `.md` version when the HTML page omits schema fields. Use the explicit model below, not a similarly named older endpoint.

## Shared execution

The [market API](https://docs.kie.ai/market/quickstart) uses:

- `POST https://api.kie.ai/api/v1/jobs/createTask` with `Authorization: Bearer` from `KIE_API_KEY` and JSON `{ "model": "...", "input": { ... } }`.
- `GET https://api.kie.ai/api/v1/jobs/recordInfo?taskId=...` to resume/poll the returned `data.taskId`.
- `GET https://api.kie.ai/api/v1/chat/credit` for remaining credits; this is not a model-price quote. Verify current model prices when budgeting; do not hardcode a total from old generic credit ranges.

Use an available KIE connector if it exposes the exact model and reference inputs. Otherwise use a small local API client reading the environment or project-root `.env`. Never place the key in prompts, JSON payload files, logs, command arguments, or delivered files. If credentials are unavailable, follow [beginner setup](setup-and-intake.md) to obtain access; complete independent prompts/board work while generation is pending. Do not substitute another image provider unless the operator explicitly selects it during setup, then use that platform's verified adapter rather than these KIE-specific fields.

Keep `jobs.jsonl` in the project: asset ID/version, exact request without secrets, input file hashes and URL roles, task ID, current state, returned URLs, local files, and inspection result. Save and flush each task ID to disk immediately when received, before polling or starting another task. Reuse existing tasks on resume. For a connection timeout after submission, inspect/reconcile the job state; do not blindly repeat a paid POST. If no task ID can be recovered, record the submission as uncertain and resolve it before retrying.

Inspect both HTTP and JSON status. Creation success only means accepted. Poll at modest intervals, e.g. 10–20 seconds with backoff, until terminal success/failure; a local wait timeout leaves a pending task to resume. Do not invent a callback URL. On terminal success, parse `data.resultJson` as JSON when returned as a string, then use its actual `resultUrls`. Handle `failCode`/`failMsg` on failure. Download generated results promptly into the task project, inspect the files, and record their paths. Polling and downloading an already-created task does not create another generation charge.

## Upload and reference identity

For local references, [KIE file upload](https://docs.kie.ai/file-upload-api/quickstart) documents multipart POST to `https://kieai.redpandaai.co/api/file-stream-upload` with `file`, `uploadPath`, and optional `fileName`, using the same Bearer credential. Persist the returned usable `data.downloadUrl`/`data.fileUrl` and `expiresAt`; verify accessibility before generation. Respect the selected model's file constraints, including when upload accepts a larger file than that model can use.

Send only the images required for this request. A local path, scene ID, or invented `@Image` label is not an API reference. Ordered URLs and prompt descriptions must agree. Keep a local master because uploaded and generated URLs may expire; refresh the upload without re-generating the artwork. The full voiceover stays local for assembly unless a separately requested capability actually needs its upload.

## Images — GPT Image 2

Official schemas: [text to image](https://docs.kie.ai/market/gpt/gpt-image-2-text-to-image), [image to image](https://docs.kie.ai/market/gpt/gpt-image-2-image-to-image).

Use `gpt-image-2-text-to-image` for a new reference without input artwork. Use `gpt-image-2-image-to-image` whenever supplied/approved character, style, set or product images must guide the result. The latter takes **`input_urls`**, not `image_urls`, with at most 16 URLs. Prompts support up to 20,000 characters; use only the relevant detail.

Default scene setting: explicit `aspect_ratio: "9:16"`, `resolution: "2K"`. Character sheets may use explicit `"3:2"` at `"2K"`. Honor another user ratio. `auto`/omitted aspect ratio is restricted to 1K; square 4K is unsupported. Omit `background` at 2K/4K because that field is supported only at 1K. Check the schema for other ratio/resolution combinations.

Request template — replace descriptive values with the finished prompt and actual accessible URLs:

```json
{
  "model": "gpt-image-2-image-to-image",
  "input": {
    "prompt": "Finished scene prompt including the ordered reference roles",
    "input_urls": ["https://actual-accessible-host/approved-character.png"],
    "aspect_ratio": "9:16",
    "resolution": "2K"
  }
}
```

For text-to-image, change the model to `gpt-image-2-text-to-image` and omit `input_urls`. Do not invent seed, batch-count, or negative-prompt fields. Generate each requested asset as its own tracked task unless the refreshed schema explicitly supports another batching mechanism. If the user requests another KIE image model, read that model's schema and preserve the same creative/reference workflow.

## Optional video — Grok Imagine 1.5

Official schema: [Grok Imagine Video 1.5 Preview](https://docs.kie.ai/market/grok-imagine/1-5-preview).

Exact model: `grok-imagine-video-1-5-preview`. It accepts image input despite the page's generic text-to-video introduction. Use one approved scene image via **`image_urls`**. Prompt maximum: 4096 characters. `duration` is an **integer**, 1–15 seconds. Supported resolutions: 480p, 720p, 1080p. Up to seven images are documented, but 1080p supports only one. For this workflow use one complete first-frame image; omit `aspect_ratio` because the schema says it is ineffective with a single image.

```json
{
  "model": "grok-imagine-video-1-5-preview",
  "input": {
    "prompt": "Finished motion prompt grounded in the approved first frame",
    "image_urls": ["https://actual-accessible-host/approved-S001.png"],
    "resolution": "1080p",
    "duration": 4
  }
}
```

The image schema permits JPEG, PNG or WebP up to 20MB. Choose `ceil(scene_seconds)` within 1–15, optionally adding an authorized trim handle if the action needs it. Record the exact retained interval. Do not add Kling's `sound` field here: it is not documented in this schema. Request silent performance and discard generated audio during assembly so the user's voiceover remains the master.

## Optional video — Kling 3

Official schema: [Kling 3.0](https://docs.kie.ai/market/kling/kling-3-0).

Exact model: `kling-3.0/video`. Use **`image_urls`**; one image is the first frame, and two are first/last frames in single-shot mode. Use `multi_shots: false`, `sound: false`, and `mode: "pro"` by default. `duration` is a **string integer** from `"3"` to `"15"`. Pro portrait output is documented as 1080×1920. The current schema marks `aspect_ratio` and `multi_prompt` required, although the prose describes them as optional/conditional. Keep an explicit ratio matching the first frame and an empty `multi_prompt` array for single-shot requests; refresh this discrepancy before execution.

```json
{
  "model": "kling-3.0/video",
  "input": {
    "prompt": "Finished single-scene motion prompt",
    "image_urls": ["https://actual-accessible-host/approved-S001.png"],
    "duration": "4",
    "aspect_ratio": "9:16",
    "mode": "pro",
    "multi_shots": false,
    "multi_prompt": [],
    "sound": false
  }
}
```

For a scene shorter than three seconds, request the supported three-second clip and trim the visual; do not lengthen the voiceover. If an end-frame constraint is needed, use a real reviewed end frame. Avoid introducing element or multi-shot modes for ordinary single-scene animation; if specifically needed, read those sections of the current schema and ensure all referenced elements exist. A written `@element_name` alone creates no reference.
