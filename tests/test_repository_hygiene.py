"""Guards against committing personal data (Riot ID, API key) to the repository.

These tests are intentionally simple: they inspect the git index rather than the
working tree, so they fail if a sensitive file has been staged or committed.
"""
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAKE_KEYS = {"fake-key-for-tests"}
SECRET_PATTERNS = (
    re.compile(r'"api_key"\s*:\s*"([^"]+)"'),
    re.compile(r'^HENRIK_API_KEY\s*=\s*(\S+)', re.MULTILINE),
)


def git(*args):
    return subprocess.run(
        ["git", *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=True,
    )


class RepositoryHygieneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            inside = git("rev-parse", "--is-inside-work-tree").stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            raise unittest.SkipTest("git indisponible")
        if inside != "true":
            raise unittest.SkipTest("pas un dépôt git")

    def tracked_files(self):
        return [line for line in git("ls-files").stdout.splitlines() if line.strip()]

    def test_personal_data_is_ignored(self):
        for path in ("data/config.json", "data/valorant.db", "data/valorant.db-wal", ".env"):
            with self.subTest(path=path):
                result = subprocess.run(
                    ["git", "check-ignore", "-q", "--no-index", path],
                    cwd=str(ROOT),
                )
                self.assertEqual(result.returncode, 0, f"{path} doit être ignoré par .gitignore")

    def test_no_personal_file_is_tracked(self):
        offenders = []
        for path in self.tracked_files():
            name = path.rsplit("/", 1)[-1]
            if (
                path.startswith("data/")
                or name in {"config.json", ".env"}
                or name.endswith((".db", ".db-shm", ".db-wal", ".sqlite"))
            ):
                offenders.append(path)
        self.assertEqual(offenders, [], "des fichiers personnels sont versionnés")

    def test_no_api_key_is_committed(self):
        leaks = []
        for path in self.tracked_files():
            candidate = ROOT / path
            if not candidate.is_file() or candidate.stat().st_size > 1_000_000:
                continue
            try:
                text = candidate.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for pattern in SECRET_PATTERNS:
                for match in pattern.finditer(text):
                    value = match.group(1).strip()
                    if value and value not in FAKE_KEYS:
                        leaks.append(f"{path}: {value[:6]}…")
        self.assertEqual(leaks, [], "une clé API semble présente dans les fichiers versionnés")


if __name__ == "__main__":
    unittest.main()
