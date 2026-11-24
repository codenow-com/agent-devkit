"""Tests of the workspace choice of cn-new-agent: `cn-setup --workspace terminal|vscode` (CN_WORKSPACE in
~/.codenow/config) and the text of skills/codenow-new-agent/SKILL.md.

    python3 -m unittest discover -s tests
"""
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL = (ROOT / "skills" / "codenow-new-agent" / "SKILL.md").read_text()
QUESTION = "Where do you want to work on the agent: in this terminal, or in VS Code?"
VSCODE_STOP = ("Continue in VS Code: open the chat\n(Claude Code extension or Copilot Chat in Interactive mode) in the "
               "new window and type /start. Nothing else runs in\nthis terminal.")


class WorkspaceSettingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.config = self.home / ".codenow" / "config"
        # no curl, git or assistants: --workspace must save and exit before any other step
        self.env = {"HOME": str(self.home), "PATH": "/usr/bin:/bin"}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cn(self, command, *args):
        return subprocess.run(["/bin/bash", str(ROOT / "bin" / command), *args], cwd=self.home, env=self.env,
                              capture_output=True, text=True, timeout=30)

    def test_workspace_is_saved_and_other_settings_stay(self):
        self.config.parent.mkdir()
        self.config.write_text("CODENOW_MCP_URL=https://mcp-server-t.example/mcp\nCN_WORKSPACE=vscode\n")
        out = self.run_cn("cn-setup", "--workspace", "terminal")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("CN_WORKSPACE=terminal saved", out.stdout)
        self.assertEqual(self.config.read_text(),
                         "CODENOW_MCP_URL=https://mcp-server-t.example/mcp\nCN_WORKSPACE=terminal\n")
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)
        out = self.run_cn("cn-setup", "--workspace=vscode")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("CN_WORKSPACE=vscode\n", self.config.read_text())

    def test_a_new_config_gets_the_workspace(self):
        out = self.run_cn("cn-setup", "--workspace", "vscode")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.config.read_text(), "CN_WORKSPACE=vscode\n")

    def test_a_wrong_or_missing_value_is_a_usage_error(self):
        for args in (["--workspace", "emacs"], ["--workspace"], ["--workspace="]):
            out = self.run_cn("cn-setup", *args)
            self.assertEqual(out.returncode, 2, args)
            self.assertIn("terminal or vscode", out.stderr)
        self.assertFalse(self.config.exists())

    def test_doctor_refuses_workspace(self):
        out = self.run_cn("cn-doctor", "--workspace", "terminal")
        self.assertEqual(out.returncode, 2)
        self.assertIn("cn-setup --workspace", out.stderr)
        self.assertFalse(self.config.exists())


class SkillTextTest(unittest.TestCase):
    def section(self, start, end):
        return SKILL[SKILL.index(start):SKILL.index(end) if end else len(SKILL)]

    def test_the_question_is_asked_once_before_step_1_and_stored(self):
        self.assertIn(QUESTION, SKILL)
        self.assertLess(SKILL.index("## 0."), SKILL.index(QUESTION))
        self.assertLess(SKILL.index(QUESTION), SKILL.index("## 1."))
        self.assertIn("CN_WORKSPACE", SKILL)
        self.assertIn("cn-setup --workspace terminal", SKILL)
        self.assertIn("cn-setup --workspace vscode", SKILL)

    def test_no_code_call_before_step_5(self):
        before = SKILL[:SKILL.index("## 5.")]
        self.assertIsNone(re.search(r"`code <", before), "a `code <...>` call before step 5")
        self.assertIn("never run `code`", before)

    def test_the_two_branches_of_step_5(self):
        vscode = self.section("### Workspace `vscode`", "### Workspace `terminal`")
        terminal = self.section("### Workspace `terminal`", None)
        self.assertIn("Run `code <agent name>` as the last action", vscode)
        self.assertIn(VSCODE_STOP, vscode)
        self.assertIn("Never run `code`", terminal)
        self.assertNotIn("Run `code", terminal)
        self.assertIn("print only the hint\n`code <agent name>`", terminal)
        self.assertIn("SKILL.md", terminal)                     # the start skill goes on in this session

    def test_step_5_tells_start_when_the_developer_identity_is_ready(self):
        terminal = self.section("### Workspace `terminal`", None)
        self.assertIn("`CODENOW_AGW_CLIENT_ID` and `CODENOW_WORKFORCE_URL`", terminal)
        self.assertIn("`cn-sandbox up --as-me`", terminal)
        self.assertLess(terminal.index("CODENOW_WORKFORCE_URL"), terminal.index("start/SKILL.md"))


if __name__ == "__main__":
    unittest.main()
