# DRAMA AD MACHINE — SOP v1.2
A complete operating manual for producing AI drama ads (script → cast → voices → video → QC → master) with Claude Code + kie.ai + ElevenLabs.

**How to use this document (for the operator):** put this file in a project folder, open Claude Code there, and say:
> Read DRAMA_AD_SOP.md and follow it. Give me a drama ad for [PRODUCT]. Here's my research: [paste research / VOC / problems].

Claude will ask for anything missing from Part 0, then run the stages in Part 4, pausing at every APPROVAL GATE for your yes. You judge scripts, faces, voices and pilots; it does everything else.

**For Claude:** treat this file as binding instructions. Never skip a gate. Never spend on generation before the gate that authorizes it.

---

## PART 0 — INTAKE (what the operator must provide)

Ask for these once, all together, and only what's missing:

1. **Product**: name, format (dropper / softgel / powder), how it's taken ("a dropper every morning"), price-irrelevant.
2. **The true criteria** that separate it from cheap versions (sourcing, process, form). Must be REAL — never invent. These become "the tell."
3. **The true scarcity reason** (harvest windows, aging time, small farms). Real only. This becomes the end card.
4. **Condition / angle**: the health problem, the FELT symptom (something a person does with their body: pressing toes, rubbing a chest), and the feared endpoint if unchecked (the needle for life, the amputation, the heart that quits). Fear must be concrete and staged, never vague.
5. **Avatar**: who the ad is for — age, sex, culture, world. The cast and setting come from their life (a cookout, a park, a garage, a bridal shop).
6. **The identity event**: a physical activity the avatar's world recognizes, that the condition threatens, and that can be handed to a grandchild/child at the end.
7. **Mechanism, in plain words**: how the problem works in the body and how the product interrupts it — grade 3-4 language ("your food turns to sugar too fast… it makes a compound that slows the sugar").
8. **Words to avoid** (compliance) and the link destination.

---

## PART 1 — HOW TO WRITE ONE (the skeleton)

Ten blocks, fixed order, fixed approximate lengths (total 4:00–5:30). Every block exists to do ONE job.

| # | block | ~len | job |
|---|---|---|---|
| 1 | COLD OPEN | 20s | Inside the identity event, warm. Then the crack: the symptom happens and a LOVED ONE sees it. Denial: "I said I'm fine." |
| 2 | THE WITNESS | 20–30s | Spouse/child installs stakes with both ends of the bloodline: the ancestor lost to this ("Your father said that too… his heart quit at 61") and the descendant who'd lose out ("a little boy who won't remember you"). Ends with the order: "You need to fix this." |
| 3 | THE DOCTOR | 25–40s | The number(s), plainly. The template advice every viewer has heard (cut carbs, lose weight, walk, recheck; the pills; "we manage it"). The refusal carries a lived reason — what the conventional fix did to the ancestor. The doctor supplies URGENCY, never the answer: "Then you find something else. But you find it fast." |
| 4 | RESEARCH | 7s | Phone screen: two "How to ___" searches. Nothing else. |
| 5 | THE PEER | 50–60s | The friend who HID it ("I didn't want anyone knowing") with worse numbers, fine now. "How?" → the source named in one word → "What?" → origin lore (where it grows, ripening time, the picking window, "where it's supposed to grow") → "And it does what?" → the outcome chain: 4–7 short literal sentences ending in the number coming down "on its own." |
| 6 | AMAZON | 28s | "I'll just grab some on Amazon." "Don't." The peer's own failed attempts ("I tried five brands"), what the fakes actually are (powder, tea bags, dried leaf off a truck), and why companies cut the corner. |
| 7 | BRAND | 25s | "Which one's real?" Brand named ONCE. The visible tell ("dark bitter liquid — that's how you know"). Regimen a tired person can do ("a dropper every morning. That's it." "That's it?" "That's it."). A commitment window tied to life ("until the next appointment"). The doubt, answered flat: "And if it doesn't work?" "Then it doesn't work." |
| 8 | DAY CARDS | 20–35s | DAY 14 / 30 / 60 / 90. Proof through OTHER PEOPLE noticing (sleep, stamina, the grandchild) and the authority re-measuring: "Say that again." "I checked it twice. Whatever you're doing, don't stop." Nobody says "I feel better." |
| 9 | PAYOFF | 15s | With the witness: "You did it?" "We did it." Then the identity event handed down: "Are you gonna teach me?" "Yeah, bud." |
| 10 | CLOSE | 10–20s | EITHER the to-camera moral (the only lens look in the ad, NO sale language) OR fully diegetic: the last human beat, then the camera drifts to the product sitting in the scene. End card: product + the true scarcity line + "Link below." Never discounts. |

