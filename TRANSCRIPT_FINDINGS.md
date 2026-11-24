# Transcript Findings: what the videos teach that the SOPs and skills don't

Compared against: drama-ad-machine SOP, song-ad-machine SOP, finn-xplains-video, wan3-podcast-ads, vox-animated-ad, omni-chalkboard-skill and omni-whiteboard-skill. PDFs are used only where a video says the prompt is "below". Times are `[mm:ss]`.

**File codes**
- OMNI = `01…06 GOOGLE OMNI`
- MC = `01…07 MOTION CONTROL`
- SD20 = `01…08 Seedance 2.0`
- KL3 = `01…09 Kling 3.0`
- BR1–BR5 = `02…B-ROLLS__01–05`
- DR1–DR4 = `02…Seedance 2.5__02–05`
- WB = Whiteboard
- VOX = Vox
- MM1/MM2 = meetings
- MM4 = AI Agent Copywriting
- DECON = `05…10 DECONSTUCTOR`
- SORA25 = `05…14 sora 2`

**The black reference clip appears in no transcript.** The only nearby hint is an unexplained "self referring method we talked on the group" that makes Kling on Kie "way cheaper" (KL3 [11:40]).

---

## 1. Gaps vs the SOPs

### A. UGC talking-head: new skill needed (nothing installed covers single-creator UGC)

1. **The first frame is "95%" of Seedance quality.** It must look like a real TikTok frame, because Seedance "has been trained on TikTok videos" (SD20 [00:42]–[01:20]). *New UGC skill; also drama SOP Part 2.*
2. **Use Seedance reference mode, not first-frame mode.** First-frame mode "tends to make the video not as good" (SD20 [06:14]–[06:28]). Settings: 720p, 9:16, 15s; 60s = 4 clips (SD20 [04:19], [08:14]). *New UGC skill.*
3. **@image tag bug: no space** ("@Image1", not "@Image 1") (SD20 [04:07]–[04:16]). *Drama SOP Part 3 and the new UGC skill.*
4. **Reference audio acts as a voice cloner.** Use a 15s MP3 cut from a TikTok, referenced as "using audio 1". It can also carry music or SFX (SD20 [07:04]–[08:02]). *New UGC skill.*
5. **Product enters from out of frame.** This reads more natural than a frame with the product already in hand. Slot order: image1 person, image2 product, image3 prop (SD20 [08:34]–[09:11], [11:14]). *New UGC skill.*
6. **Kling 3.0 talking clips.**
   - 6s clips with about 16–17 words. At 7–8s, Kling "pauses for one second… and… talks faster after that" (KL3 [11:03]–[11:28]).
   - Native lip-sync from a start frame. Standard = 720p, Pro = 1080p (KL3 [10:08]–[10:33]).
   - The voice tends to stay consistent per face (KL3 [09:36]).
   
   *New UGC skill. finn's kie-api.md has the schema only.*
7. **Use 3–4 start-frame variants per talking video.** Change the prop or gesture each time, or the actor "is repeating the start frame" (KL3 [08:19]–[09:12], [13:00]). *New UGC skill.*
8. **Clone pipeline.** Inspo frame (Pinterest/TikTok) → 3-angle character sheet → Nano Banana character swap. Change the face: "we can get copyrighted, we can get sued" (KL3 [04:49]–[06:54], [05:26]; OMNI [01:16]). *New UGC skill.*
9. **Gemini analyzes, Claude writes.** Gemini is best at video analysis but drops the script when half the screen is b-roll, so paste the script manually. Then Claude turns Gemini's output plus the "master prompt" into the prompts (KL3 [01:44], [07:01]–[07:23], [15:38]–[16:20]). *New UGC skill.*
10. **Omni Method 1.** Image-to-video with the base prompt. Then regenerate using the first output video as the reference, so voice and movement carry over (OMNI [01:29]–[03:01]). Budget about 30–33 words per 10s talking clip (OMNI [10:50]). Vox's 20–25 words is for VO-only. *New UGC skill.*
11. **Omni Method 2, the cost trick.** Generate one Seedance clip, then use it as the Flow/Omni video reference and swap scripts. The result is "maybe 60, 70% as Cdance" but much cheaper (OMNI [09:50]–[10:10]). Real videos as references get "restricted"; AI-made ones pass (OMNI [06:19]–[07:50]). *New UGC skill.*
12. **Omni Flash motion control.** It replaces the person in a 10s video and is "outperforming cling motion control". Add "remove all text from screen" (MC [00:06], [01:41]–[02:46]). **Caution:** the method pastes the prompt as a screenshot to dodge Flow's flagging and re-skins other people's TikTok/Ads Library videos. You decide whether that belongs in the pipeline. *New skill needed.*

