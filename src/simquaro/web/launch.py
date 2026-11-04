"""Foreground loopback launch, imported lazily by the dependency-free CLI."""

import asyncio
import socket
import webbrowser


def launch(store, *, port, no_browser, runtime_root, emit):
    try:
        import uvicorn
        from simquaro.web.app import create_app
    except ImportError:
        emit("gui.error", error={"code": "WEB_EXTRA_REQUIRED",
             "message": "The GUI needs the optional web packages in this Python environment.",
             "actions": ["From the repository, inside its virtual environment: python -m pip install -e '.[web]'",
                         "Then run: simquaro gui"]})
        return 1
    url = f"http://127.0.0.1:{port}"
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", port))
        listener.listen(128)
        listener.setblocking(False)
    except OSError:
        listener.close()
        emit("gui.error", error={"code": "GUI_PORT_UNAVAILABLE", "message": f"Cannot listen on {url}; no existing process was stopped.",
             "actions": [["simquaro", "gui", "--port", str(8766 if port != 8766 else 8767), "--no-browser"]]})
        return 1

    async def serve():
        app = create_app(store, runtime_root=runtime_root, origin=url)
        config = uvicorn.Config(app, host="127.0.0.1", port=port, workers=1,
                                proxy_headers=False, access_log=False, log_level="warning")
        server = uvicorn.Server(config)
        task = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            while not server.started and not task.done(): await asyncio.sleep(.01)
            if server.started:
                emit("gui.ready", result={"url": url, "message": "Keep this terminal open. Ctrl+C stops the server and its owned simulators."})
                if not no_browser:
                    try:
                        opened = await asyncio.to_thread(webbrowser.open, url)
                    except Exception:
                        opened = False
                    if not opened: emit("gui.browser", result={"url": url, "message": "Open this URL manually in your browser."})
            await task
            return 0 if server.started else 1
        finally:
            server.should_exit = True
            if not task.done():
                await task
    try:
        return asyncio.run(serve())
    finally:
        listener.close()
