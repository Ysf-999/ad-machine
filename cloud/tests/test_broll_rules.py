"""No-network tests for the b-roll rules: tools/banned.py, the ban + taste parts of tools/moments.py,
the new preflight checks (T33, T49, T51, T09/T06, plan windows in T06) and rawedit's T50 default / ban refusal.
Everything runs on a temporary repo root; nothing reads footage/raw, calls ffmpeg, Claude or Drive."""
import ast
import contextlib
import io
import json
import pathlib
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
SCRATCH = ROOT / "cloud" / ".scratch"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import banned  # noqa: E402
import moments  # noqa: E402
import preflight as pf  # noqa: E402
import rawedit  # noqa: E402

A = "1AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"   # whole clip banned
W = "1WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW"   # hard window 10-12, soft text 20-25 "too slow", scoped 30-32
G = "1GGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG"   # clean clip (mitt take)
C = "1CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"   # clean clip

BAN = {
    "banned_ids": {A: "owner 11/20: blurry"},
    "banned_name_patterns": ["- Studio"],
    "banned_drive_folders": ["Old Edits"],
    "banned_windows": {W: "cushion 10-12 banned (owner 11/8: not satisfying); bed 20-25 too slow; "
                          "doormat 30-32 banned for 'embedded hair' lines (owner #1211); husky 40-44 still fine"},
    "notes": {"WEB3/vac_mk36522 + WEB/vac_mk36522": "owner: vacuum clip is fake"},
}


class Root:
    """A throwaway repo root with footage/BANNED_CLIPS.json, projects/ and moment cards."""

    def __init__(self, ban=BAN):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.td = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.p = pathlib.Path(self.td.name)
        (self.p / "footage" / "moments" / "cards").mkdir(parents=True)
        (self.p / "projects").mkdir()
        (self.p / "feedback").mkdir()
        if ban is not None:
            (self.p / "footage" / "BANNED_CLIPS.json").write_text(json.dumps(ban))

    def proj(self, name, plan=None, **files):
        d = self.p / "projects" / name
        d.mkdir(parents=True)
        if plan is not None: (d / "plan.json").write_text(json.dumps(plan))
        for k, v in files.items():
            f = d / k.replace("__", "/"); f.parent.mkdir(parents=True, exist_ok=True); f.write_text(v)
        return d

    def card(self, fid, **c):
        (self.p / "footage" / "moments" / "cards" / f"{fid}.json").write_text(json.dumps(c))

    def close(self):
        self.td.cleanup()


