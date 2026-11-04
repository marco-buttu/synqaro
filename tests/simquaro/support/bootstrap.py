"""Worker substitution that owns inherited descriptors but never becomes ready."""

import os
from pathlib import Path
import signal
import subprocess
import sys


if os.environ.get("SIMQUARO_TEST_MODE") == "exit":
    Path(os.environ["SIMQUARO_TEST_BARRIER"]).write_text(str(os.getpid()))
    raise SystemExit(3)
elif os.environ.get("SIMQUARO_TEST_MODE") == "descendant":
    from simquaro import worker
    original = worker.serve
    async def with_descendant(*args):
        descendant = subprocess.Popen([sys.executable, "-c", "import signal; signal.pause()"],
                                      close_fds=False)
        Path(os.environ["SIMQUARO_TEST_BARRIER"]).write_text(str(descendant.pid))
        return await original(*args)
    worker.serve = with_descendant
    raise SystemExit(worker.main())
else:
    signal.signal(signal.SIGTERM, lambda *_: exit(0))
    Path(os.environ["SIMQUARO_TEST_BARRIER"]).write_text(str(os.getpid()))
    while True:
        signal.pause()
