#!/usr/bin/env node
// wan3-podcast-ads driver
//
// Turns a podcast-ad spec (JSON) into self-contained Wan 3.0 chunk prompts,
// and checks the things that actually break a render: word budget per 30s
// chunk, reference-slot wiring, speaker->audio mapping, and cut grammar.
//
//   node driver.mjs build <spec.json>            # all chunks
//   node driver.mjs build <spec.json> --chunk 6  # one chunk
//   node driver.mjs check <spec.json>            # validation only
//   node driver.mjs budget <spec.json>           # per-chunk timing table
//   node driver.mjs scaffold <out.json> --minutes 3 --hosts 2
//
// Every chunk printed by `build` is a COMPLETE prompt. Wan 3.0 renders each
// 30s chunk as its own generation, so the identity/style preamble is repeated
// in full every time. That repetition is the point, not a bug.

import { readFileSync, writeFileSync, existsSync } from "node:fs";

/* ------------------------------------------------------------------ utils */

const words = (s) => String(s ?? "").trim().split(/\s+/).filter(Boolean).length;

const mmss = (sec) => {
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
};

const die = (msg) => {
  console.error(`\x1b[31mERROR\x1b[0m ${msg}`);
  process.exit(1);
};

const arg = (flag, fallback) => {
  const i = process.argv.indexOf(flag);
  return i === -1 ? fallback : process.argv[i + 1];
};

/* ----------------------------------------------------------------- defaults */

// Calibrated against the one chunk we KNOW rendered well: the operator's
// chunk 6 - 8 dialogue beats + 1 silent reaction, 123 words, 30s window.
//
// Note the tension this exposes: 123 words in 30s is ~246 wpm nominal, far
// above natural speech (~165 wpm). So the word count, not the clock, is the
// gate here - it is the only number grounded in a render that actually worked.
// The seconds column in `budget` is advisory only: it tells you how the same
// text would read at a natural pace, which is useful for spotting a chunk
// that is truly bloated rather than merely dense.
const DEFAULTS = {
  fps: 24,
  wpm: 165, // natural-speech reference for the advisory seconds column
  chunkSeconds: 30,
  cutOverhead: 0.3, // pre-roll before first word + ~0.2s hold after last word
  wordsCeiling: 123, // proven to render - do not exceed
  wordsFloor: 75, // below this the chunk drags
  beatsCeiling: 10, // proven chunk had 9
};

const PRESET_FRAMING =
  "Medium close framing from roughly chest to top of head. Camera at seated eye level. " +
  "Locked tripod cameras. No cinematic camera movement. No artificial push ins. " +
  "No floating camera. No background changes.";

const PRESET_NEGATIVES =
  "No crossfades. No morphing between {{many}}. No split screen. No dramatic zooms. " +
  "No subtitles. No background music. Natural quiet studio room tone only. " +
  "Extremely accurate lip sync.";

const PRESET_IMPERFECTIONS =
  "Allow tiny natural imperfections such as breathing, swallowing, fingers moving near " +
  "the microphone, small posture changes and spontaneous facial reactions.";

/* ------------------------------------------------------------------- load */

function load(path) {
  if (!existsSync(path)) die(`spec not found: ${path}`);
  let spec;
  try {
    spec = JSON.parse(readFileSync(path, "utf8"));
  } catch (e) {
    die(`spec is not valid JSON: ${e.message}`);
  }
  spec.fps ??= DEFAULTS.fps;
  spec.wpm ??= DEFAULTS.wpm;
  spec.chunkSeconds ??= DEFAULTS.chunkSeconds;
  spec.hosts ??= [];
  spec.refs ??= [];
  spec.chunks ??= [];
  for (const h of spec.hosts) h.id = String(h.id);
  return spec;
}

const hostById = (spec, id) => spec.hosts.find((h) => h.id === String(id));

/* -------------------------------------------------------------- validation */

