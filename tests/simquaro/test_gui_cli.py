"""The GUI command is discoverable without importing optional web packages."""

from contextlib import redirect_stdout, redirect_stderr
import io
import unittest

from simquaro.cli import main


class GuiCliTests(unittest.TestCase):
    def test_gui_help_and_invalid_port_work_without_web_imports(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            result = main(["gui", "--help"])
        self.assertEqual(result, 0, err.getvalue())
        self.assertIn("--no-browser", out.getvalue())
        self.assertIn("--port", out.getvalue())
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(["gui", "--port", "0"]), 2)
