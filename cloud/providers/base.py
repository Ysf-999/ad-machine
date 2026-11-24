"""Small synchronous transport boundary; durable scheduling lives above it."""
from dataclasses import dataclass
import math
from typing import Any, Protocol


class ProviderRefused(RuntimeError):
    pass


@dataclass(frozen=True)
class CloudAuthorization:
    go: bool = False
    budget_cap: float | None = None
    reserved_cost: float | None = None
    credentials_ready: bool = False
    linux_worker_verified: bool = False

    def require(self) -> None:
        if not self.go:
            raise ProviderRefused('Cloud compute disabled: explicit go required')
        if not self.credentials_ready:
            raise ProviderRefused('Owner-managed cloud credentials unavailable')
        if not self.linux_worker_verified:
            raise ProviderRefused('Linux image, mounts, runner and gates have not been verified')
        values = (self.budget_cap, self.reserved_cost)
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
            raise ProviderRefused('Finite budget cap and measured/reserved cost required; unknown cost refuses compute')
        if self.budget_cap <= 0 or self.reserved_cost <= 0 or self.reserved_cost > self.budget_cap:
            raise ProviderRefused('Positive reservation must fit the remaining run budget')


class Provider(Protocol):
    def run(self, request: dict[str, Any], authorization: CloudAuthorization | None = None) -> dict[str, Any]:
        """Execute a declared safe stage; return the existing runner report."""
        ...