function validate(spec) {
  const problems = [];
  const warn = (m) => problems.push({ level: "warn", m });
  const err = (m) => problems.push({ level: "error", m });

  if (spec.hosts.length < 1) err("spec.hosts is empty - at least one host required");

  const seenImg = new Map();
  const seenAud = new Map();
  for (const h of spec.hosts) {
    if (!h.image) err(`host ${h.id} (${h.label ?? "?"}) has no image slot`);
    if (!h.audio) warn(`host ${h.id} has no audio slot - Wan will invent a voice`);
    if (!h.label) err(`host ${h.id} has no label (e.g. "Woman 1")`);
    if (h.image && seenImg.has(h.image))
      err(`image slot ${h.image} is shared by hosts ${seenImg.get(h.image)} and ${h.id} - each host needs their own`);
    if (h.audio && seenAud.has(h.audio))
      err(`audio slot ${h.audio} is shared by hosts ${seenAud.get(h.audio)} and ${h.id} - voices will bleed`);
    if (h.image) seenImg.set(h.image, h.id);
    if (h.audio) seenAud.set(h.audio, h.id);
  }

  const declared = new Set([
    ...spec.hosts.map((h) => h.image).filter(Boolean),
    ...spec.refs.map((r) => r.slot).filter(Boolean),
  ]);

  // slot numbering should be contiguous from 1 - Wan binds by ordinal upload order
  const nums = [...declared]
    .map((s) => Number(String(s).replace(/\D+/g, "")))
    .filter((n) => Number.isFinite(n))
    .sort((a, b) => a - b);
  nums.forEach((n, i) => {
    if (n !== i + 1)
      warn(`reference slots are not contiguous from 1 (got ${nums.join(", ")}) - upload order must match slot numbers`);
  });

  if (!spec.chunks.length) err("spec.chunks is empty - nothing to build");

  spec.chunks.forEach((c, ci) => {
    const n = c.n ?? ci + 1;
    if (!Array.isArray(c.beats) || !c.beats.length) {
      err(`chunk ${n} has no beats`);
      return;
    }
    let spoken = 0;
    c.beats.forEach((b, bi) => {
      const where = `chunk ${n} beat ${bi + 1}`;
      const isCutaway = b.slot && b.host === undefined;
      if (b.slot) {
        if (!declared.has(b.slot)) err(`${where} uses undeclared slot ${b.slot}`);
      }
      if (b.host !== undefined && !hostById(spec, b.host))
        err(`${where} references unknown host "${b.host}"`);
      if (!b.slot && b.host === undefined) err(`${where} has neither host nor slot`);

      if (!b.silent && !b.line && !isCutaway)
        err(`${where} has no line and is not marked silent`);
      if (b.silent && b.line) warn(`${where} is marked silent but carries a line - line ignored`);

      if (b.prop) {
        const slot = b.propSlot ?? spec.refs.find((r) => r.kind === "product")?.slot;
        if (!slot)
          warn(
            `${where} handles a prop but no {"kind":"product"} ref is declared - ` +
              `Wan will invent the packaging`,
          );
        else if (b.propSlot && !declared.has(b.propSlot))
          err(`${where} propSlot ${b.propSlot} is not declared in refs`);
        if (b.host === undefined && !b.slot) err(`${where} has a prop but nobody to hold it`);
      }

      // a cutaway's text is a shot description, not spoken dialogue
      if (!b.silent && !isCutaway) spoken += words(b.line);
    });

    const t = timing(spec, c);
    if (t.words > DEFAULTS.wordsCeiling)
      err(
        `chunk ${n}: ${t.words} words exceeds the proven ${DEFAULTS.wordsCeiling}-word ceiling - move a line to the next chunk`,
      );
    else if (t.words < DEFAULTS.wordsFloor)
      warn(`chunk ${n}: only ${t.words} words - thin for 30s, the hold at the end will drag`);
    if (t.beats > DEFAULTS.beatsCeiling)
      warn(`chunk ${n}: ${t.beats} beats - more than ${DEFAULTS.beatsCeiling} cuts in 30s reads as choppy`);

    const speakers = new Set(c.beats.filter((b) => !b.slot && b.host !== undefined).map((b) => String(b.host)));
    if (spec.hosts.length > 1 && speakers.size === 1)
      warn(`chunk ${n} never cuts - one speaker for the whole 30s reads as a monologue, not a podcast`);

    const reacted = c.beats.some((b) => b.silent || b.reaction);
    if (!reacted) warn(`chunk ${n} has no listener reaction or silent beat - add one, it is what makes the cut feel real`);
    void spoken;
  });

  return problems;
}

/* ------------------------------------------------------------------ timing */

function timing(spec, chunk) {
  const beats = chunk.beats ?? [];
  const spoken = (b) => !b.silent && !(b.slot && b.host === undefined);
  const w = beats.reduce((a, b) => a + (spoken(b) ? words(b.line) : 0), 0);
  const speech = (w / spec.wpm) * 60;
  // silent reactions and product cutaways cost screen time but no words
  const held = beats.filter((b) => !spoken(b)).length;
  const overhead = beats.length * DEFAULTS.cutOverhead + held * 1.2;
  return { words: w, beats: beats.length, speech, overhead, total: speech + overhead };
}

