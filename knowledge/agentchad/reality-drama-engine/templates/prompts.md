# Prompt templates — Reality Drama Engine

<!-- 2026-11-12  Plates first: §1 is the character plate, §1b scene still made from plates, §1c product plate from real photos. -->
<!-- 2026-11-12  People are labelled by description, never by name; start-frame-only engine templates (section 5). -->

Copy, fill every `<slot>`, keep the fixed lines word for word. The example brand is Loopa, a smart water bottle that
glows when you have not had a sip in an hour.

**No names in any prompt.** Give each person a LABEL: a short description used word for word in every prompt, for
example `the woman about 45 with a grey bob and a green cardigan` or `the man about 50 in a white coat`. A name
("Anna", "Dr. Hart") used as a label gets printed into the picture. A name spoken inside a quoted line is fine.

## 1. Character plate (the Phone-Photo Lock)

One per person, approved by the user before anything else. Every other picture of this person is made from it (§1b).

```
Style: Candid smartphone photo, natural colours, slight grain, real skin texture with pores and fine lines,
no retouching, no studio look.
Visual: <age> year old <person>, <hair>, <clothes for this scene>, <doing what>, in <real place>, <looking into the
phone camera as if about to speak | looking at <OTHER PERSON LABEL> off camera>.
Composition: vertical 9:16, <phone held at arm's length | phone on a stand | filmed by a friend>, eye level,
<head and shoulders | waist up>, <background detail that makes the place believable>.
Lighting: <one real source: window light from the left / car interior daylight / evening street light>.
Constraints: no text, no logos, no watermark, natural hands with five fingers.
```

Example: `34 year old man, short dark hair, grey hoodie, holding a coffee mug, in a small apartment kitchen, looking at
his partner off camera. ... Lighting: morning window light from the left.`

## 1b. Scene still made from plates (every still after the plates)

Attach the plates as references: the character plate(s), the product plate when the product is in the shot, the
location plate when the place comes back. Never write a person or the product from text alone.

```
References: image 1 is <PERSON LABEL> (plate: keep the face, hair, age and build exactly). [image 2 is <PERSON B
LABEL> (plate).] [image 3 is the product (plate, <real size> cm; copy the packaging and label exactly).] [image 4 is
<the place> (plate).]
Same <woman | man> as image 1: same face, same hair, same age. Change only: <this scene's clothes>, <place>, <light>,
<framing and pose>, <one action>.
Style: Candid smartphone photo, natural colours, slight grain, real skin texture, no retouching.
No text anywhere in the image except the real product label copied from its plate.
```

Log the still in `plates.json` under `stills` with the plate ids you attached.

## 1c. Product plate (from real product photos)

Attach the real product photos (front, and the side with the label). The plate is a clean phone photo of the product
as sold, used as the reference for every product shot.

```
References: image 1 (and 2) are real photos of the product. Copy the product exactly: shape, colour, cap, the label
text and layout letter for letter. Do not invent or change any text.
Visual: the product standing on <a plain table>, <real size> cm tall, caps on, label facing the camera.
Style: Candid smartphone photo, natural light, slight grain.
```

Read the label on the result at full size against the real photo. Any wrong letter: regenerate, or use the real
photo itself as the plate.

## 2. Talking clip (one person, to the phone)

```
Style: Photorealistic UGC video filmed on a phone, natural handheld movement, <place>. 9:16 vertical. Hard cuts
between shots.

References: image 1 is <PERSON LABEL> (keep face, hair and clothes exactly as in the image).
[image 2 is the product (<real size> cm, about as long as <her|his> forearm). Leave this line out when the product is
not on screen.]
[video 1 shows ONLY the camera angle, framing and pacing to copy; do not copy the faces of the people in it.
Only when a reference ad is used.]

Shots:
Shot 1 (0-3s): <framing>, <PERSON LABEL> <one visible action>, says "<exact line>".
Shot 2 (3-6s): <framing>, <action>, says "<exact line>".

Voice & delivery: <FROZEN VOICE SENTENCE OF THIS PERSON>. Real conversational delivery with small pauses, light
gestures, eyebrows moving. Exactly these words, nothing added.

Audio: only these lines spoken by the person on screen with matching lip movement. <ROOM SOUND>. No music.
No narration.

Constraints: IMPORTANT: the picture must be completely clean. NO subtitles, NO captions, NO burned-in text, NO
letters or words anywhere in the frame, no logos, no watermark.
```

## 3. Dialogue turn (drama scene, one speaker per clip)