**Writing laws (all mandatory):**
- Lines 2–8 words. Every line answers the previous line. Only blocks 5 and 6 contain long speeches.
- Grade 3–4 vocabulary. LITERAL mechanism — no metaphor stacks (no waves/scissors/static). One plain image max.
- Order of revelation: problem → mechanism of the PROBLEM → fear → solution → mechanism of the solution. Never hand over the solution before the fear.
- The fear is a staircase with named stages ("First it's 2 toes… then the needle… then a sore that won't close… then they took the foot").
- Emotion is shown through body and behavior (pressing the toes, checking the floor, going still, a swallow), never named, never blushing/cartoon reactions.
- Never name a compound the video model can't say. "Makes a compound that slows your sugar" beats a garbled Latin word. If a name is essential, test it in the pilot.
- Family lines are vague-specific: "a little boy who won't remember you," not the child's name.
- Numerals as digits. US English. Ellipses, never em dashes. No scaffolding words. Brand appears once, in block 7, plus the end card.

---

## PART 2 — WHAT'S NEEDED (accounts + asset pack)

**Accounts:** kie.ai (models: `gpt-image-2-text-to-image`, `gpt-image-2-image-to-image`, `bytedance/seedance-2-5`), ElevenLabs (TTS + shared voice library). Keys in a `.env`.

**Folder layout:** `PROJECT/{CAST, ENV, VOICE, TAKES, CARDS, STILLS, EDIT_KIT}` plus `batch_taskids.json`.