/* ------------------------------------------------------------ prompt build */

// The proven prompt says "Only the woman currently speaking moves her lips",
// not "the person ... their lips". Naming the cast concretely is part of what
// makes the identity lock hold, so derive the right nouns instead of hedging.
const CAST = {
  women: { one: "woman", many: "women", poss: "her", possPl: "their" },
  men: { one: "man", many: "men", poss: "his", possPl: "their" },
  mixed: { one: "person", many: "speakers", poss: "their", possPl: "their" },
};

function preamble(spec) {
  const H = spec.hosts;
  const c = CAST[spec.cast ?? "mixed"] ?? CAST.mixed;
  const out = [];

  // 1. identity lock
  const idParts = H.map((h) => `${h.label} exactly from ${h.image}`);
  out.push(
    `Preserve ${joinAnd(idParts)}. Preserve their real facial structure, skin texture, hairstyle, ` +
      `clothing, microphone, chair, lighting and podcast environment. Do not beautify or smooth their faces.`,
  );

  // 2. extra reference slots
  for (const r of spec.refs) {
    if (r.kind === "product")
      out.push(
        `${r.slot} is the product. Reproduce it exactly as shown in ${r.slot} - exact label, exact ` +
          `typography, exact colour, exact container shape. Do not redesign, restyle or re-letter it.` +
          (r.desc ? ` ${r.desc}` : ""),
      );
    else if (r.kind === "wide")
      out.push(
        `${r.slot} is the wide two shot of the room. Use it for the wide angle only. The seating ` +
          `positions, background and lighting in ${r.slot} must match the close ups exactly.` +
          (r.desc ? ` ${r.desc}` : ""),
      );
    else if (r.desc) out.push(`${r.slot}: ${r.desc}`);
  }

  // 3. look
  out.push(
    `Professional but visually natural podcast recording. ${spec.framing ?? PRESET_FRAMING}` +
      (spec.environment ? ` ${spec.environment}` : ""),
  );

  // 4. personas
  const personas = H.filter((h) => h.persona).map((h) => `${h.label} ${h.persona}.`);
  if (personas.length) out.push(personas.join(" "));

  // 5. the one-mouth rule - the single highest-value line in the whole prompt
  const listener =
    H.length > 2
      ? `The listening ${c.many} keep ${c.possPl} mouths naturally closed and react`
      : `The listening ${c.one} keeps ${c.poss} mouth naturally closed and reacts`;
  out.push(
    `Only the ${c.one} currently speaking moves ${c.poss} lips. ${listener} with tiny eyebrow movements, ` +
      `nods, smiles, blinks, glances and changes of expression.`,
  );

  // 6. cut grammar
  out.push(
    `Every speaker change uses an immediate hard cut to that ${c.one}'s camera. Cut approximately 2 to 4 frames ` +
      `before ${c.poss} first spoken word so the edit feels like a real multicamera podcast. Hold the speaker for ` +
      `roughly 0.2 seconds after ${c.poss} final word before cutting away.`,
  );

  // 7. negatives + imperfections
  out.push((spec.negatives ?? PRESET_NEGATIVES).replace("{{many}}", c.many));
  out.push(spec.imperfections ?? PRESET_IMPERFECTIONS);

  // 8. audio binding - last, immediately before the beat sheet.
  // Consecutive lines, not separate paragraphs: they read as one mapping table.
  const audio = H.filter((h) => h.audio).map(
    (h) => `for reference_audio_urls use ${h.audio} for ${h.label}`,
  );
  if (audio.length) out.push(audio.join("\n"));

  return out.join("\n\n");
}