```
Style: Photorealistic phone video of a real moment at home, filmed by someone in the room, natural handheld
movement, <place>. 9:16 vertical.

References: image 1 is <SPEAKER LABEL> (keep face, hair and clothes exactly). image 2 is <LISTENER LABEL> (keep face, hair and
clothes exactly).

Shots:
Shot 1 (0-4s): over <LISTENER LABEL>'s shoulder, <SPEAKER LABEL> <action>, says "<exact line>". <LISTENER LABEL> listens silently.
Shot 2 (4-6s): close-up of <LISTENER LABEL>, reacting with <one visible feeling>, silent.

Voice & delivery: only <SPEAKER LABEL> speaks. <FROZEN VOICE SENTENCE OF THE SPEAKER>. Exactly these words, nothing added.
<LISTENER LABEL> says nothing.

Audio: <SPEAKER LABEL>'s line with matching lip movement. <ROOM SOUND>. No music. No narration.

Constraints: IMPORTANT: the picture must be completely clean. NO subtitles, NO captions, NO burned-in text, NO
letters or words anywhere in the frame, no logos, no watermark.
```

## 4. Reaction or two-shot (nobody speaks)

```
Style: Photorealistic phone video, natural handheld movement, <place>. 9:16 vertical.
References: image 1 is <PERSON A LABEL>, image 2 is <PERSON B LABEL> (keep faces, hair and clothes exactly).
Shots:
Shot 1 (0-3s): medium two-shot, <PERSON A LABEL> and <PERSON B LABEL> <one shared action, e.g. both stare at the glowing bottle>, silent.
Audio: <ROOM SOUND> only. Nobody speaks. No music.
Constraints: IMPORTANT: the picture must be completely clean. NO subtitles, NO captions, NO burned-in text, NO
letters or words anywhere in the frame, no logos, no watermark.
```

## Frozen voice sentences (write once per person, paste unchanged into every clip)

```
<PERSON LABEL> speaks <language> with a natural <accent> accent, <age>-year-old <gender> voice, <warm | dry | teasing |
excited>, <slow | medium | quick> pace.
```

## Room sound lines (match the place you see)

| Place                         | Line                                                                     |
| ----------------------------- | ------------------------------------------------------------------------ |
| Kitchen, living room, bedroom | Quiet small room, clean close voice, no background noise, no hiss.       |
| Car                           | Car interior, engine off, soft cabin sound, clean close voice.           |
| Street                        | Light outdoor air and distant traffic, voice clear and close.            |
| Office, waiting room          | Quiet room with a soft air-conditioning hum, clean voice.                |
| Hall, stage                   | Short light room echo, words crisp, light audience sounds between lines. |

## 5. Start-frame-only engine (for example Veo through a reseller)

The engine takes one start image and no references. Make the picture in the image step, then animate it.

Scene still (image model; attach the character plates and the product plate here, never in the video step):

```
Style: Candid smartphone photo, natural colours, slight grain, real skin texture, no retouching.
References: image 1 is <PERSON A LABEL>, image 2 is <PERSON B LABEL>, image 3 is the product (<real size> cm).
<scene block, word for word for every still of this scene: "Set: ... In it: ...">.
Visual: <the clip's opening framing>, <who is where>, <one action just before the line>.
No text anywhere in the image.
```

Later still in the same scene (the approved scene still attached as image 1; a person who enters now gets their
character plate attached as image 2):

```
Same room, same people, same clothes, same light as image 1. <scene block, word for word>. [Image 2 is <PERSON
LABEL>, now in the room.] Change only: <new framing>, <new action>.
No text anywhere in the image.
```

Clip (start image = the scene still; never a character sheet):

```
Style: Photorealistic phone video, natural handheld movement, <place>. 9:16 vertical.
Shots:
Shot 1 (0-4s): <framing>, <SPEAKER LABEL> <action>, says "<exact line>".
Hard cut.
Shot 2 (4-6s): close-up of <LISTENER LABEL>, reacting with <one visible feeling>, silent.
Voice & delivery: only <SPEAKER LABEL> speaks. <FROZEN VOICE SENTENCE OF THE SPEAKER>. Exactly these words, nothing added.
Audio: <ROOM SOUND>. No music. No narration.
Constraints: IMPORTANT: the picture must be completely clean. NO subtitles, NO captions, NO burned-in text, NO
letters or words anywhere in the frame, no logos, no watermark. Same characters, clothes and set as the first frame.
```

Two shots per clip at most; leave an end frame empty on a two-shot clip.
