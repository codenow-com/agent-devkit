"""Tests of --help, -h and the usage errors of every cn-* command (lib/help.sh).

    python3 -m unittest discover -s tests
"""
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
COMMANDS = sorted(p.name for p in (ROOT / "bin").glob("cn-*"))
# cn-sandbox passes every argument but -h/--help and its own token forms to the agent's sandbox.sh.
PASS_THROUGH = {"cn-sandbox"}
# Every tool that could reach the network, a container or an assistant: a fake that records the call and fails.
FAKES = ["curl", "git", "docker", "python3", "kubectl", "pinniped", "oidc-token", "oidc-agent", "claude", "codex",
         "copilot", "openspec", "npm", "pip", "brew"]
FAKE = """#!/bin/bash
echo "$(basename "$0") $*" >> "$FAKE_LOG"
exit 99
"""


class HelpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.home = self.tmp / "home"
        self.bin = self.tmp / "bin"
        self.home.mkdir()
        self.bin.mkdir()
        self.log = self.tmp / "calls.log"
        for name in FAKES:
            (self.bin / name).write_text(FAKE)
            (self.bin / name).chmod(0o755)
        self.env = {"HOME": str(self.home), "PATH": f"{self.bin}:/usr/bin:/bin", "FAKE_LOG": str(self.log)}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cn(self, command, *args):
        return subprocess.run(["/bin/bash", str(ROOT / "bin" / command), *args], cwd=self.home, env=self.env,
                              capture_output=True, text=True, timeout=30)

    def assert_no_effect(self, command):
        self.assertEqual(list(self.home.rglob("*")), [], f"{command} wrote into HOME")
        self.assertFalse(self.log.exists(), f"{command} ran: {self.log.read_text() if self.log.exists() else ''}")

    def test_every_command_is_covered(self):
        self.assertEqual(COMMANDS, ["cn-call", "cn-doctor", "cn-new-agent", "cn-sandbox", "cn-setup", "cn-update",
                                    "cn-wait"])

    def test_help_prints_the_manual_and_does_nothing_else(self):
        for command in COMMANDS:
            with self.subTest(command=command):
                result = self.run_cn(command, "--help")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                for section in ("NAME", "SYNOPSIS", "DESCRIPTION", "OPTIONS", "EXIT STATUS", "EXAMPLES", "SEE ALSO"):
                    self.assertIn(f"\n{section}\n", "\n" + result.stdout, section)
                self.assertIn(f"    {command} - ", result.stdout)
                self.assertLessEqual(max(len(line) for line in result.stdout.splitlines()), 80)
                self.assert_no_effect(command)

    def test_short_h_equals_help(self):
        for command in COMMANDS:
            with self.subTest(command=command):
                self.assertEqual(self.run_cn(command, "-h").stdout, self.run_cn(command, "--help").stdout)
                self.assert_no_effect(command)

    def test_an_unknown_option_is_a_usage_error(self):
        for command in COMMANDS:
            if command in PASS_THROUGH:
                continue
            with self.subTest(command=command):
                result = self.run_cn(command, "--no-such-option")
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, "")
                lines = result.stderr.splitlines()
                self.assertTrue(any(line.startswith("usage: ") for line in lines), result.stderr)
                self.assertEqual(lines[-1], f"Try '{command} --help'.")
                self.assert_no_effect(command)

    def test_help_after_other_options(self):
        for command, args in (("cn-setup", ["--check", "--help"]), ("cn-doctor", ["--only-gateway", "-h"]),
                              ("cn-new-agent", ["--with", "codex", "--help"]),
                              ("cn-wait", ["build", "s", "a", "--help"])):
            with self.subTest(command=command):
                result = self.run_cn(command, *args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(result.stdout.startswith("NAME\n"))
                self.assert_no_effect(command)

    def test_sandbox_passes_other_arguments_on(self):
        repo = self.tmp / "agent"
        (repo / "sandbox").mkdir(parents=True)
        (repo / "sandbox" / "sandbox.sh").write_text('echo "sandbox.sh $*"\n')
        subprocess.run(["/usr/bin/git", "init", "-q", str(repo)], check=True, env={**self.env, "PATH": "/usr/bin:/bin"})
        env = {**self.env, "PATH": f"{self.bin}:/usr/bin:/bin"}
        (self.bin / "git").unlink()  # cn-sandbox finds the repository with git
        result = subprocess.run(["/bin/bash", str(ROOT / "bin" / "cn-sandbox"), "logs", "--help"], cwd=repo, env=env,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "sandbox.sh logs --help\n")

    def test_doctor_refuses_forget_key(self):
        result = self.run_cn("cn-doctor", "--forget-key")
        self.assertEqual(result.returncode, 2)
        self.assertIn("cn-setup --forget-key", result.stderr)
        self.assertTrue(result.stderr.rstrip().endswith("Try 'cn-doctor --help'."))
        self.assert_no_effect("cn-doctor")

    def test_wait_keeps_the_max_option(self):
        result = self.run_cn("cn-wait", "build", "--max", "5", "--bogus")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown option '--bogus'", result.stderr)


if __name__ == "__main__":
    unittest.main()