class BannedParseTests(unittest.TestCase):
    def setUp(self):
        self.r = Root(); self.root = self.r.p

    def tearDown(self):
        self.r.close()

    def test_parse_is_conservative(self):
        ws = banned.load(self.root)["windows"][W]
        self.assertEqual([(w["in"], w["out"], w["hard"]) for w in ws], [(10.0, 12.0, True), (30.0, 32.0, False)])
        self.assertEqual(ws[1]["scope"], "for 'embedded hair' lines")
        self.assertEqual(banned.parse_windows("husky 35-39 still fine; cat-tree bed 38.8-44.1 too slow"), [])
        self.assertEqual(banned.parse_windows("pinch clump 0-3 banned as a 'pet hair mess' shot (owner)")[0][:3],
                         (0.0, 3.0, "as a 'pet hair mess' shot"))

    def test_machine_readable_windows_merge(self):
        b = dict(BAN, banned_windows_s={C: [[1, 2], [5, 6, "for hook lines"]], W: [[10, 12]]})
        (self.root / "footage" / "BANNED_CLIPS.json").write_text(json.dumps(b))
        win = banned.load(self.root)["windows"]
        self.assertEqual(len(win[W]), 2)                       # 10-12 not duplicated
        self.assertEqual([(w["in"], w["hard"]) for w in win[C]], [(1.0, True), (5.0, False)])

    def test_clip_banned_every_reference_form(self):
        for ref in (A, f"footage/raw/{A}.mov", f"m:{A[:10]}@3.0"):
            self.assertIn("banned clip", banned.clip_banned(ref, root=self.root), ref)
        self.assertIn("banned name", banned.clip_banned(C, "Couch - Studio.mp4", root=self.root))
        self.assertIn("Old Edits", banned.clip_banned("Old Edits/x.mp4", root=self.root))
        self.assertIn("notes", banned.clip_banned("library/WEB3/vac_mk36522.mp4", root=self.root))
        self.assertIsNone(banned.clip_banned(G, "Couch - mitt take.mp4", root=self.root))
        self.assertIsNone(banned.clip_banned("library/WEB3/vac_mk99999.mp4", root=self.root))

    def test_missing_ban_list_fails_closed(self):
        r = Root(ban=None)
        try:
            self.assertIn("not found", banned.clip_banned(G, root=r.p))
            self.assertTrue(banned.blockers({"shots": [{"at": 0, "src": G}]}, r.p))
        finally:
            r.close()

    def test_window_banned(self):
        self.assertIn("10-12", banned.window_banned(W, 11, 13, root=self.root))
        self.assertIsNone(banned.window_banned(W, 12, 14, root=self.root))          # only touches the edge
        self.assertIsNone(banned.window_banned(W, 20, 25, root=self.root))          # "too slow" is not a ban
        self.assertIsNone(banned.window_banned(W, 41, 43, root=self.root))          # "still fine"
        self.assertIn("embedded hair", banned.window_banned(W, 30.5, 31, root=self.root))
        self.assertIsNone(banned.window_banned(W, 30.5, 31, root=self.root, scoped=False))
        self.assertIn("banned clip", banned.window_banned(A, 0, 1, root=self.root))  # whole clip first

    def test_basic_matches_old_is_banned(self):
        ids, pats = banned.ids_and_patterns(self.root)
        self.assertTrue(banned.basic(A, "x.mp4", ids, pats))
        self.assertTrue(banned.basic(C, "Couch - Studio.mp4", ids, pats))
        self.assertFalse(banned.basic(A[:10], "x.mp4", ids, pats))     # old rule: exact id only
        self.assertFalse(banned.basic(W, "x.mp4", ids, pats))          # windows never ban the whole clip

    def test_plan_hits_beats_and_shots(self):
        plan = {"aroll": {"fid": C, "file": f"{C}.mov", "name": "Ana take"},
                "beats": [{"n": 1, "segs": [{"in": 0, "out": 3}],
                           "broll": {"fid": W, "file": f"{W}.mp4", "in": 9.0, "dur": 2.0, "speed": 1.0},
                           "suggest": [{"fid": A}]},
                          {"n": 2, "segs": [{"in": 3, "out": 6}],
                           "broll": {"fid": G, "file": f"{G}.mp4", "in": 0, "dur": 2, "split": {"fid": A, "in": 1}}}],
                "real_v1": {"fid": A}}
        hits = banned.plan_hits(plan, self.root)
        self.assertEqual(sorted((h["where"], h["kind"]) for h in hits), [("beat 1 b-roll", "window"), ("beat 2 split", "clip")])
        vo = {"total": 10, "shots": [{"at": 0, "src": f"footage/raw/{W}.mp4", "in": 29.0},
                                     {"at": 2, "src": f"m:{G[:10]}@1.0", "hook_src": f"footage/raw/{A}.mp4"},
                                     {"at": 5, "src": "library/WEB/vac_mk36522.mp4"}]}
        hits = banned.plan_hits(vo, self.root)
        kinds = sorted(h["kind"] for h in hits)
        self.assertEqual(kinds, ["clip", "clip", "window-scoped"])
        self.assertEqual(len(banned.blockers(vo, self.root)), 2)
        sw = banned.shot_windows(vo)
        self.assertEqual([(w["in"], w["out"]) for w in sw], [(29.0, 31.0), (1.0, 4.0), (0.0, 5.0)])

    def test_banned_imports_only_the_standard_library(self):
        tree = ast.parse((TOOLS / "banned.py").read_text())
        mods = {n.name.split(".")[0] for x in ast.walk(tree) if isinstance(x, ast.Import) for n in x.names}
        mods |= {x.module.split(".")[0] for x in ast.walk(tree) if isinstance(x, ast.ImportFrom) and x.module}
        self.assertTrue(mods <= set(sys.stdlib_module_names), mods - set(sys.stdlib_module_names))


