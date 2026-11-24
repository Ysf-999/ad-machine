# Fonts

`cloud/fonts-manifest.json` records every bundled font in `library/fonts/` (size, SHA256, embedded family /
PostScript / license fields) and the system fonts some tools use. All bundled files (Caveat VF, Fraunces VF,
Montserrat Black/Bold/ExtraBold, Poppins Bold/Medium/SemiBold, TikTok Sans VF) carry an embedded SIL Open Font
License reference; keep the license and attribution with them.

Some tools default to system faces that are not bundled: Arial Black (rawedit, assemble_anim, burn_captions),
SF / Helvetica Neue / Arial (comment cards, review tiles, HyperFrames fallbacks). Their redistribution rights in a
cloud image are not established, so they are never copied into the image. In the cloud the worker writes a private
fontconfig that only sees `library/fonts/` (`worker/ad_job.py`), so a caption style that names a system face falls back
to whatever fontconfig picks. Pick a bundled face in your caption styles for identical Mac and cloud renders, or add a
font you are licensed to ship to `library/fonts/`.

`worker/fonts.py` (prototype runner) builds the same kind of private fontconfig for the offline stage runner; its tests
are in `tests/test_fonts.py`.
