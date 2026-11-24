# syntax=docker/dockerfile:1.7
# WRITTEN NOT RUN. Offline template, NOT a verified Linux reproduction.
# Build context: the repo root. Prototype template for the queue worker; the live controller image is built in controller/app.py. Supply the separate named context `runtime`.
# BASE_IMAGE must be an owner-reviewed Linux/amd64 Python 3.12 image pinned by
# digest, already containing fontconfig and Chromium system libraries.
# The Mac freeze files in cloud/locks are audit evidence, NOT Linux lockfiles.
# No build/login/download/deployment was performed for this template.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ARG BASE_IMAGE
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    FFMPEG_NO_GATE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 PIP_NO_INDEX=1 \
    CLAUDE_BACKEND=skip MOMENTS_BACKEND=skip \
    PLAYWRIGHT_BROWSERS_PATH=/opt/runtime/playwright-browsers \
    PATH=/opt/venv/bin:/opt/runtime/ffmpeg:/opt/runtime/node/bin:/usr/local/bin:/usr/bin:/bin \
    PYTHONPATH=/opt/pipeline/cloud
RUN python -c "import sys; assert sys.version_info[:2] == (3,12); assert '@sha256:' in '${BASE_IMAGE}', 'Pin base image digest'"
# Owner must prepare all these artifacts on Linux. Missing artifacts fail build.
# SHA256SUMS must cover every artifact; do not place credentials in this context.
COPY --from=runtime / /opt/runtime/
RUN cd /opt/runtime && sha256sum -c SHA256SUMS
RUN python -m venv /opt/venv && \
    /opt/venv/bin/python -m pip install --no-index --require-hashes \
      --find-links=/opt/runtime/wheelhouse -r /opt/runtime/python-linux.lock
# Proposed new Linux pins, not claimed resolved/tested against this pipeline.
# All transitive dependencies must be in python-linux.lock with hashes.
RUN python -c "from importlib.metadata import version; assert version('faster-whisper') == '1.2.1'; assert version('playwright') == '1.56.0'"
RUN /opt/runtime/ffmpeg/ffmpeg -version | head -1 | grep -E '^ffmpeg version 7\.0([ -]|$)' && \
    /opt/runtime/ffmpeg/ffprobe -version | head -1 | grep -E '^ffprobe version 7\.0([ -]|$)'
# hyperframes/ must contain Linux-installed node_modules from the project's
# package-lock.json (HyperFrames 0.9.6), not the Mac node_modules tree.
RUN test -x /opt/runtime/node/bin/node && \
    /opt/runtime/node/bin/node -e "const p=require('/opt/runtime/hyperframes/node_modules/hyperframes/package.json'); if(p.version!=='0.9.6')process.exit(1)" && \
    test -d /opt/runtime/playwright-browsers
COPY tools/*.py /opt/pipeline/tools/
COPY cloud/transcription.py /opt/pipeline/cloud/transcription.py
COPY cloud/llm.py /opt/pipeline/cloud/llm.py
COPY cloud/providers/*.py /opt/pipeline/cloud/providers/
COPY cloud/runner/*.py /opt/pipeline/cloud/runner/
COPY library/fonts/ /usr/local/share/fonts/admachine/
# Additional exact caption/card fonts (including Arial Black) are explicit
# owner-supplied artifacts. Silent font substitution does not establish parity.
RUN cp -R /opt/runtime/fonts/. /usr/local/share/fonts/ && fc-cache -f && \
    fc-list : family | grep -F 'Arial Black' && \
    python -c "from playwright.sync_api import sync_playwright; from pathlib import Path; p=sync_playwright().start(); assert Path(p.chromium.executable_path).is_file(); p.stop()"
WORKDIR /opt/pipeline
# No secrets/models/footage copied. Runtime staging and Linux isolation are still
# missing: current runner requires macOS Seatbelt and MUST refuse on Linux.
# This entry point therefore fails closed for stage runs until that is resolved.
ENTRYPOINT ["/opt/venv/bin/python", "-m", "providers.worker"]