class MomentsTasteTests(unittest.TestCase):
    def setUp(self):
        self.r = Root(); self.root = self.r.p
        self.ps = [patch.object(moments, "ROOT", self.root), patch.object(moments, "CARDS", self.root / "footage/moments/cards")]
        for p in self.ps: p.start()

    def tearDown(self):
        for p in self.ps: p.stop()
        self.r.close()

    def test_window_ban(self):
        m = lambda a, b: {"fid": W, "start": a, "end": b}
        self.assertTrue(moments.window_ban(m(9, 11))[0])
        self.assertEqual(moments.window_ban(m(13, 18)), (False, ""))
        drop, note = moments.window_ban(m(29, 33), "mitt pulls hair off the doormat")
        self.assertFalse(drop); self.assertIn("embedded hair", note)
        self.assertTrue(moments.window_ban(m(29, 33), "embedded hair the vacuum leaves")[0])

    def test_owner_picks(self):
        log = self.root / "feedback" / "log.jsonl"
        rows = [{"id": 1, "text": f"change this clip to this https://drive.google.com/file/d/{G}/view"},
                {"id": 2, "text": f"never use https://drive.google.com/file/d/{C}/view again"},
                {"id": 3, "kind": "like", "text": f"love the strand in {W}"},
                {"id": 4, "text": "folder https://drive.google.com/drive/folders/1FFFFFFFFFFFFFFFFFFFFFFFFFFFF"}]
        log.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
        self.assertEqual(moments.owner_picks(log), {G: [1], W: [3]})

    def test_approved_projects_and_windows(self):
        log = self.root / "feedback" / "log.jsonl"
        log.write_text(json.dumps({"ad": "c-ad", "status": "approved"}) + "\n")
        self.r.proj("a-ad", {"locked": True, "total": 4, "shots": [{"at": 0, "src": f"footage/raw/{G}.mp4", "in": 2}]})
        self.r.proj("b-ad", {"total": 4, "shots": []}, **{"frameio.json": json.dumps({"cleaned": "2026-11-22"})})
        self.r.proj("c-ad", {"beats": [{"broll": {"fid": C, "in": 1, "dur": 2, "speed": 1.5}}]})
        self.r.proj("d-ad", {"total": 4, "shots": [{"at": 0, "src": f"footage/raw/{W}.mp4"}]})
        self.assertEqual(moments.approved_projects(log), {"a-ad", "b-ad", "c-ad"})
        aw = moments.approved_windows(log)
        self.assertEqual(aw[G[:10]], [(2.0, 6.0, "a-ad")])
        self.assertEqual(aw[C[:10]], [(1.0, 4.0, "c-ad")])
        self.assertNotIn(W[:10], aw)

    def test_fav_boost_is_modest(self):
        m = {"fid": G, "start": 2, "end": 5}
        fav = {"t06": [], "picked": {G: [1]}, "approved": {G[:10]: [(3, 6, "a-ad")]}}
        b, why = moments.fav_boost(m, fav, 0)
        self.assertAlmostEqual(b, moments.FAV_CAP); self.assertEqual(why, ["picked", "approved"])
        self.assertAlmostEqual(moments.fav_boost(m, fav, 3)[0], 0.0)          # faded by the 3rd use
        self.assertLess(moments.fav_boost(m, fav, 2)[0], 0.02 * 2 + 1e-9)     # never beats the fatigue penalty
        self.assertAlmostEqual(moments.fav_boost(m, {"t06": [G[:9]]}, 5)[0], moments.FAV_T06)
        self.assertAlmostEqual(moments.fav_boost(m, dict(fav, t06=[G[:9]]), 0)[0], moments.FAV_CAP)
        self.assertEqual(moments.fav_boost({"fid": C, "start": 0, "end": 1}, fav, 0), (0.0, []))

    def test_plan_fids_counts_vo_shots_not_suggestions(self):
        plan = {"beats": [{"broll": {"fid": C}, "suggest": [{"fid": A}]}], "intent": {"fid": A},
                "shots": [{"at": 0, "src": f"footage/raw/{G}.mp4"}, {"at": 1, "src": f"m:{W[:10]}@3.0"},
                          {"at": 2, "src": "library/web/x.mp4", "hook_src": f"footage/raw/{G}.mp4"}]}
        self.assertEqual(moments._plan_fids(plan, [W]), {C, G, W})
        self.assertEqual(moments._plan_fids(plan, []), {C, G})

    def test_usage_counts_hook_family_once(self):
        for n in ("ad-h1", "ad-h2"):
            self.r.proj(n, {"total": 2, "shots": [{"at": 0, "src": f"footage/raw/{G}.mp4"}]})
        self.r.proj("other", {"beats": [{"broll": {"fid": G}}]})
        self.assertEqual(moments.usage()[G], 2)


def write_ass(path, lines):
    head = "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(head + "".join(f"Dialogue: 0,{s},{e},Default,,0,0,0,,{t}\n" for s, e, t in lines))