### B. B-roll: new skill needed

13. **Script-specific b-roll flow.** Script → brief → shot list → storyboard (9:16 frames on one 16:9 sheet) → labeled individual 9:16 images → Kling i2v prompts with "no spoken words" (BR1 [01:30]–[05:46]).
14. **Model choice.** Kling is the cheap default. Use Seedance whenever there is readable text, phones or screens, because Kling text goes "glyphic" (BR1 [06:55]–[07:11]; BR2 [09:01]–[09:22]). Seedance or Kling beat Omni on camera control (BR2 [01:32]).
15. **Reusable library.** Have the agent plan a category folder tree (problem moments, failed solutions, discovery, education, use) with 3 b-rolls per category. Keep them faceless so they can be reused. Rename the files and upload to Drive (BR2 [02:34]–[05:26], [10:43]).
16. **Realism line, added after the first pass:** "uneven camera angles, TikTok style, candid… iPhone 15", plus a handheld-shaky prefix on every i2v prompt (BR2 [06:23], [07:49]; BR1 [07:50]–[08:04]).
17. **Make images before video so defects show early.** A blurred label was caught at the image stage (BR2 [08:41]). Salvage awkward clips by cutting a 1–3s span (BR2 [10:07]–[10:20]).
18. **X-ray b-roll.** Candid start image → end image of the same shot zoomed in with a bone/organ overlay on a dark background → animate start→end → trim to 2–3s at 2× (BR3 [00:36]–[05:32]).
19. **Screen-recording b-roll.** Seedance 2.5 on Kie, with a reference image plus the real screen recording as the reference video (BR4 [00:16]–[01:35]).
20. **Handmade b-roll.** Film the screen with a phone at an angle, starting blurred, using a stylus pointer (BR5).

### C. Assembly and post (no skill covers it)

21. **Kling UGC finish.**
    - Play at 1.1×.
    - Adjustment layer: temperature 2, exposure −3, contrast −8 (−6 to −8), highlight −3, shadow 3, whites −2, blacks 0, clarity 1, particles 2.
    - 30fps for ads; optical-flow 60fps only for X (KL3 [13:34]–[14:57]).
    - For Omni, contrast −12 to −16 gives an "iPhone style look" (OMNI [05:04]–[05:20]).
    
    *New UGC skill.*
22. **Adobe Podcast "Enhance"** on the exported audio (KL3 [15:03]–[15:17]; DECON [16:29]). *New UGC skill; optional for drama S7.*
23. **Drama edit.** Cut dead space and speed ramp the whole video to about 1.15×, no zooms (DR4 [00:10]–[00:35]). Add music from CapCut or a Suno prompt (DR4 [01:00]–[01:34]). Make the speech a **compound clip before auto-captions**. Add hook text, and hide captions while it shows (DR4 [01:40]–[02:09]). *Drama SOP S7, which has no music, caption or hook step.*
24. **Animated formats.** Lay the VO first, generate 10s clips, then speed each clip (often 2×) so it ends exactly on its line: "then you have control of the pacing" (VOX [09:50]–[13:24]; WB [07:15]–[11:10]). Optional: transitions and ElevenLabs marker SFX (VOX [14:20]; WB [11:43]). *Vox, whiteboard and chalkboard skills.*

### D. Animation skill additions

25. **Whiteboard on Seedance 2.0.** Use one blank-board start frame for every clip plus a generated end frame per clip. Seedance gives the best result, Omni is the cheap fallback, and "Veo… looks horrible". Do the VO first (WB [01:31]–[02:30], [05:37]–[06:41]). The skill only knows Omni last-frame chaining. *omni-whiteboard-skill; same option for chalkboard.*
26. **Vox start images.** Text-to-video lost the character (VOX [05:47]–[06:09]). Fix: one base start image plus one product-intro start image (VOX [07:37]–[08:03]). Omni beat Seedance 2.0 Fast here (VOX [08:43]). *vox-animated-ad, which has no start-frame mode.*
27. **Vox script check.** If the script doesn't make the category obvious, "Facebook might have a harder time putting it in front of the proper audience". For women's health, use the graphic specifics from research (VOX [05:13]–[05:38], [06:49]). *vox VO rules.*

### E. Drama SOP additions

