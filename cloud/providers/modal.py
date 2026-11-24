"""WRITTEN NOT RUN: transport to an owner-deployed, verified Linux worker.

No modal import, App construction, authentication, image build, upload or deploy
at import time. This does NOT claim the macOS Seatbelt runner works on Linux.
Deployment is intentionally unavailable until the missing Linux boundary exists.
"""
import importlib
from typing import Any

from .base import CloudAuthorization, ProviderRefused


class ModalProvider:
    def __init__(self, app_name: str = '', function_name: str = ''):
        self.app_name, self.function_name = app_name, function_name

    def run(self, request: dict[str, Any], authorization: CloudAuthorization | None = None) -> dict[str, Any]:
        (authorization or CloudAuthorization()).require()
        if not self.app_name or not self.function_name:
            raise ProviderRefused('Owner must name an existing verified worker deployment')
        try:
            modal = importlib.import_module('modal')
        except ImportError as exc:
            raise ProviderRefused('Modal SDK is unavailable; no login or automatic installation attempted') from exc
        # Caller must reserve spend durably before entry; no retry/resubmission here.
        # The remote service must enforce a matching hard timeout and input gates.
        report = modal.Function.from_name(self.app_name, self.function_name).remote(request)
        if not isinstance(report, dict) or report.get('status') not in {'done', 'failed'}:
            raise RuntimeError('Invalid Modal worker report')
        # A transport success is not QC, approval, or permission to upload.
        report = dict(report)
        report['deliverable'] = False
        return report