**Cast pack (per character):**
1. FRONT face — text-to-image, candid-iPhone realism prompt (natural light, sensor grain, flat contrast, no retouching, plain wall). Get it APPROVED.
2. PROFILE — image-to-image FROM the approved front: "the EXACT SAME PERSON as the input image… true side profile… same clothing." NEVER prompt a profile from text alone (you'll get a different person → drift and artifacts in video).
3. OUTFIT plate — headless (framed from the neck down, cropped at the collar), arms at sides showing the hands, and ALWAYS state the character's skin tone or the model will default it wrong.

**Environments:** one still per location, EMPTY — "NOBODY in frame, no people, no text," vertical 9:16, same candid-iPhone language. Reuse across takes.

**Product:** one hero still of the real bottle/pack, stylized ONCE, reused as the reference everywhere; never re-describe its colors in prompts.

**Voices:** search the ElevenLabs shared library per role (gender/age/accent + descriptive terms), pull 3 candidates each, render ~5s samples that contain the script's HARD WORDS (the product name, condition terms, any medical words) so the operator judges pronunciation too. Children barely exist in the library: pitch-shift a young voice up, or give the video model NO sample for the child and let it invent one from the description. Character's voice sample = timbre/accent reference only; the video model does the acting.

**Cards/stills:** DAY cards = white text on black, 720×1280, 1.5s clips. The research beat = image-to-image on the location still, putting the two searches ON the phone screen ("text crisp, correctly spelled, nothing else on screen"), then a 7s slow push-in.

---

## PART 3 — HOW TO MAKE THEM (production grammar for Seedance 2.5 on kie)

**Take design:** one scene = one take, ≤30s, `720p`, `9:16`, `generate_audio: true`. Per take: ≤5 `reference_image_urls` (environment first, then faces, then outfits), ≤2 `reference_audio_urls` (the two speakers), and ALWAYS a 2s black clip as `reference_video_urls` with "Ignore the reference video entirely" in the prompt — it makes each take dramatically cheaper than generating without it. Persist every task id to disk the moment it's created.

**Every prompt is built from these blocks, in order:**
1. **Scoped refs:** "Use @Image1 only for the [location]; ignore any people in it. Use @Image2 only for NAME's facial features; ignore background and wardrobe. … Use @Audio1 only for NAME's voice timbre and accent. Ignore the reference video entirely."
2. **STYLE:** cinema-verite telenovela on a phone — natural light, flat contrast, sensor grain, handheld micro-shake — and the shot grammar: "built from SHOTS separated by clean hard CUTS: wide or two-shot to establish, tight singles with faces filling the frame, then the reverse. Nobody ever looks at the camera: in every tight single the speaker looks at the OTHER person's eyes, off to one side of the lens; the camera sits beside the listener's shoulder."
3. **Scene setup:** who, wardrobe (restated in words), where, mood.
4. **Timestamped SHOT blocks:** `SHOT 1 (0-8s), two-shot: NAME says: "…" ` — every line in quotes, attributed, in order, with the physical action written as ONE deliberate motion that happens BEFORE the dialogue it motivates.
5. **RULES:** "Each line is spoken ONCE, in the exact order written, by the named speaker only, and while one person speaks the other's mouth stays CLOSED; no extra lines, no laughter unless written. Accurate lip sync. No subtitles, no captions, no on-screen text, no music. No identity drift, no face changes." Plus pronunciation lines for hard words.
6. **CONTINUITY:** "every object keeps its exact form for the whole take — clothes, tools, plates, phones and furniture never change, merge, appear or move on their own; hands stay calm, one small gesture per shot." If wardrobe matters (hats, jackets): name it per shot ("wearing his cap and flannel in EVERY shot, never removed").
7. **DELIVERY:** "real conversation — warm, unhurried, each line answering the last; never clipped or robotic."

**Hard-won laws (violating these is what fails takes):**
- Hard words: split IN the spoken line, two parts max ("sour... sop"). Never split a word two speakers trade back-to-back — write it plain for the second speaker. Letter-number terms are three sounds ("A... one... C"). Five-syllable splits read robotic. If a word fails twice, REWRITE THE LINE without it.
- The LAST line of a take mis-attributes easily: give it its own tight single on the right speaker + an explicit turn guard.
- Phone/video calls: over-the-shoulder staging behind the caller looking at the screen; the back of a phone never faces camera; no laptops or readable screens (screen text renders garbled); show the call being MADE (tap, ring, answer) so the scene has cause.
- No costume business inside a take (shoes/socks on-off) — objects morph. Shoe already off, sock stays on.
- Scene-to-scene needs visible cause. If the script jumps (kitchen → suddenly shopping online), insert a push — an argument that ruptures them into action beats a transition.
- No cartoon emotion (no blushing, no big laughs); reactions come AFTER their cause, small.
- kie moderation: no studio names, no gore/medical-explicit words; profanity in dialogue has passed.

**Process:** render a PILOT first — the longest two-hander (it stress-tests both lead voices, the location, and the cut grammar). Whisper-check it, frame-check it, get the operator's verdict, fold their notes into ALL prompts, then batch the rest at full width.

---

## PART 4 — AUTOMATION (the stage machine Claude Code runs)

**Stages and gates:**
- **S0 INTAKE** — collect Part 0. No spend.
- **S1 SCRIPT** — write to the Part 1 skeleton, present in chat with a blank line between every line. GATE: operator approves/edit-notes. Apply notes verbatim.
- **S2 CAST PACK** — faces (front → approval implied by the sheet review → profiles via i2i), outfits (skin tone stated), envs, product still, DAY cards, research still. Build labeled contact SHEETS (faces+profiles; outfits+envs). GATE: operator approves or names swaps.
- **S3 VOICES** — 3 candidates per role with hard words in the samples; send with a who's-who list (file → character → library descriptor → sample line). GATE: operator picks each.
- **S4 PILOT** — 1–2 takes. Whisper QC (small.en) + frame strip. Present with honest defects. GATE: verdict + notes → patch all prompts.
- **S5 BATCH** — all remaining takes at full concurrency in a BACKGROUND job that: persists every task id to `batch_taskids.json` on submit; RESUMES by saved id instead of resubmitting (protects against double billing after crashes/kills); retries once; on "Credits insufficient" reports to the operator and resumes the missing keys after top-up (finished takes are skipped by file-exists). Monitor the job's stdout for SUBMITTED/OK/FAIL lines.
- **S6 QC** — for every take: whisper (small.en) transcript vs an expected-phrase list (treat numeral spellings, "sugar coat," brand-name mishearings as fuzz → operator listen-check, NOT auto-re-roll); a 3–5 frame strip per take reviewed for wardrobe drift, eyeline-to-lens, prop morphing, wrong-speaker mouths. Re-roll ONLY verified defects, as `key_v2`, `key_v3`…
- **S7 ASSEMBLE** — normalize every piece (720×1280 pad, 24fps, AAC 48k), insert DAY cards at their slots, concat in script order, `loudnorm I=-14:TP=-1.5`. The assembler always prefers the highest `_vN` per key. Output: `MASTER.mp4`, `EDIT_KIT/` (numbered ordered clips + ORDER.txt for hand editing), `QC_REPORT.txt`. Deliver master + QC report + the flags that need ears.

**Core API pattern (kie):** create task → poll → download; every call wrapped with 2–3 attempts; NEVER run a long batch in the foreground (run detached, notify on completion); check credit balance before S5.
```
POST createTask {model, input:{prompt, reference_image_urls, reference_audio_urls,
                 reference_video_urls:[black2s], duration, resolution:"720p",
                 aspect_ratio:"9:16", generate_audio:true}}
→ save {take_key: taskId} to batch_taskids.json immediately
→ poll recordInfo until success → download → TAKES/{key}.mp4
```

**Templatisation:** the skeleton carries no brand. Slots: `[PRODUCT] [FORMAT+REGIMEN] [TELL] [SCARCITY TRUTH] [CONDITION] [FELT SYMPTOM] [FEARED ENDPOINT] [AVATAR+WORLD] [IDENTITY EVENT] [WITNESS] [ANCESTOR STORY] [DESCENDANT] [NUMBERS before/after] [PEER] [MECHANISM PLAIN] [FAKE-PRODUCT TELL] [WINDOW] [DAY OBSERVATIONS ×3]`. A new ad = new intake → same machine.

**Budget discipline:** the black-clip reference discount plus 720p keeps a full 15–17-take ad affordable; the gates exist so nothing large is generated before the pilot proves the grammar.

**Quality bar to ship:** every line verbatim and attributed to the right mouth · no wardrobe/prop drift across a scene's takes · no lens looks except a scripted close · phone logic correct · mechanism literal and complete · no sale language in the film · end card uses only true scarcity · the last image is the future the avatar nearly lost (or the product sitting quietly in that scene).

---

## PART 5 — BOOTSTRAP (zero-context setup; read this first on a fresh machine)

**Prerequisites (install once):** Python 3.9+, `pip install httpx openai-whisper pillow`, and `ffmpeg` on PATH (macOS: `brew install ffmpeg`). Whisper downloads its model on first run; use `small.en` for QC.

**Keys — create a `.env` in the project folder:**
```
KIE_API_KEY=...        # from kie.ai → API Keys (needs credits loaded)
ELEVENLABS_API_KEY=... # from elevenlabs.io → Profile → API Keys
```

**kie.ai API contract (the only two endpoints you need):**
- Create: `POST https://api.kie.ai/api/v1/jobs/createTask` with header `Authorization: Bearer $KIE_API_KEY`, JSON body `{"model": "<model>", "input": {...}}`. Response contains `data.taskId`.
- Poll: `GET https://api.kie.ai/api/v1/jobs/recordInfo?taskId=<id>` (same auth). Poll every 15–30s until `data.state` is `success` (result URLs are in `data.resultJson` → `resultUrls`) or `fail`. Also in `data`: `creditsConsumed`.
- File inputs: kie accepts public URLs. Upload local refs first: `POST https://kieai.redpandaai.co/api/file-stream-upload` (same Bearer auth) as multipart with `file` and `uploadPath=images/user`; the response's `data.downloadUrl` is what you pass in `input`.
- Models used here: `gpt-image-2-text-to-image` and `gpt-image-2-image-to-image` (input: `prompt`, `aspect_ratio` like `"9:16"`/`"3:4"`, `resolution:"2K"`, i2i adds `input_urls:[...]` ≤3) and `bytedance/seedance-2-5` (input: `prompt`, `reference_image_urls` ≤5, `reference_audio_urls`, `reference_video_urls`, `duration` int ≤30, `resolution:"720p"`, `aspect_ratio:"9:16"`, `generate_audio:true`). The black reference clip makes Seedance generation far cheaper than running without it — ALWAYS pass it.
- The black clip (make once): `ffmpeg -f lavfi -i color=c=black:s=720x1280:r=24 -f lavfi -i anullsrc=r=48000:cl=stereo -t 2 -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest black_2s_916.mp4`

**ElevenLabs API contract:**
- TTS: `POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}` header `xi-api-key`, query `output_format=mp3_44100_192`, JSON `{"text": "...", "model_id": "eleven_multilingual_v2", "voice_settings": {"stability":0.6,"similarity_boost":0.6,"style":0.0,"use_speaker_boost":true}}`. Response body is the MP3.
- Find voices: `GET https://api.elevenlabs.io/v1/shared-voices?page_size=40&gender=&age=&accent=&language=en&search=` → pick by `descriptive`/`cloned_by_count`; add to the account with `POST https://api.elevenlabs.io/v1/voices/add/{public_owner_id}/{voice_id}` `{"new_name": "..."}` before using its `voice_id` in TTS.

**Scripts to write on first run (Claude: build these from Parts 3–4, they're ~150 lines each):** `batch.py` (takes dict → upload refs → createTask → persist id → poll → download; args = take keys; resume-by-id; semaphore 14–16) and `assemble.py` (whisper-QC vs expected phrases → normalize 720×1280/24fps → insert cards → concat → loudnorm → MASTER + EDIT_KIT + QC_REPORT). Run batches as background jobs, never foreground.

**Sanity pilot for a new setup:** generate 1 face still, 1 env still, 1 voice sample, then one 8s two-line Seedance take with the black clip. If all four land, the pipeline is proven — proceed to S1.

---

## PART 6 — CONSISTENCY + POLISH LAWS (added 2026-08-24, learned on a single-location game-show format; apply to every ad)

**The one-room law (biggest quality lever).** If scenes share a location, generate ONE master still of that location, get it approved, then derive every other angle/side/detail plate from it with image-to-image ("THE EXACT SAME room — identical walls, colors, materials, lighting — now seen from ..."). Reference the SAME plates in every take of that location. Never generate two independent stills of "the same" room — the model will build two different rooms and props/geometry will drift take to take.

**Delete what can render wrong.** Numbers, signs, and readable text on set props WILL come out wrong somewhere (podium "1 2 3" rendered 4-3-3). Remove them from the plates (use a motif instead); let dialogue/VO carry the meaning. Add uniqueness guards for furniture: "the SINGLE chair — the only chair anywhere."

**Composition guards for split/blind staging.** If the format says two people can't see each other (partition, phone call, different rooms), they must NEVER share a frame during those scenes — combined wides both break the illusion and invite the model to clone a character onto the wrong side. Singles only; they meet on screen only at the scripted reveal.

**Casting wide shots.** For a populated establishing shot, build ONE composite contact sheet (all approved faces in a row, name labels under each — a 10-line PIL script) and reference it for the crowd shot. BUT scope it: the person speaking in a tight shot needs their OWN face ref scoped to that shot ("the man in shot 1 has EXACTLY this face, from @Image1 ONLY"), composite for the distant people only, plus a negative guard ("never a man with glasses"). An unscoped composite can dress the wrong labeled face into a role. And say "the set is FULL: every seat, every position occupied" — never pan across an empty set.

**Two-strike word law.** If a word slurs and you re-roll and it slurs AGAIN (any variation), stop re-rolling — REWRITE the line ("on the dot" → "like clockwork"; "Black Seed" → "Black Cumin"). One whisper mishear alone = flag for a human ear, not a re-roll (whisper mangles brand names and numerals it doesn't know). A silent take that grows invented speech gets a SILENCE block: "completely WORDLESS take — every mouth stays closed; the only sound is the ambience written."

**PACE block in every take.** "Brisk pacing — lines flow one after another with NO long pauses or dead air; movement happens DURING lines; the last line finishes near the end of the take." Then in assembly, trim each clip head/tail using whisper word timestamps (first word −0.45s, last word +0.55s) — EXCEPT takes whose visual payoff comes AFTER the last line (reveals, product holds, inserts): never tail-trim those.

**MC/host/narrator interval lines = on-camera clips, not VO overlays.** Laying announcer VO over scene audio reads as jumbled overlap. Give each interval its own 5s single of the host (hosts may address the lens). Trim them snappy (2–3s) in the edit.

**Sound layering rules.** If a take's prompted ambience already contains crowd reactions (groans, gasps, laughter), do NOT overlay an SFX copy — you'll get doubles at slightly different times. Only overlay what ambience can't make: buzzers, stings, fanfares, music beds, and generate those with ElevenLabs sound-generation (ask for "ends on a clean resolved final chord" so music closes instead of chopping). Mix levels that work: music beds ~0.25 under dialogue, stings ~0.7. Anchor timed SFX on whisper WORD timestamps, and search a LIST of token variants ("min/men/metformin") — whisper re-spells words, and a missed single token silently sends your cue to the end of the clip.

**Interstitial cards.** Generate cards in one consistent retro style (same background/typeface family), then animate cheaply in ffmpeg: chroma-key a flat flower/motif (generated on pure green), rotate it in a corner overlay. Every card gets the SAME short sting — a repeating audio signal that says "next scene."

**No redundant closers.** If the final take already ends on the product, don't add a product-still zoom after it.

**Version hygiene.** Re-rolls save as `_v2`, `_v3`...; the assembler always prefers the highest version; prefix a bad version `REJ_` to retire it from selection (keeps it on disk for comparison). Hand off to the editor as a `CAPCUT_DROP/` folder: every file named `NN_slot__PICK` / `__alt-reason` / `__REJ-reason` so alphabetical sort = timeline order, plus an AUDIO_SFX folder and a README cue map.

---

## PART 7 — CHARACTER, CAMERA & AUDIO LAWS (added 2026-08-25; the QC layer that survives contact with the model)

These were paid for one re-roll at a time. Bake them into every prompt from take one.

**Eyeline is GEOMETRY, not a rule.** "Nobody looks at the camera" fails as a prohibition. What works: in every tight single, the speaker is seen in THREE-QUARTER view, looking at the other character just OFF-FRAME beside the lens; the camera never sits on the axis between two people's eyes. When a shot still comes back frontal (final-line reaction singles are the repeat offender), escalate to the OTS SHOULDER ANCHOR: put the listener's shoulder/hair soft-focus in the foreground edge — with a foreground body in frame the model cannot build an on-axis selfie.

**Mirrors are disguised lens-looks.** "Tight on her reflection" = her reflected eyes pointing into the camera, every time. Shoot every mirror beat with the camera at 45 DEGREES to the glass so the reflection is a PROFILE ("we see the side of her reflected face — it can never point at the camera"), plus the OTS shoulder in the frame edge.

**Hands: never airborne.** No counting on fingers, no holding fingers up, no pointing — ever; list-numbers live in the voice alone. And gesture language like "her thumb traces his cheek" renders as an airborne POINT — write CONTACT language instead: "two fingertips RESTING on the cheekbone, continuous contact, never lifting to point." Touches are allowed; hovering is not.

**Object physics block.** Any hand-prop (card, bottle, phone) gets one line: "always either held in the hand or resting fully ON the surface — it never floats, never hovers, never appears twice."

**Body-furniture anti-fusion.** Any standing-at-counter/vanity shot gets: "a clear visible gap between her body and the counter; nothing merges, nothing intersects." Without it, waists melt into furniture.

**Faces bleed from ANY reference that contains a face — including your style-anchor frame.** A described-but-uncast cameo (a daughter, a passerby) will borrow the face of whoever appears in the reference images, and text guards lose that fight repeatedly. For any take that introduces a described character: (1) purge every ref containing another person's face (use face-free plates), or give the cameo their own face ref; (2) state the cameo's ethnicity and family resemblance explicitly, with a negative guard ("NOT the specialist").

**The payoff face is a second character.** For transformation stories, generate an AFTER face via image-to-image from the approved cast face ("THE EXACT SAME woman — but refreshed: hollows filled, cheeks fuller, lines softened, still naturally her age, no filter look") and use it as the face ref for payoff scenes, with the improved features restated in the prompt. Never expect the ad's promise to show up by itself.

**Pace is per-format.** "No dead air" fixes documentary drama but makes intimate formats rushed. Write the pacing block to match the room: "calm and intentional, a natural breath between lines, a pause where a thought lands — but never dead air longer than a beat." Then trim heads/tails in assembly with word timestamps — EXCEPT: never head-trim a take whose visual business precedes the first line (cold opens), and never tail-trim a take whose payoff follows the last line (reveals, product holds).

**Voices wobble; plan for it.** The model re-synthesizes voices from the reference on every take, so take-to-take timbre drift is inherent. Mitigate: (1) each character keeps the SAME @AudioN slot in every take of the production — never reorder by who speaks first; (2) for a two-voice take the combined reference budget is ~15 seconds — cut each character's ref to a dense 6–9s segment (pick it by word-timestamps: the longest continuous-speech window); (3) judge drift on the FINAL EDIT only, then fix lines in post with a speech-to-speech re-voice of the locked character voice — not with re-rolls.

**Pronunciation is won in the GENERATION, not in post.** The main focus: get every hard word said right inside the clip. The stack, in order — (1) write the word phonetically IN the spoken line (spell it the way it must sound); (2) carry an ARTICULATION rule ("four smooth syllables, said the SAME way every time"); (3) bake every hard word into the voice-casting samples so you hear the risk before production; (4) make the pilot the take that carries the hardest words; (5) two independent renders slurring the same word = REWRITE the line (change the word, not the actor). A clean clip beats any repair.

**OPTIONAL last resort — the word-dub.** Honest caveat: it works only sometimes, and seams can be audible; treat it as a salvage option, never the plan. If a take is otherwise great and one word is off, you MAY transplant the word from a take where it was said correctly: word-timestamps locate both spans → donor word tempo-fitted to the SAME span duration (downstream sync survives) → loudness-matched → a quiet bed of the target's own room tone (~-11dB) under the donor word so it doesn't ring "studio-clean." Never low-pass/treble-cut the word to blend it (smears it into mush). Judge the seam by ear at full volume; if it reads as a splice, fall back to a speech-to-speech re-voice of the whole line, or re-roll the take.

**The frame-by-frame gate is mandatory.** Before any draft is delivered: extract 1 frame per second from every take, tile into strips, and look at EVERY strip. Whisper plus sparse strips will miss floating props, body fusions, lens-looks, wrong-numbered props, identity swaps and finger-counting. Also build a one-frame-per-take contact sheet of the final picks — the whole ad on one screen — to verify a single grade, a single room, and a single cast before the edit.