function joinAnd(parts) {
  if (parts.length === 1) return parts[0];
  if (parts.length === 2) return `${parts[0]} and ${parts[1]}`;
  return `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

function beatSheet(spec, chunk, index) {
  const lines = [];
  const start = (chunk.n ?? index + 1) - 1;
  const t0 = start * spec.chunkSeconds;
  const t1 = t0 + spec.chunkSeconds;

  lines.push(`CHUNK ${chunk.n ?? index + 1}`);
  lines.push(`${mmss(t0)} to ${mmss(t1)}`);
  lines.push("");

  const productSlot = spec.refs.find((r) => r.kind === "product")?.slot;
  const wideSlots = new Set(spec.refs.filter((r) => r.kind === "wide").map((r) => r.slot));

  let onScreen = null;
  const lastIdx = chunk.beats.length - 1;

  chunk.beats.forEach((b, i) => {
    const host = b.host !== undefined ? hostById(spec, b.host) : null;
    const isWide = b.slot && wideSlots.has(b.slot);
    // the shot we cut to; for a wide beat that is the wide plate, and the
    // speaker is named inside it rather than becoming the shot itself
    const ref = b.slot ?? host?.image;
    const isFirst = i === 0;
    const isLast = i === lastIdx;

    // --- shot instruction
    if (isLast && b.silent) {
      // the closing hold - named as an end anchor so Wan does not cut away
      lines.push(`End on ${ref}.`);
    } else if (isFirst) {
      lines.push(isWide ? `Start on the wide shot ${ref}.` : `Start on ${ref}.`);
    } else if (isWide) {
      lines.push(`Hard cut to the wide shot ${ref} showing both hosts in frame.`);
    } else if (b.slot) {
      lines.push(`Cut to ${b.slot}.`);
    } else if (ref !== onScreen) {
      lines.push(`Hard cut to ${ref}.`);
    } else {
      lines.push(`Keep ${ref} on screen.`);
    }
    lines.push("");
    onScreen = ref;

    // --- content
    if (b.silent) {
      const who = host ? host.image : ref;
      lines.push(`${who} ${b.reaction ?? "reacts with their mouth closed"}. No dialogue.`);
    } else if (isWide && host) {
      // wide two-shot with dialogue: name the speaker inside the frame
      const others = spec.hosts.filter((h) => h.id !== host.id);
      lines.push(`In the wide shot, ${host.label} (${host.image}) speaks: “${b.line}”${b.action ? ` ${b.action}` : ""}`);
      if (others.length)
        lines.push(
          "",
          `${joinAnd(others.map((h) => `${h.label} (${h.image})`))} ${others.length > 1 ? "stay" : "stays"} ` +
            `silent in frame with ${others.length > 1 ? "their mouths" : "mouth"} closed${b.reaction ? `, ${b.reaction}` : ""}.`,
        );
    } else if (b.slot && !host) {
      // pure cutaway - product insert, no dialogue over the cut
      lines.push(`${b.line ?? b.insert ?? `Hold on ${b.slot}.`} No dialogue over this shot.`);
    } else {
      const action = b.action ? ` ${b.action}` : "";
      lines.push(`${ref}: “${b.line}”${action}`);
      if (b.reaction) {
        const other = spec.hosts.find((h) => h.image !== ref);
        if (other) lines.push("", `${other.image} ${b.reaction} while listening. Mouth closed.`);
      }
    }

    // --- product handling, appended to whatever shot is live
    if (b.prop) {
      const slot = b.propSlot ?? productSlot;
      lines.push(
        "",
        slot
          ? `${host?.image ?? ref} ${b.prop}. The product is the exact product from ${slot} - same label, ` +
              `same typography, same colour, same container shape. Do not redesign it.`
          : `${host?.image ?? ref} ${b.prop}.`,
      );
    }

    lines.push("");
  });

  // explicit end anchor - Wan holds the last named reference
  const last = chunk.beats[lastIdx];
  const lastRef = last.slot ?? hostById(spec, last.host)?.image;
  if (!last.silent) {
    lines.push(`End on ${lastRef}.`);
  }

  return lines.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

function buildChunk(spec, chunk, index) {
  return `${preamble(spec)}\n\n${beatSheet(spec, chunk, index)}`;
}

/* --------------------------------------------------------------- commands */

function cmdCheck(spec, { quiet } = {}) {
  const problems = validate(spec);
  const errors = problems.filter((p) => p.level === "error");
  const warns = problems.filter((p) => p.level === "warn");
  if (!quiet) {
    for (const p of problems) {
      const tag = p.level === "error" ? "\x1b[31mERROR\x1b[0m" : "\x1b[33mWARN \x1b[0m";
      console.log(`${tag} ${p.m}`);
    }
    console.log(
      problems.length
        ? `\n${errors.length} error(s), ${warns.length} warning(s)`
        : "\x1b[32mOK\x1b[0m  spec is clean",
    );
  }
  return errors.length;
}

function cmdBudget(spec) {
  const total = spec.chunks.length * spec.chunkSeconds;
  console.log(
    `${spec.project ?? "(untitled)"} - ${spec.chunks.length} chunks x ${spec.chunkSeconds}s = ${mmss(total)} @ ${spec.wpm} wpm\n`,
  );
  console.log("chunk  window        beats  words  fit         nat.read");
  console.log("-----  ------------  -----  -----  ----------  --------");
  let tw = 0;
  spec.chunks.forEach((c, i) => {
    const n = c.n ?? i + 1;
    const t = timing(spec, c);
    tw += t.words;
    const t0 = (n - 1) * spec.chunkSeconds;
    const win = `${mmss(t0)}-${mmss(t0 + spec.chunkSeconds)}`;
    const fit =
      t.words > DEFAULTS.wordsCeiling
        ? "\x1b[31mOVER CAP \x1b[0m"
        : t.words < DEFAULTS.wordsFloor
          ? "\x1b[33mthin     \x1b[0m"
          : "\x1b[32mgood     \x1b[0m";
    console.log(
      `${String(n).padStart(5)}  ${win.padEnd(12)}  ${String(t.beats).padStart(5)}  ` +
        `${String(t.words).padStart(5)}  ${fit}  ${(t.total.toFixed(1) + "s").padStart(8)}`,
    );
  });
  console.log(
    `\ntotal words: ${tw}  |  per-chunk band: ${DEFAULTS.wordsFloor}-${DEFAULTS.wordsCeiling} words` +
      `\n"nat.read" = how long this text takes at ${spec.wpm} wpm natural speech. It will read` +
      `\nlonger than ${spec.chunkSeconds}s at proven density - that is expected, gate on words.`,
  );
}

function cmdBuild(spec, only) {
  if (cmdCheck(spec, { quiet: true }) > 0) {
    console.error("\x1b[31mrefusing to build - run `check` and fix the errors first\x1b[0m\n");
    cmdCheck(spec);
    process.exit(1);
  }
  const chunks = only
    ? spec.chunks.filter((c, i) => String(c.n ?? i + 1) === String(only))
    : spec.chunks;
  if (!chunks.length) die(`no chunk numbered ${only}`);

  chunks.forEach((c, i) => {
    const n = c.n ?? i + 1;
    const idx = spec.chunks.indexOf(c);
    console.log(`${"=".repeat(72)}`);
    console.log(
      `CHUNK ${n}  (${i + 1} of ${chunks.length} being built)  -  paste this ENTIRE block into Wan 3.0 as one generation`,
    );
    console.log(`${"=".repeat(72)}\n`);
    console.log(buildChunk(spec, c, idx));
    console.log("");
  });
}

function cmdScaffold(out) {
  const minutes = Number(arg("--minutes", 1));
  const nChunks = Math.max(1, Math.round((minutes * 60) / DEFAULTS.chunkSeconds));
  const spec = {
    project: "UNTITLED",
    cast: "women",
    wpm: DEFAULTS.wpm,
    chunkSeconds: DEFAULTS.chunkSeconds,
    environment: "",
    hosts: [
      { id: "A", label: "Woman 1", image: "@image1", audio: "File 1", side: "left", persona: "has a curious, skeptical, slightly amused personality" },
      { id: "B", label: "Woman 2", image: "@image2", audio: "File 2", side: "right", persona: "knows the subject better but speaks casually, like telling a friend something surprising rather than performing an advertisement" },
    ],
    refs: [],
    chunks: Array.from({ length: nChunks }, (_, i) => ({
      n: i + 1,
      beats: [
        { host: "A", line: "REPLACE ME" },
        { host: "B", line: "REPLACE ME" },
        { host: "A", silent: true, reaction: "gives a knowing reaction with her mouth closed" },
      ],
    })),
  };
  writeFileSync(out, JSON.stringify(spec, null, 2));
  console.log(`wrote ${out} - ${nChunks} chunk(s), ${mmss(nChunks * DEFAULTS.chunkSeconds)}`);
}

/* ------------------------------------------------------------------- main */

const [cmd, path] = process.argv.slice(2);
if (!cmd || !path) {
  console.log(`usage:
  node driver.mjs build    <spec.json> [--chunk N]
  node driver.mjs check    <spec.json>
  node driver.mjs budget   <spec.json>
  node driver.mjs scaffold <out.json> [--minutes 3]`);
  process.exit(1);
}

if (cmd === "scaffold") cmdScaffold(path);
else {
  const spec = load(path);
  if (cmd === "check") process.exit(cmdCheck(spec) > 0 ? 1 : 0);
  else if (cmd === "budget") cmdBudget(spec);
  else if (cmd === "build") cmdBuild(spec, arg("--chunk", null));
  else die(`unknown command: ${cmd}`);
}
