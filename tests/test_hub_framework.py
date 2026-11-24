import pathlib, sys, tempfile, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "lib"))
import cn_hub  # noqa: E402


class Framework(unittest.TestCase):
    def repo(self, text):
        d = pathlib.Path(tempfile.mkdtemp())
        if text is not None:
            (d / "requirements.txt").write_text(text)
        return d

    def test_sdk(self):
        self.assertEqual(cn_hub.framework(self.repo("codenow-agent-sdk==2.24.0\n")), "CodeNOW Agent SDK 2.24.0")

    def test_adk_with_extras(self):
        self.assertEqual(cn_hub.framework(self.repo("google-adk[a2a]==2.14.1\nlitellm==1\n")), "Google ADK 2.14.1")

    def test_adk_plain(self):
        self.assertEqual(cn_hub.framework(self.repo("google-adk==2.14.1\n")), "Google ADK 2.14.1")

    def test_none(self):
        self.assertIsNone(cn_hub.framework(self.repo("requests==2\n")))
        self.assertIsNone(cn_hub.framework(self.repo(None)))


if __name__ == "__main__":
    unittest.main()
