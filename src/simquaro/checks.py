"""Small ordered validation runner; no replay, reset, or simulator internals."""

from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field

from simquaro.console import render_bytes
from synqaro_protocol.client import ProtocolClient


class CheckFailure(Exception):
    pass


class CheckSkipped(Exception):
    pass


@dataclass(frozen=True)
class Check:
    name: str
    mutating: bool
    run: Callable[[ProtocolClient], Awaitable[None]]


@dataclass(frozen=True)
class CheckResult:
    name: str
    state: str
    reason: str
    duration: float


@dataclass
class CheckReport:
    results: list[CheckResult] = field(default_factory=list)
    identity: dict = field(default_factory=dict)
    evidence: list[dict] = field(default_factory=list)

    @property
    def exit_code(self):
        return int(not any(r.state == "passed" for r in self.results)
                   or any(r.state == "failed" or (r.state == "skipped" and r.reason != "Permission required: --allow-changes")
                          for r in self.results))

    def as_dict(self):
        return {**asdict(self), "exit_code": self.exit_code,
                "counts": {state: sum(r.state == state for r in self.results)
                           for state in ("passed", "failed", "skipped")}}


async def run_checks(client, checks, *, allow_changes=False, emit=None):
    """Own the supplied connection for one run, never the physical procedures."""
    report = CheckReport()
    if not allow_changes:
        client.read_only = True  # Also protect against a mislabeled check.
    def record(name, state, reason, began):
        reason = "".join(c if " " <= c <= "~" else "?" for c in str(reason)[:1024])
        result = CheckResult(name, state, reason, max(0, client.clock.monotonic() - began))
        report.results.append(result)
        if emit is not None: emit(result)
    if not checks:
        await client.close()
        return report
    began = client.clock.monotonic()
    blocked = False
    try:
        try:
            await client.connect()
        except Exception as exc:
            record("connection", "failed", exc, began)
            for check in checks:
                record(check.name, "skipped", "Connection/bootstrap unavailable", client.clock.monotonic())
            return report
        descriptor = client.descriptor.fields
        report.identity = {key: descriptor.get(key) for key in
                           ("hardware_id", "hardware_model", "firmware_version", "firmware_build")}
        report.identity.update(host=client.host, port=client.port,
                               initial_boot_id=client.general.fields.get("boot_id"))
        for check in checks:
            began = client.clock.monotonic()
            if check.mutating and not allow_changes:
                record(check.name, "skipped", "Permission required: --allow-changes", began)
            elif check.mutating and blocked:
                record(check.name, "skipped", "A previous check failed or was incomplete", began)
            else:
                try:
                    await check.run(client)
                except CheckSkipped as exc:
                    blocked = True
                    record(check.name, "skipped", exc, began)
                except Exception as exc:
                    blocked = True
                    uncertain = " (outcome uncertain)" if getattr(exc, "uncertain", False) else ""
                    record(check.name, "failed", str(exc) + uncertain, began)
                else:
                    record(check.name, "passed", "", began)
        report.identity["final_boot_id"] = client.general.fields.get("boot_id")
        return report
    finally:
        report.evidence = [{"kind": e.kind, "id": e.request_id, "message": e.message,
                            "observed_at": e.received_at, "data": render_bytes(e.wire)}
                           for e in list(client.evidence)[-32:]]
        await client.close()