28. **Children:** Kie may block child images, so generate them in ChatGPT (DR2 [07:02]; DR3 [02:03]). *Part 2.*
29. **Flashbacks:** sepia, with a child-version reference of the adult character. Add failed-solution props from a screenshot of the real item (DR3 [04:02]–[04:31]). *Parts 1–2.*
30. **Product sheet:** build it from real photos plus a usage video, and hand-correct the part counts (DR2 [08:28]–[09:28]). *Part 2.*
31. **Script push:** never take the first plot. Ask for "an emotional punch in the gut" and keep the product out of the opening. Base the plot on a long-running winning ad (DR2 [00:06]–[03:20]; DR3 [00:50]). *S1.*
32. **Omni fallback:** Omni has no multi-cut, so make one frame per shot and "juggle" 2–3 frames per two-person scene. Old Omni chaining changed the backgrounds (MM2 [05:18]–[06:28]). Have Claude adapt the Seedance SOP (MM2 [06:43]–[07:31]). *New appendix.*

### F. Veo, Sora and other models

33. **Veo 3.1 automation.** Gemini splits a reference video into 8s segments with dialogue, and a "bridge segments" step generates matching end/start frames (MM1 [21:48]–[23:13]). Scripts over 55 words get segmented (MM1 [27:31]). *New skill needed; there is no Veo skill.*
34. **Sora 2 is being retired** (web app down, API "too expensive") (KL3 [00:08]–[00:27]). Three portable rules:
    - On continuation clips, strip location, character and voice descriptions and use the "exact same scene… tone and voice" line (DECON [06:41]–[09:13]).
    - State the real product size, e.g. "50 gram", so packaging scales correctly (DECON [13:51]–[14:24]).
    - White-background product images beat transparent PNGs (SORA25 [03:19]–[03:33]).
    
    *New UGC skill.*
35. **LTX 2.3:** open-source, 1080p/2K, runs local or on RunPod. Not yet taught (KL3 [00:38]–[00:54]).

---

## 2. Ready-to-use prompt templates (verbatim; none are in the skills)

**Clone (Gemini)**, KL3 [03:51]:
> help me clone this video exactly like it is scene by scene, extract raw script in one block, exact exact actions she's doing, the style of video, the way she's talking, how the character looks, every different scene 100% the same, do not miss anything, follow a master prompt to do everything.

**Character swap (Nano Banana)**, KL3 [06:45]:
> replace the first character with second character, upscale the image, remove play button if it's a video.

**Same set, new prop.** The video says "exact same framing as image one…" (KL3 [08:08]). The full block from the PDF (`01…09 Kling 3.0`):
> Exact same framing as Image 1 - same character, same set, same lighting. Vary only prop and gesture/expression as noted per clip below. Camera: Same as Image 1. Deep focus on everything. No blur. Lighting: Same as Image 1. ABSOLUTELY NO phones, cameras, screens, social media UI, floating text, or digital overlays visible anywhere in the frame.

**First-frame request (ChatGPT)**, SD20 [05:13]:
> I'm creating a new video for C dance. And I will need the first frame prompt so I can generate an image that matches the UGC video below. I don't have any references. Give me the correct iPhone photo realistic prompt that matches this scene.

**Seedance add-ons**, SD20 [03:19]–[03:39]:
> she is always sitting in the same car, in the same seat, the same lightning, same angle and the same tripod camera setup.

> she should talk like she's yapping to a friend, add small natural movements and gestures, looking around, leaning closer, laughing a little and saying things like, like, you know

**Voice from audio**, SD20 [07:32]:
> She talks fast and casual like venting to her best friend on FaceTime with natural Amazon-like filler using audio 1.

**Product entry**, SD20 [08:50]: "reaches down out of frame with the right hand. She brings up to the chest the [product] from image two."

**Omni base.** The video points to the prompt (OMNI [10:19]). Verbatim from the PDF `01…06 GOOGLE OMNI`:
> natural and realistic arm movements, subtle lean forward, looks directly at the lens the whole time he/she says in an american 20 year old ugc tone: "[LINE]" Ambient Sound. No cuts. No zooms. No transitions. Raw iPhone footage, expressive ugc movements, UGC aesthetic. Vertical 9:16. NO PRODUCT IN HAND. ONE CONTINUOUS SHOT

Variant #P2 prefixes "Static tripod shot,". **Product add**, OMNI [04:19]: "She brings the square perfume bottle from [image] into the frame and hold it up."

**B-roll storyboard**, BR1 [03:33]–[05:38]:
> for the B-roll shot list, can you help me generate image prompt ideas and an image storyboard for what the B-rolls would look like … a total of nine by 16 images laid out across one large 16 by nine image … create as many as needed so that we can see all the B-roll shots.

Then: "turn all of these into … individual nine by 16 images and label them accordingly." Then: "I'm going to be using cling to turn these images into videos. no spoken words. Can you help me generate prompts to turn each of these images into a video?"

