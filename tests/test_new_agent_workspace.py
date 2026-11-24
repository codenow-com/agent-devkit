"""Tests of the workspace choice of cn-new-agent: `cn-setup --workspace terminal|vscode` (CN_WORKSPACE in
~/.codenow/config), the VS Code shortcut of bin/cn-new-agent and the text of skills/codenow-new-agent/SKILL.md.

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
SWITCH = ("Continue in VS Code: in the window that opened, open the chat (Claude Code extension, or Copilot Chat in "
          "Interactive mode) and type /codenow-new-agent (Copilot Chat: ask it to use the codenow-new-agent skill). "
          "Nothing else runs in this terminal.")
INSTALL_CODE = "Shell Command: Install 'code' command in PATH"
FAKE = """#!/bin/bash
echo "$(basename "$0") $* | $PWD | here=${CN_NEW_AGENT_HERE:-}" >> "$FAKE_LOG"
"""


def flat(text):
    return " ".join(text.split())


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


class NewAgentShortcutTest(unittest.TestCase):
    """bin/cn-new-agent with fake `code`, claude, codex and copilot that only record their call."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()).resolve()
        self.home = self.tmp / "home"
        self.bin = self.tmp / "bin"
        self.home.mkdir()
        self.bin.mkdir()
        self.log = self.tmp / "calls.log"
        for name in ("code", "claude", "codex", "copilot"):
            (self.bin / name).write_text(FAKE)
            (self.bin / name).chmod(0o755)
        (self.home / ".codenow").mkdir()
        self.env = {"HOME": str(self.home), "PATH": f"{self.bin}:/usr/bin:/bin", "FAKE_LOG": str(self.log)}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def workspace(self, value):
        (self.home / ".codenow" / "config").write_text(f"CN_WORKSPACE={value}\n")

    def run_new_agent(self, *args, **env):
        return subprocess.run(["/bin/bash", str(ROOT / "bin" / "cn-new-agent"), *args], cwd=self.home,
                              env={**self.env, **env}, capture_output=True, text=True, timeout=30)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_vscode_opens_this_folder_and_starts_no_assistant(self):
        self.workspace("vscode")
        out = self.run_new_agent()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.calls(), [f"code . | {self.home} | here="])
        self.assertEqual(out.stdout.splitlines()[-1], SWITCH)

    def test_vscode_with_an_assistant_named_still_opens_vs_code(self):
        self.workspace("vscode")
        out = self.run_new_agent("--with", "codex")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual([c.split()[0] for c in self.calls()], ["code"])

    def test_here_starts_the_assistant_in_this_terminal(self):
        self.workspace("vscode")
        out = self.run_new_agent("--here")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.calls(), [f"claude /codenow-new-agent --here | {self.home} | here=1"])
        out = self.run_new_agent("--here", "--with", "copilot")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(self.calls()[-1].startswith("copilot -i Use the codenow-new-agent skill"), self.calls())
        self.assertIn("Work in this terminal (--here)", self.calls()[-1])
        self.assertTrue(self.calls()[-1].endswith("here=1"))

    def test_no_code_command_prints_the_install_hint(self):
        self.workspace("vscode")
        (self.bin / "code").unlink()
        out = self.run_new_agent()
        self.assertEqual(out.returncode, 1)
        self.assertIn(INSTALL_CODE, out.stderr)
        self.assertIn("--here", out.stderr)
        self.assertEqual(self.calls(), [])

    def test_terminal_or_unset_starts_the_assistant_and_never_code(self):
        for value in ("terminal", None):
            with self.subTest(workspace=value):
                if value:
                    self.workspace(value)
                self.log.unlink(missing_ok=True)
                out = self.run_new_agent()
                self.assertEqual(out.returncode, 0, out.stderr)
                self.assertEqual(self.calls(), [f"claude /codenow-new-agent | {self.home} | here="])

    def test_inside_vs_code_the_flow_stays_there(self):
        self.workspace("vscode")
        for env in ({"TERM_PROGRAM": "vscode"}, {"VSCODE_PID": "123"}, {"VSCODE_IPC_HOOK_CLI": "/tmp/x.sock"}):
            with self.subTest(env=env):
                self.log.unlink(missing_ok=True)
                out = self.run_new_agent(**env)
                self.assertEqual(out.returncode, 0, out.stderr)
                self.assertEqual([c.split()[0] for c in self.calls()], ["claude"])


class SkillTextTest(unittest.TestCase):
    def section(self, start, end):
        return SKILL[SKILL.index(start):SKILL.index(end) if end else len(SKILL)]

    def test_the_workspace_is_settled_first_and_stored(self):
        self.assertIn(QUESTION, SKILL)
        where = SKILL.index("## Where the user works")
        self.assertLess(where, SKILL.index("## 0."))
        self.assertLess(SKILL.index(QUESTION), SKILL.index("## 0."))
        self.assertIn("CN_WORKSPACE", SKILL)
        self.assertIn("cn-setup --workspace terminal", SKILL)
        self.assertIn("cn-setup --workspace vscode", SKILL)
        self.assertIn("CN_NEW_AGENT_HERE=1", SKILL)

    def test_vscode_in_a_terminal_assistant_switches_at_once(self):
        where = self.section("## Where the user works", "## 0.")
        self.assertIn("switch now", where)
        self.assertIn("Do not do step 0\n  and do not ask any question about the agent here", where)
        self.assertIn("run `code .`", where)
        self.assertIn("as the last action of this session", where)
        self.assertIn(SWITCH, flat(where))
        self.assertIn("`command -v code`", where)
        self.assertIn(INSTALL_CODE, where)
        # no creation question before the switch: steps 1 to 4 all come after it
        for step in ("## 0.", "## 1.", "## 2.", "## 3.", "## 4."):
            self.assertLess(SKILL.index("switch now"), SKILL.index(step), step)
        self.assertNotIn("agents_create", where)
        self.assertNotIn("agent_swarms_list", where)

    def test_inside_vs_code_is_detected_and_not_asked(self):
        where = self.section("## Where the user works", "## 0.")
        for marker in ("`TERM_PROGRAM=vscode`", "`VSCODE_PID`", "`VSCODE_IPC_HOOK_CLI`", "VS Code Copilot Chat"):
            self.assertIn(marker, where)
        self.assertIn("Inside VS Code, do not ask where the user works", where)
        self.assertIn("When `CN_WORKSPACE` in `~/.codenow/config` is not set, save\n   `vscode`", where)
        self.assertLess(where.index("Inside VS Code?"), where.index(QUESTION))

    def test_no_code_call_before_step_5(self):
        before = SKILL[:SKILL.index("## 5.")]
        self.assertIsNone(re.search(r"`code <", before), "a `code <...>` call before step 5")
        self.assertIn("never run `code`", before)

    def test_the_old_terminal_vscode_branch_is_gone(self):
        self.assertNotIn("### Workspace `vscode`", SKILL)
        self.assertNotIn("type /start. Nothing else runs in", SKILL)

    def test_the_branches_of_step_5(self):
        copilot = self.section("### Inside VS Code, Copilot Chat", "### Inside VS Code, Claude Code")
        claude = self.section("### Inside VS Code, Claude Code", "### Workspace `terminal`")
        terminal = self.section("### Workspace `terminal`", None)
        self.assertIn("Run `code <agent name>` as the last action", copilot)
        self.assertIn("new window", copilot)
        self.assertIn("type /start", copilot)
        self.assertIn("in this same session", claude)
        self.assertIn("working folder for every command", claude)
        self.assertIn("do not open a new window", claude)
        self.assertIn("Only when the user asks", claude)
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