class PreflightNewChecksTests(unittest.TestCase):
    def setUp(self):
        self.r = Root(); self.root = self.r.p
        self.ps = [patch.object(pf, "ROOT", self.root), patch.dict(pf._CARDS, clear=True)]
        for p in self.ps: p.start()

    def tearDown(self):
        for p in self.ps: p.stop()
        self.r.close()

    def test_t33_length(self):
        self.assertTrue(pf.check_length(120.0)[0].startswith("PASS T33"))
        self.assertTrue(pf.check_length(121.4)[0].startswith("FAIL T33"))
        self.assertIn("2:01.4", pf.check_length(121.4)[0])

    def test_t51_sale_line(self):
        rx = lambda p: re.compile(r"\b" + r"[\s\W_]*".join(re.escape(w) for w in p.split()) + r"\b", re.I)
        with patch.object(pf, "BANNED_PHRASES", [("mega sale", rx("mega sale"))]):   # brand.json banned_phrases
            d = self.r.proj("s1", {"vo": "This big sale ends Sunday"})
            self.assertTrue(pf.check_sale_line(d, pf.load_plan(d))[0].startswith("PASS T51"))
            d = self.r.proj("s2", {"script": [{"line": "Our early mega-sale deal"}]})
            self.assertTrue(pf.check_sale_line(d, pf.load_plan(d))[0].startswith("FAIL T51"))
            d = self.r.proj("s3", {"shots": [{"note": "early mega sale"}]})          # a note is not on screen
            self.assertTrue(pf.check_sale_line(d, pf.load_plan(d))[0].startswith("PASS"))
            d = self.r.proj("s4", {})
            write_ass(d / "EDIT_KIT" / "captions.ass", [("0:00:02.00", "0:00:02.50", "{\\b1}SALE"),
                                                       ("0:00:01.50", "0:00:02.00", "MEGA")])
            out = pf.check_sale_line(d, {})
            self.assertTrue(out[0].startswith("FAIL T51") and "EDIT_KIT/captions.ass" in out[0])

    def test_t49_flash(self):
        vo = lambda *ats, **kw: {"total": kw.get("total", 10), "shots": [{"at": a, "src": f"footage/raw/{s}.mp4", "in": 0}
                                                                          for a, s in ats]}
        d = self.r.proj("f1")
        out = pf.check_flash(d, vo((0, G), (3, C), (3.3, W), (6, A)))
        self.assertTrue(any(l.startswith("FAIL T49") and "0.30s" in l for l in out), out)
        out = pf.check_flash(d, vo((0, G), (3, C), (3.6, W), (6, A)))
        self.assertTrue(any(l.startswith("WARN T49") and "0.60s" in l for l in out) and not any("FAIL" in l for l in out), out)
        p = vo((0, G), (3, C), (3.3, W)); p["shots"][1]["flash_ok"] = "owner: copy the reference montage"
        self.assertFalse(any("FAIL" in l for l in pf.check_flash(d, p)))
        self.assertTrue(pf.check_flash(d, vo((0, G), (3, C), (6, A)))[0].startswith("PASS T49"))
        # contiguous source time from one clip (a speed ramp) is one window, not a flash
        ramp = {"total": 4, "shots": [{"at": 0, "src": f"footage/raw/{G}.mp4", "in": 0}, {"at": 1.5, "src": f"footage/raw/{G}.mp4", "in": 1.5, "speed": 1.0},
                                      {"at": 1.8, "src": f"footage/raw/{G}.mp4", "in": 1.8}]}
        self.assertTrue(pf.check_flash(d, ramp)[0].startswith("PASS T49"))

    def test_t49_card_cuts(self):
        d = self.r.proj("f2")
        plan = {"total": 4, "shots": [{"at": 0, "src": f"footage/raw/{G}.mp4", "in": 10.0}]}
        self.r.card(G, cuts=[10.3, 20.0], moments=[])
        out = pf.check_flash(d, plan)
        self.assertTrue(out[0].startswith("WARN T49") and "10.00-10.30s" in out[0], out)
        pf._CARDS.clear(); self.r.card(G, cuts=[10.3, 10.6, 10.9, 11.2], moments=[])   # swipe burst, not edits
        self.assertTrue(pf.check_flash(d, plan)[0].startswith("PASS T49"))

    def test_t09_repeat_in_one_ad(self):
        d = self.r.proj("r1")
        plan = {"total": 9, "shots": [{"at": 0, "src": f"footage/raw/{G}.mp4", "in": 2}, {"at": 3, "src": f"footage/raw/{C}.mp4"},
                                      {"at": 6, "src": f"footage/raw/{G}.mp4", "in": 3}]}
        out = pf.check_reuse(d, plan)
        self.assertTrue(out[0].startswith("FAIL T09"), out)
        plan["shots"][2]["in"] = 8
        self.assertTrue(pf.check_reuse(d, plan)[0].startswith("PASS T09"))

    def test_t09_mitt_take_across_hooks(self):
        body = [{"at": 3, "src": f"footage/raw/{C}.mp4", "in": 0}, {"at": 6, "src": f"footage/raw/{G}.mp4", "in": 0, "note": "mitt one-take"}]
        h1 = {"total": 9, "shots": [{"at": 0, "src": f"footage/raw/{W}.mp4", "in": 50}] + body}
        h2 = {"total": 9, "shots": [{"at": 0, "src": f"footage/raw/{A}.mp4", "in": 50}] + body}
        h3 = {"total": 12, "shots": [{"at": 0, "src": f"footage/raw/{G}.mp4", "in": 0.5, "note": "mitt one-take"}]
                                    + [dict(s, at=s["at"] + 3) for s in body]}   # its hook re-shows the body's mitt take
        d1 = self.r.proj("batch-h1", h1); self.r.proj("batch-h2", h2)
        self.assertTrue(pf.check_reuse(d1, h1)[0].startswith("PASS T09"))      # the shared body is by design
        self.r.proj("batch-h3", h3)
        out = pf.check_reuse(d1, h1)
        self.assertTrue(any(l.startswith("WARN T06/T09") and "batch-h3" in l for l in out), out)
        self.assertFalse(any(l.startswith("FAIL") for l in out))

    def test_t06_plan_windows(self):
        d = self.r.proj("b1", {"total": 4, "shots": [{"at": 0, "src": f"footage/raw/{W}.mp4", "in": 9}, {"at": 2, "src": f"footage/raw/{W}.mp4", "in": 30}]})
        out = pf.check_banned(d)
        self.assertTrue(any(l.startswith("FAIL T06") and "10-12" in l for l in out), out)
        self.assertTrue(any(l.startswith("WARN T06") and "embedded hair" in l for l in out), out)
        d = self.r.proj("b2", {"total": 4, "shots": [{"at": 0, "src": f"footage/raw/{A}.mp4"}]})
        out = pf.check_banned(d)
        self.assertEqual(sum(1 for l in out if A[:12] in l), 1, out)            # the file scan's line, not a duplicate
        d = self.r.proj("b3", {"total": 4, "shots": [{"at": 0, "src": f"footage/raw/{G}.mp4"}]})
        self.assertTrue(pf.check_banned(d)[0].startswith("PASS T06"))

    def test_new_lines_pass_the_approval_word_filter(self):
        d = self.r.proj("w1")
        lines = pf.check_flash(d, {}) + pf.check_reuse(d, {}) + pf.check_length(10) + pf.check_sale_line(d, {})
        for l in lines:
            for bad in ("SKIP", "UNAVAILABLE", "MANUAL", "NOT CHECKED"):
                self.assertNotIn(bad, l.upper(), l)