**B-roll realism**, BR2 [06:23]: "make the camera angles, uneven camera angles, TikTok style, candid as if it was taken with the iPhone 15"

**X-ray**, BR3 [01:06], [02:27]: "help me generate an image prompt for a tick-tock style Candid photo from iPhone 15 of [scene]", then "help me get in a zoomed in skeleton overlay"

**Screen recording (Seedance 2.5)**, BR4 [01:12]: "handheld shaky camera movement, use @reference image … person is scrolling and clicking on the … make the phone show the screen … @reference URL"

**Continuity line**, DECON [09:03]: "[character] in the exact same scene, talking in the exact same tone and voice, rhythm"

**Motion-control cleanup**, MC [02:40]: "remove all text from screen. Keep everything else the same."

---

## 3. Tools and accounts mentioned

- **Kie.ai:** Seedance 2.0/2.5, Kling 3.0, GPT Image 2, Sora 2, Veo. Pay-as-you-go with "clear pricing" (SD20 [06:02]). An overload "won't lose credits" (SORA25 [03:42]).
- **Google Flow:** Omni / Omni Flash, Nano Banana, Veo 3.1 (OMNI; MC; KL3 [04:21]).
- **Kling official site:** cheaper per clip than Kie (KL3 [11:46]).
- **ChatGPT Images 2:** first frames, b-roll, child characters (SD20 [04:40]; DR3 [02:03]).
- **Nano Banana Pro/2:** character sheets, swaps, prop variants (KL3 [04:16]).
- **Gemini:** video analysis, Gems (KL3 [01:44]).
- **Claude/Claude Code:** prompts, skills (SD20 [01:46]).
- **Codex + "0xROAS agent":** research, briefs, b-roll images. Run it in Codex, not plain chat, or API generation fails (BR1 [00:20]; DR2 [12:08]).
- **Antigravity:** copy with Gemini (MM4 [09:48]).
- **ElevenLabs:** VO, voice picks, SFX (DR1 [02:36]; WB [12:01]).
- **Suno:** music (DR4 [01:29]).
- **CapCut:** editing, adjustment layer, captions (KL3 [13:34]; DR4).
- **Adobe Podcast:** speech enhance; Creative Cloud premium needed (DECON [16:29]–[17:04]).
- **LTX 2.3:** open-source video model, local or RunPod (KL3 [00:38]).
- **images.laozhang.ai:** Nano Banana 4K images (DECON [19:05]).
- **Freepik:** "really slow" (DECON [19:24]).
- **Seedance 1.5 Pro or Kling:** a 4–5s rotating product clip for a Sora product character (DECON [13:19]).
- **Higgsfield:** alternative generator (DR1 [02:30]).
- **Inspo sources:** Pinterest, TikTok, Ads Library.
- **Hardware:** a stylus pointer (BR5 [00:55]).
- **Fiverr/TikTok students:** human translation for EU ads (MM2 [10:20]–[13:25]).

**Prices quoted verbatim:**
- "$125 for the first three months… you get like 25,000 credits… like 10 credits per VL 3.1 fast video" (KL3 [04:36]–[04:42])
- Kling official: "for six seconds, it costs you less than 60 cents with a maximum plan" (KL3 [11:46]); "one minute video $4, $5, something like that" (KL3 [13:26])
- Drama ad via Kie: "this is going to cost you about 41 bucks" (DR3 [05:05])
- "5 cents 4k Nano Banana image" (DECON [19:05])
- Kie Sora: "like 60% cheaper… than the official OpenAI platform" (SORA25 [03:48])
- Unnamed provider: "17 cents per vo 3.1 720p quality" (MM1 [56:31])
- PDF only: Ultra makes "omni videos for 1.44$ / 60s" (`01…06 GOOGLE OMNI`)

---

## 4. Can be skipped

- **MM1 meeting:** ad accounts and offers talk. Keep only [21:48]–[27:44] (item 33).
- **MM2 meeting:** ad accounts, tracking, cloaking. Keep only [05:18]–[07:31] and [10:11]–[10:35].
- **AI LIPSYNC, AI TALKING FRUIT, V2 TT SHOP, V2 AI ANIMATIONS:** a 1–3 line sample ad, no teaching. The method is in Google Docs linked from the PDFs.
- **Wan 3.0 Podcast:** sample ad audio only. wan3-podcast-ads covers it.
- **DR1:** an overview that duplicates the drama SOP. **DR2/DR3:** a live run of the drama SOP; keep items 28–31.
- **SORA25, DECON:** retired Sora 2 workflow; keep item 34.
- **MM4:** copy/research agent, not video production.
- **BR5:** one manual tip.
- **VOX, WB walkthroughs:** duplicate their skills except items 24–27.
