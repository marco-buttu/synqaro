"""Bounded once-only jobs and ownership of server-created child processes."""

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import secrets

from simquaro.web import ServiceError


class JobManager:
    def __init__(self):
        self._records, self._tasks = {}, {}
        self._monitors = set()
        self._closed = False

    def busy(self, target):
        return any(r["target"] == target and r["state"] == "running" for r in self._records.values())

    def start(self, kind, target, coroutine):
        code = "SERVER_CLOSING" if self._closed else "JOB_LIMIT" if len(self._tasks) >= 16 else "TARGET_BUSY" if self.busy(target) else None
        if code:
            coroutine.close()
            raise ServiceError(code, "Wait for the active job to finish; do not repeat an uncertain action")
        jid = secrets.token_urlsafe(24)
        self._records[jid] = {"id": jid, "kind": kind, "target": target, "state": "running",
                              "started_at": datetime.now(timezone.utc).isoformat(), "progress": []}
        self._tasks[jid] = asyncio.create_task(self._run(jid, coroutine))
        return jid

    def progress(self, jid, event):
        record = self._records[jid]
        data = deepcopy(event)
        if len(json.dumps(data)) > 16384: data = {"message": "Progress event exceeded display limit"}
        record["progress"].append(data)
        del record["progress"][:-32]

    async def _run(self, jid, coroutine):
        record = self._records[jid]
        try:
            result = await coroutine
            if len(json.dumps({**record, "result": result}, allow_nan=False).encode()) > 1048000:
                raise ServiceError("REPORT_LIMIT", "Result exceeded 1 MiB; inspect the target before retrying")
            record.update(state="failed" if isinstance(result, dict) and
                          (result.get("ok") is False or result.get("exit_code", 0) != 0) else "succeeded", result=result)
        except asyncio.CancelledError:
            coroutine.close()
            record.update(state="interrupted", error={"code": "JOB_INTERRUPTED", "uncertain": True,
                          "message": "Server stopped observing; hardware may still be running. Query its state"})
        except Exception as exc:
            record.update(state="failed", error={"code": getattr(exc, "code", "JOB_FAILED"),
                          "message": str(exc)[:1024], "uncertain": getattr(exc, "uncertain", False)})
        finally:
            record["finished_at"] = datetime.now(timezone.utc).isoformat()
            self._tasks.pop(jid, None)
            completed = [key for key, r in self._records.items() if r["state"] != "running"]
            for key in completed[:-64]: self._records.pop(key, None)

    def get(self, jid):
        if jid not in self._records: raise ServiceError("UNKNOWN_JOB", "Report expired; inspect recent jobs or query hardware state")
        return deepcopy(self._records[jid])

    def list(self, target):
        return [self.get(jid) for jid, r in self._records.items() if r["target"] == target]

    def own(self, runtime, started):
        """Register synchronously, before callers do any more cancellable work."""
        if started is None or started.child is None: return
        monitor = asyncio.create_task(runtime.supervise([started]))
        self._monitors.add(monitor)
        def finished(task):
            self._monitors.discard(task)
            if not task.cancelled(): task.exception()  # Retrieve any supervision failure.
        monitor.add_done_callback(finished)

    async def close(self):
        self._closed = True
        tasks = list(self._tasks.values())
        # Let newly registered wrappers establish their cancellation/finally path.
        await asyncio.sleep(0)
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        monitors = list(self._monitors)
        for monitor in monitors: monitor.cancel()
        await asyncio.gather(*monitors, return_exceptions=True)
