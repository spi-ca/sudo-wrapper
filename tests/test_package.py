#!/usr/bin/env python3
"""Release archive checks; never execute installed sudo or extract as root."""
import hashlib
import os
from pathlib import Path
import subprocess
import tarfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "sudo-wrapper-linux-x86_64"
ARCHIVE = ROOT / "zig-out/release" / (PREFIX + ".tar.gz")


class PackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run([str(ROOT / "build.sh")], cwd=ROOT, check=True)
        cls.env = {**os.environ, "SOURCE_COMMIT": "0" * 40}
        cls.package()

    @classmethod
    def package(cls):
        subprocess.run([str(ROOT / "package.sh")], cwd=ROOT, env=cls.env, check=True)

    def test_archive_contents_modes_and_symlink(self):
        expected = {PREFIX, PREFIX + "/bin", *(
            PREFIX + "/" + name for name in (
                "README.md", "LICENSE", "BUILD-INFO", "SHA256SUMS",
                "bin/sudo", "bin/sudoedit", "bin/visudo"))}
        with tarfile.open(ARCHIVE, "r:gz") as archive:
            self.assertEqual(set(archive.getnames()), expected)
            alias = archive.getmember(PREFIX + "/bin/sudoedit")
            self.assertTrue(alias.issym())
            self.assertEqual(alias.linkname, "sudo")
            for name, size in [("sudo", 166), ("visudo", 168)]:
                member = archive.getmember(PREFIX + "/bin/" + name)
                self.assertTrue(member.isfile())
                self.assertEqual(member.mode, 0o755)
                self.assertEqual(member.size, size)
                data = archive.extractfile(member).read()
                self.assertEqual(data, (ROOT / "zig-out/bin" / name).read_bytes())
            for name in ("README.md", "LICENSE"):
                member = archive.getmember(PREFIX + "/" + name)
                self.assertEqual(member.mode, 0o644)
                self.assertEqual(archive.extractfile(member).read(),
                                 (ROOT / name).read_bytes())
            for member in archive.getmembers():
                self.assertEqual((member.uid, member.gid, member.mtime), (0, 0, 0))
                self.assertEqual(member.mode & 0o6000, 0)
            info = archive.extractfile(PREFIX + "/BUILD-INFO").read().decode()
            self.assertIn("source_commit=" + "0" * 40 + "\n", info)
            self.assertIn("target=x86_64-linux\n", info)

    def test_archive_and_binary_checksums(self):
        digest, filename = (ROOT / "zig-out/release/SHA256SUMS").read_text().split()
        self.assertEqual(filename, ARCHIVE.name)
        self.assertEqual(digest, hashlib.sha256(ARCHIVE.read_bytes()).hexdigest())
        with tarfile.open(ARCHIVE, "r:gz") as archive:
            checksums = archive.extractfile(PREFIX + "/SHA256SUMS").read().decode()
            for line in checksums.splitlines():
                digest, filename = line.split()
                self.assertIn(filename, ("bin/sudo", "bin/visudo"))
                data = archive.extractfile(PREFIX + "/" + filename).read()
                self.assertEqual(digest, hashlib.sha256(data).hexdigest())
            self.assertEqual(len(checksums.splitlines()), 2)

    def test_package_rebuild_is_deterministic(self):
        original = ARCHIVE.read_bytes()
        self.package()
        self.assertEqual(ARCHIVE.read_bytes(), original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
