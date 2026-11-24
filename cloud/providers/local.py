"""Launch the existing hermetic runner in a credential-free local subprocess."""
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from .base import CloudAuthorization


class LocalSubprocessProvider:
    def run(self, request: dict[str, Any], authorization: CloudAuthorization | None = None) -> dict[str, Any]:
        cloud = Path(__file__).resolve().parents[1]
        env = {'PATH': '/usr/bin:/bin', 'PYTHONPATH': str(cloud), 'PYTHONDONTWRITEBYTECODE': '1',
               'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'FFMPEG_NO_GATE': '1',
               'CLAUDE_BACKEND': 'skip', 'MOMENTS_BACKEND': 'skip', 'LANG': 'en_US.UTF-8'}
        # HOME is needed by Python/platform libraries, but no SDK is imported here.
        env['HOME'] = os.path.expanduser('~')
        timeout = request.get('manifest', {}).get('timeout', 600)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 3600:
            raise ValueError('Stage timeout must be between 0 and 3600 seconds')
        proc = subprocess.run([sys.executable, '-m', 'providers.worker'], input=json.dumps(request),
                              env=env, cwd=cloud, capture_output=True, text=True, timeout=timeout + 30)
        if proc.returncode:
            # Do not echo untrusted tool output or credentials to the calling UI.
            raise RuntimeError('Local stage worker failed; no source writeback performed')
        report = json.loads(proc.stdout)
        if not isinstance(report, dict) or report.get('status') not in {'done', 'failed'}:
            raise RuntimeError('Invalid local worker report')
        return report
