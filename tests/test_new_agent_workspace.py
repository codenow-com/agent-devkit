"""Tests of the workspace choice of cn-new-agent: `cn-setup --workspace terminal|vscode` (CN_WORKSPACE in
~/.codenow/config), the VS Code shortcut of bin/cn-new-agent and the text of skills/codenow-new-agent/SKILL.md.

    python3 -m unittest discover -s tests
"""
import json
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
ALLOW = ("VS Code may ask once to allow automatic tasks (Allow and Run). If nothing starts, run the task "
         "'CodeNOW: new agent' (Terminal \u2192 Run Task) or type /codenow-new-agent in the chat.")
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

    def tasks(self):
        return json.loads((self.home / ".vscode" / "tasks.json").read_text())["tasks"]

    def run_task(self, command):
        run = subprocess.run(["/bin/bash", "-c", command], cwd=self.home, env=self.env, capture_output=True,
                             text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_vscode_opens_this_folder_and_starts_no_assistant_here(self):
        self.workspace("vscode")
        out = self.run_new_agent()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.calls(), [f"code . | {self.home} | here="])
        self.assertEqual(out.stdout.splitlines()[-1], ALLOW)
        self.assertNotIn(SWITCH, out.stdout)

    def test_vscode_writes_a_one_shot_folder_open_task(self):
        self.workspace("vscode")
        out = self.run_new_agent()
        self.assertEqual(out.returncode, 0, out.stderr)
        (task,) = self.tasks()
        self.assertEqual(task["label"], "CodeNOW: new agent")
        self.assertEqual(task["detail"], "cn-devkit: one-shot")
        self.assertEqual(task["type"], "shell")
        self.assertEqual(task["runOptions"], {"runOn": "folderOpen"})
        self.assertEqual(task["presentation"], {"reveal": "always", "focus": True, "panel": "dedicated"})
        helper = str(ROOT / "lib" / "vscode_task.py")
        self.assertEqual(task["command"], f"python3 -I {helper} remove {self.home} --created-file --created-dir; "
                                          "exec claude /codenow-new-agent")

    def test_the_task_command_removes_itself_and_starts_the_assistant(self):
        self.workspace("vscode")
        self.assertEqual(self.run_new_agent().returncode, 0)
        self.run_task(self.tasks()[0]["command"])
        self.assertEqual(self.calls()[-1], f"claude /codenow-new-agent | {self.home} | here=")
        self.assertFalse((self.home / ".vscode").exists())

    def test_vscode_with_codex_or_copilot_puts_their_cli_in_the_task(self):
        self.workspace("vscode")
        for name, start in (("codex", "exec codex 'Use the codenow-new-agent skill"),
                            ("copilot", "exec copilot -i 'Use the codenow-new-agent skill")):
            with self.subTest(assistant=name):
                out = self.run_new_agent("--with", name)
                self.assertEqual(out.returncode, 0, out.stderr)
                self.assertEqual([c.split()[0] for c in self.calls()][-1], "code")
                (task,) = self.tasks()
                self.assertIn(start, task["command"])
                self.assertIn(f"clone it into {self.home}.", task["command"])
                self.assertEqual(out.stdout.splitlines()[-1], ALLOW)

    def test_vscode_with_copilot_not_installed_falls_back_to_the_chat(self):
        self.workspace("vscode")
        (self.bin / "copilot").unlink()
        out = self.run_new_agent("--with", "copilot")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.splitlines()[-1], SWITCH)
        self.assertFalse((self.home / ".vscode").exists())
        self.assertEqual([c.split()[0] for c in self.calls()], ["code"])

    def test_autostart_off_only_prints_the_instruction(self):
        self.workspace("vscode")
        out = self.run_new_agent(CN_VSCODE_AUTOSTART="off")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.splitlines()[-1], SWITCH)
        self.assertNotIn(ALLOW, out.stdout)
        self.assertFalse((self.home / ".vscode").exists())
        self.assertEqual(self.calls(), [f"code . | {self.home} | here="])

    def test_an_existing_tasks_json_is_merged(self):
        self.workspace("vscode")
        (self.home / ".vscode").mkdir()
        mine = {"label": "build", "type": "shell", "command": "make"}
        (self.home / ".vscode" / "tasks.json").write_text(json.dumps({"version": "2.0.0", "tasks": [mine]}))
        out = self.run_new_agent()
        self.assertEqual(out.returncode, 0, out.stderr)
        tasks = self.tasks()
        self.assertEqual(tasks[0], mine)
        self.assertEqual([t["label"] for t in tasks], ["build", "CodeNOW: new agent"])
        self.assertNotIn("--created", tasks[1]["command"])
        # the task takes out only itself and leaves the file and the other task
        self.run_task(tasks[1]["command"])
        self.assertEqual(self.tasks(), [mine])

    def test_a_tasks_json_with_comments_is_not_touched(self):
        self.workspace("vscode")
        (self.home / ".vscode").mkdir()
        jsonc = '{\n  // my tasks\n  "version": "2.0.0",\n  "tasks": [],\n}\n'
        (self.home / ".vscode" / "tasks.json").write_text(jsonc)
        out = self.run_new_agent()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual((self.home / ".vscode" / "tasks.json").read_text(), jsonc)
        self.assertIn("left unchanged", out.stdout)
        self.assertEqual(out.stdout.splitlines()[-1], SWITCH)
        self.assertEqual([c.split()[0] for c in self.calls()], ["code"])

    def test_a_second_run_replaces_the_task(self):
        self.workspace("vscode")
        self.assertEqual(self.run_new_agent().returncode, 0)
        self.assertEqual(self.run_new_agent("--with", "codex").returncode, 0)
        (task,) = self.tasks()
        self.assertIn("exec codex", task["command"])
        # what the first run created is still cleaned up
        self.assertIn("--created-file --created-dir", task["command"])
        self.run_task(task["command"])
        self.assertFalse((self.home / ".vscode").exists())

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


