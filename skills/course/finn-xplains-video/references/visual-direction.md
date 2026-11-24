# Finn Xplains visual direction

## Visual authority

Inspect [reference-frames.jpg](reference-frames.jpg), extracted from the user's 113.8-second MP4, before the first creative pass. This is the specific treatment the user named “Finn Xplains.” Do not assume a generator understands the name or that it identifies a documented proprietary animation method. New user references and explicit adjustments supersede these defaults.

The sheet contains historical muslin scenes and a blanket offer. Those subjects, claims, price, brand, costumes, and warm-to-dark-to-light sequence belong to that example. Transfer the visual grammar; build the new content from the supplied script.

## What makes it recognizable

- White or ivory circular heads, dot eyes, tiny mouths, understated expressions, simplified bodies and hands. Detailed clothing and props distinguish roles. Head proportions and eye spacing stay stable for a given character.
- Fine brown/charcoal ink outlines, delicate hatching, watercolor/gouache-like shading, visible wash edges and mottled paper. Material detail is especially strong in fabric, wood, architecture, and plants.
- More detailed environments than faces: a readable foreground action within a believable room, landscape, workplace, or historical setting appropriate to the script.
- Clear central subjects in portrait framing. Vary wide context, medium action, close-up consequence, split comparison, and explanatory cutaway to make the narration visible.
- Simple visual reasoning: before/after, scale comparisons, layers, airflow, cause/effect, an object disappearing, a value tipping a balance. Choose metaphors from the actual sentence. Render exact arrows, labels, amounts, and diagrams in editing when precision matters.
- The source uses held stills and direct cuts. Continuous character motion, zooms, floating particles, and camera orbits are optional additions, not essential identifiers.
- Color follows the new story's emotional arc. Cream, ochre, sage and warm brown support calm or heritage; slate, indigo and charcoal can support conflict; airy paper/ivory supports resolution. Do not darken unrelated scenes merely to copy the source.
- Caption design: short readable phrases in black sans-serif on compact white labels, placed consistently within safe margins. Leave the subject's important action unobscured. Chapter cards may use restrained handwriting on cream paper. A brief word-at-a-time black card can punctuate a genuine turning point; it is not mandatory.

## Cast decisions

List all people/creatures needed to express the script's actions and relationships. Merge roles only when it does not confuse who did what. Reuse an identity across time with explicitly designed wardrobe/age variants when needed. Distinguish named or recurring roles from illustrative anonymous crowds. Explain the final count and provide prompts only for references that will be used.

A character lock is compact but concrete: `C01 | role | head/body proportions | face marks | hair/headwear | clothes/colors | signature prop | expression vocabulary`. Set locks define layout, key landmarks, palette, lighting direction, and reusable props. Product locks follow the actual user product reference; do not invent packaging or borrow the blanket from the example.

## Character-sheet prompt pattern

Expand all variables before delivery. Choose views useful to the planned scenes; four views is a starting point, not a requirement.

> Character reference sheet of one consistent character, C01: [role and identity]. Minimalist ivory circular head [specific proportions], [precise eye/mouth design], [hair/headwear], [wardrobe with fixed colors and footwear], [signature prop]. Show front, three-quarter and side full-body views, plus a close-up with [needed expressions]. Same proportions and outfit in every view. Fine brown pen-and-ink contours, delicate cross-hatching, soft watercolor washes, matte paper texture, gently shaded fabric. Neutral cream background, clear separated views, all hands and feet visible. Only this identity appears. Keep the identity natural to the new story. No scene scenery, narration text, labels, watermarks, or unrelated accessories.

Use a cropped, approved single view from the sheet when an image model might duplicate the multi-view layout. For unusual recurring hands/product handling, make a specific reference only if the planned scene needs it.

## Scene-image prompt pattern

> Image 1 supplies C01's identity and wardrobe. Image 2 supplies [set/product] only. Create one complete [9:16] scene: [visible action and consequence, tied to the exact script line]. C01 [expanded identity cues, pose, gaze and emotion] at [screen position], interacting with [object, hand contact and relative scale]. [Other relevant characters with their own reference mapping.] [Environment layout and landmarks]. [Shot distance, camera height, focal hierarchy and clear space for captions]. [Light direction and story-appropriate palette]. Vintage illustrated-storybook rendering: precise ink outlines, fine hatching, translucent watercolor/gouache-like shading, gently mottled paper, tactile [materials]. Maintain the reference identities while using this requested scene composition. No collage or character-sheet panels. No baked-in subtitles, logos, or unrequested writing.

The mapping text must match the real ordered KIE `input_urls`. Include only relevant references. A set reference cannot silently replace a character reference. A product reference cannot redefine the art style unless instructed.

For diagrams, state the exact object count, ordering, visual mechanism and intended arrow flow. Generate the material/illustration base and add exact readable diagram text as editable layers if the generated result is inaccurate.

## Optional image-to-video prompt pattern

Read the source image before writing its motion instructions. Describe changes to the existing scene, not a new illustration.

> Begin from the supplied approved scene image. Over [usable seconds], [character] performs [one clear action with start, contact and end state]. [One restrained secondary action if useful]. Camera [locked or one modest move]. Preserve the round-head proportions, dot-eye placement, exact clothing, object count, background layout, linework and watercolor texture. [Continuity condition or stable final pose]. Silent character performance, closed mouth, no lip-sync, no new scene, no internal cuts, no added text.

Schedule the meaningful action inside the eventual retained part of the provider clip. Avoid idle motion in a clip that will be trimmed before the action starts. When a mechanism is best explained as a still diagram, keep it still unless animation clearly improves comprehension and animated mode is authorized.

## Quick visual acceptance

Read the frame against its exact line: is the point visible without relying on captions? Compare recurring identities and sets side by side. Inspect physical contacts and hands, product proportions, unusual extra objects, text leakage, palette, and material texture. A beautiful unrelated scene fails. A returned image or clip is not accepted merely because the API succeeded.
