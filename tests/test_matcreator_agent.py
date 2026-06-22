"""Import-completeness tests for the MatCreator agent.

Each test runs the target import in an isolated subprocess so that:
  - Module-level state (WORKSPACE_ROOT, ALL_SKILLS) is resolved fresh per run.
  - MCP TCP probes in mcp_tools.py don't affect the test-runner process.

A minimal workspace (just a ``skills/`` subdirectory) is created in a temp
directory and pointed to via the MATCLAW_WORKSPACE env var so that
``skill.py``'s module-level ``load_skills()`` call doesn't crash.
"""

import os
import sys
import tempfile
import unittest
import subprocess
from pathlib import Path

# mcp_tools.py probes 6 servers with a 2-second TCP timeout each.
_IMPORT_TIMEOUT = 60  # seconds
# Project root (one level above tests/)
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)


def _import_check(module_expr: str, workspace: str) -> subprocess.CompletedProcess:
    """Run ``import <module_expr>`` in a subprocess with a temp workspace.

    PYTHONPATH is extended with the project root so that ``agents.MatCreator``
    is discoverable without requiring an editable install.
    """
    existing = os.environ.get("PYTHONPATH", "")
    pythonpath = f"{_PROJECT_ROOT}{os.pathsep}{existing}" if existing else _PROJECT_ROOT
    env = {**os.environ, "MATCLAW_WORKSPACE": workspace, "PYTHONPATH": pythonpath}
    return subprocess.run(
        [sys.executable, "-c", f"import {module_expr}"],
        env=env,
        capture_output=True,
        text=True,
        timeout=_IMPORT_TIMEOUT,
    )


class TestMatCreatorImports(unittest.TestCase):
    """Verify that every MatCreator sub-module imports without errors."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        # skill.py iterates workspace_skills_dir() at module load time.
        os.makedirs(os.path.join(cls._tmp.name, "skills"), exist_ok=True)
        cls.workspace = cls._tmp.name

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _assertImportable(self, module_expr: str):
        result = _import_check(module_expr, self.workspace)
        self.assertEqual(
            result.returncode, 0,
            msg=f"Import of '{module_expr}' failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}",
        )

    # ── Individual sub-modules ────────────────────────────────────────────────

    def test_constants(self):
        self._assertImportable("agents.MatCreator.constants")

    def test_workspace(self):
        self._assertImportable("agents.MatCreator.workspace")

    def test_guide(self):
        self._assertImportable("agents.MatCreator.guide")

    def test_skill(self):
        self._assertImportable("agents.MatCreator.skill")

    def test_orchestrator(self):
        self._assertImportable("agents.MatCreator.agents.orchestrator.agent")

    def test_thinking_agent(self):
        self._assertImportable("agents.MatCreator.agents.thinking_agent")

    def test_execution_agent(self):
        self._assertImportable("agents.MatCreator.agents.execution_agent")

    def test_tester_agent(self):
        self._assertImportable("agents.MatCreator.agents.tester_agent")

    # ── Top-level package ─────────────────────────────────────────────────────

    def test_top_level_exports_app(self):
        """agents.MatCreator must be importable and export `app`."""
        result = _import_check(
            "agents.MatCreator; from agents.MatCreator import app",
            self.workspace,
        )
        self.assertEqual(
            result.returncode, 0,
            msg=f"Top-level import / app export failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