class VscodeTaskHelperTest(unittest.TestCase):
    """lib/vscode_task.py remove: only its own entry, and only the files it created."""

    def setUp(self):
        self.folder = pathlib.Path(tempfile.mkdtemp()).resolve()
        self.path = self.folder / ".vscode" / "tasks.json"

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def helper(self, *args):
        out = subprocess.run(["python3", "-I", str(ROOT / "lib" / "vscode_task.py"), *args], capture_output=True,
                             text=True, timeout=30)
        self.assertIn(out.returncode, (0, 3), out.stderr)
        return out.returncode

    def ours(self):
        return {"label": "CodeNOW: new agent", "detail": "cn-devkit: one-shot", "command": "x"}

    def test_remove_keeps_a_file_it_did_not_create(self):
        self.path.parent.mkdir()
        self.path.write_text(json.dumps({"version": "2.0.0", "tasks": [self.ours()]}))
        self.helper("remove", str(self.folder))
        self.assertEqual(json.loads(self.path.read_text()), {"version": "2.0.0", "tasks": []})

    def test_remove_deletes_only_what_it_created(self):
        self.path.parent.mkdir()
        self.path.write_text(json.dumps({"version": "2.0.0", "tasks": [self.ours()]}))
        (self.folder / ".vscode" / "settings.json").write_text("{}")
        self.helper("remove", str(self.folder), "--created-file", "--created-dir")
        self.assertFalse(self.path.exists())
        self.assertTrue((self.folder / ".vscode" / "settings.json").exists())
        (self.folder / ".vscode" / "settings.json").unlink()
        self.path.write_text(json.dumps({"version": "2.0.0", "tasks": [self.ours()]}))
        self.helper("remove", str(self.folder), "--created-file", "--created-dir")
        self.assertFalse((self.folder / ".vscode").exists())

    def test_remove_keeps_other_tasks_and_is_harmless_twice(self):
        other = {"label": "build", "command": "make"}
        self.path.parent.mkdir()
        self.path.write_text(json.dumps({"version": "2.0.0", "tasks": [other, self.ours()]}))
        self.helper("remove", str(self.folder), "--created-file", "--created-dir")
        self.assertEqual(json.loads(self.path.read_text())["tasks"], [other])
        self.helper("remove", str(self.folder), "--created-file", "--created-dir")
        self.assertEqual(json.loads(self.path.read_text())["tasks"], [other])

    def test_remove_without_a_file_does_nothing(self):
        self.assertEqual(self.helper("remove", str(self.folder)), 0)
        self.assertFalse(self.path.parent.exists())

    def test_add_twice_keeps_one_task(self):
        self.assertEqual(self.helper("add", str(self.folder), "claude", "/codenow-new-agent"), 0)
        self.assertEqual(self.helper("add", str(self.folder), "claude", "/codenow-new-agent"), 0)
        self.assertEqual(len(json.loads(self.path.read_text())["tasks"]), 1)

    def test_add_refuses_a_file_that_is_not_a_tasks_object(self):
        self.path.parent.mkdir()
        for text in ("[]", '{"tasks": {}}', "{,}"):
            self.path.write_text(text)
            self.assertEqual(self.helper("add", str(self.folder), "claude"), 3)
            self.assertEqual(self.path.read_text(), text)


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
