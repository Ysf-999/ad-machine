# Reference slots — wiring images and audio

Wan 3.0 binds references by **ordinal upload order**. `@image1` is the first
image you upload, `@image2` the second. The names in the prompt are pointers
to upload positions, not to filenames. Get the order wrong and host A speaks
with host B's face.

## The standard two-host wiring

This covers ~90% of podcast ads:

| Slot | Content | Spec field |
|---|---|---|
| `@image1` | Left host, close-up plate | `hosts[0].image` |
| `@image2` | Right host, close-up plate | `hosts[1].image` |
| `File 1` | Left host voice | `hosts[0].audio` |
| `File 2` | Right host voice | `hosts[1].audio` |

Audio references are named `File N` in the prompt body, matching the
`reference_audio_urls` upload order — the same ordinal rule as images, but a
separate sequence. File 1 is the first audio upload, not the first reference
overall.

**Left/right is a real constraint.** Whichever host sits on the left in the
plate must stay on the left in every shot. Put it in `hosts[].side` and keep
the wide plate consistent with it, or the cut between close-ups will feel
like the two of them swapped chairs.

## Adding a product

Declare it as a ref with `kind: "product"`:

```json
{ "slot": "@image4", "kind": "product",
  "desc": "Keep the label facing camera and fully legible whenever it is in frame." }
```

The driver then emits the packaging lock in the preamble automatically:
exact label, exact typography, exact colour, exact container shape, do not
redesign.

Two ways to get the product on screen:

**1. In a host's hands** — `prop` on a dialogue beat. The host keeps talking;
the product enters the shot they are already in.

```json
{ "host": "B",
  "line": "But this is the one I kept in my bag...",
  "prop": "lifts the bottle off the desk and turns it so the label faces camera" }
```

Write the `prop` text as a physical action that suits the product. A bottle
gets lifted and turned; a jar gets unscrewed; a sachet gets torn; a device
gets clicked on. Match the action to what the thing actually is — a generic
"holds up the product" renders as a hand holding a blob.

**2. As a cutaway insert** — a beat with `slot` and no `host`. No dialogue
runs over it, so it costs ~1.5s of screen time and zero words. Use it right
after a host says something that makes the viewer want to look at the thing.

```json
{ "slot": "@image4",
  "line": "Tight insert on the product sitting on the desk between the two microphones, label fully legible, shallow depth of field, same warm studio light." }
```

The `line` on a cutaway is a **shot description**, not dialogue. The driver
knows the difference and excludes it from the word budget.

## Wide shots and multicam

If the operator supplies one image with both hosts in frame, declare it
`kind: "wide"`:

```json
{ "slot": "@image3", "kind": "wide",
  "desc": "Woman 1 is seated on the left, Woman 2 on the right, exactly as in the close ups." }
```

That unlocks the three-angle cut pattern:

- **wide** `@image3` — both hosts, establishes the room and the geography
- **close-up** `@image1` — left host
- **close-up** `@image2` — right host

A wide beat can carry dialogue. Give it both `slot` and `host`:

```json
{ "slot": "@image3", "host": "A", "line": "So what actually changed first?" }
```

which renders as a hard cut to the wide, with the speaker named inside the
frame and the other host explicitly held silent — otherwise Wan animates both
mouths in the two-shot, which is the most common wide-shot failure.

**Where wides earn their place:** the opening beat of chunk 1 (establish the
room once), and one mid-roll reset every 60–90s. Cutting wide on every third
beat destroys the intimacy that makes the format work. The close-ups are the
ad; the wide is punctuation.

## Slot numbering

Number contiguously from 1 across all references — hosts first, then extras.
A gap (`@image1`, `@image2`, `@image7`) means the upload order cannot match
the slot numbers, and the driver warns about it. Renumber instead of
uploading padding.
