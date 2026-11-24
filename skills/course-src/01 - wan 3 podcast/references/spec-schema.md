# Spec schema

The driver's input. One JSON file per ad.

```jsonc
{
  "project": "string",           // label only, shown in budget output
  "cast": "women",               // women | men | mixed - drives pronouns in the
                                 // one-mouth rule and cut grammar. Default: mixed
  "wpm": 165,                    // natural-speech rate for the advisory column
  "chunkSeconds": 30,            // Wan's per-generation window

  "environment": "string",       // appended to the look block. Studio, lighting,
                                 // mics, background. Optional but recommended

  "framing":       "string",     // optional - overrides the proven framing block
  "negatives":     "string",     // optional - overrides the negatives block
  "imperfections": "string",     // optional - overrides the imperfections block

  "hosts": [
    {
      "id": "A",                 // short key used by beats
      "label": "Woman 1",        // how the prompt names them. REQUIRED
      "image": "@image1",        // their close-up plate. REQUIRED, unique
      "audio": "File 1",         // their voice reference. unique
      "side": "left",            // documentation only - keep it accurate
      "persona": "has a curious, skeptical, slightly amused personality"
    }
  ],

  "refs": [
    { "slot": "@image3", "kind": "wide",    "desc": "..." },
    { "slot": "@image4", "kind": "product", "desc": "..." },
    { "slot": "@image5", "kind": "other",   "desc": "free-form description" }
  ],

  "chunks": [
    {
      "n": 1,                    // chunk number. Drives the timecode header:
                                 // chunk 6 -> "2:30 to 3:00"
      "beats": [ /* see below */ ]
    }
  ]
}
```

## Beat shapes

**Dialogue** — a host speaking in their close-up.

```jsonc
{ "host": "A",
  "line": "spoken words",
  "action":   "laughs it off",           // optional - speaker, during the line
  "reaction": "raises an eyebrow" }      // optional - the OTHER host, listening
```

**Dialogue with product** — same, plus the host handling it.

```jsonc
{ "host": "B", "line": "...",
  "prop": "lifts the bottle and turns it so the label faces camera",
  "propSlot": "@image4" }                // optional - defaults to the product ref
```

**Wide shot with dialogue** — `slot` (a `kind:"wide"` ref) plus `host`.

```jsonc
{ "slot": "@image3", "host": "A", "line": "..." }
```

**Cutaway insert** — `slot`, no `host`. `line` is a shot description, not
dialogue, and is excluded from the word budget.

```jsonc
{ "slot": "@image4", "line": "Tight insert on the product, label legible..." }
```

**Silent hold** — a reaction beat with no dialogue.

```jsonc
{ "host": "B", "silent": true, "reaction": "gives a knowing reaction with her mouth closed" }
```

## What the validator enforces

Errors (block `build`):

- host missing `label` or `image`
- two hosts sharing an `image` or `audio` slot
- a beat referencing an unknown host or an undeclared slot
- a beat with neither `host` nor `slot`
- a non-silent, non-cutaway beat with no `line`
- a chunk over the 123-word ceiling
- `propSlot` not declared in `refs`

Warnings (advisory):

- host with no `audio` — Wan invents a voice
- slot numbers not contiguous from 1
- chunk under 75 words, or over 10 beats
- a chunk that never cuts between speakers
- a chunk with no reaction or silent beat
- `prop` used with no `kind:"product"` ref declared