class RaweditTests(unittest.TestCase):
    def test_t50_caption_default_inside_safe_zone(self):
        mv = rawedit.DEFAULT_RULES["caption_margin_v"]
        self.assertEqual(mv, 640)   # the value the owner approved on Rug Cleaner v3
        self.assertLessEqual(rawedit.H - mv, round(rawedit.H * (1 - rawedit.SAFE["bottom"])) + 32)   # 32 px below Meta's guide line, by his choice

    def test_set_broll_ban_guard(self):
        r = Root()
        try:
            with patch.object(banned, "ROOT", r.p):
                with self.assertRaises(SystemExit) as e:
                    rawedit._ban_guard({"fid": W, "New file name": "cushion.mp4"}, 11.0, 13.0)
                self.assertIn("REFUSED T06", str(e.exception))
                with self.assertRaises(SystemExit):
                    rawedit._ban_guard({"fid": A, "New file name": "a.mp4"}, 0.0, None, 2.0)
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rawedit._ban_guard({"fid": W, "New file name": "doormat.mp4"}, 30.0, 31.0)
                    rawedit._ban_guard({"fid": G, "New file name": "ok.mp4"}, 0.0, 5.0)
                self.assertIn("WARN T06", buf.getvalue())
                self.assertEqual(buf.getvalue().count("WARN"), 1)
        finally:
            r.close()


if __name__ == "__main__":
    unittest.main()
