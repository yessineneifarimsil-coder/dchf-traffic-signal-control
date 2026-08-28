"""Cross-platform provenance of the frozen qualification network.

provenance.build_run_manifest hashes the checked-out bytes of the frozen
network and aborts the run when they differ from the SHA-256 in the
configuration. That digest is therefore sensitive to line-ending translation:
under core.autocrlf=true a Windows checkout rewrites every LF to CRLF, so the
working-tree bytes -- and the digest -- change while the file content and its
Git blob identity stay exactly the same.

The repository pins this one path to LF in .gitattributes. These tests fail
loudly, and with a diagnosis rather than a bare hash mismatch, if that pin is
removed or a working tree predates it.
"""

from __future__ import absolute_import

import hashlib
import os
import subprocess
import unittest

from .common import REPOSITORY_ROOT, config_copy


FROZEN_NETWORK = "sumo_scenarios/two_intersections/corridor_2x2/corridor_2x2.net.xml"

RENORMALISE_HINT = (
    "Adding .gitattributes does not rewrite an existing working tree. Delete "
    "the file and check it out again to re-apply the LF pin:\n"
    "    git rm --cached -- {path}\n"
    "    git checkout -- {path}"
).format(path=FROZEN_NETWORK)


def _network_path():
    return os.path.join(REPOSITORY_ROOT, FROZEN_NETWORK)


def _network_bytes():
    with open(_network_path(), "rb") as handle:
        return handle.read()


class FrozenNetworkByteProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.config = config_copy()
        self.frozen_sha = self.config["network"]["sha256"]
        self.frozen_blob = self.config["network"]["git_blob"]
        self.raw = _network_bytes()

    def test_frozen_network_is_checked_out_with_lf_line_endings(self):
        """The root cause, checked directly rather than through the digest."""
        crlf = self.raw.count(b"\r\n")
        self.assertEqual(
            crlf,
            0,
            "The frozen network is checked out with {} CRLF line endings. Its "
            "content is unchanged, but provenance hashes raw bytes, so every "
            "run will abort with a SHA-256 mismatch.\n{}".format(
                crlf, RENORMALISE_HINT
            ),
        )

    def test_checked_out_bytes_hash_to_the_configured_sha256(self):
        """The exact invariant provenance.build_run_manifest enforces."""
        digest = hashlib.sha256(self.raw).hexdigest()
        self.assertEqual(
            digest,
            self.frozen_sha,
            "Checked-out network bytes hash to {} but the frozen "
            "configuration records {}.".format(digest, self.frozen_sha),
        )

    def test_line_ending_damage_is_distinguishable_from_a_content_change(self):
        """Separates a recoverable checkout defect from a real edit.

        If the raw digest is wrong but the LF-normalised digest is right, the
        content is intact and only the line endings need re-normalising. If the
        normalised digest is also wrong, the network itself has changed, which
        is a scientific change and not something .gitattributes can fix.
        """
        normalised = self.raw.replace(b"\r\n", b"\n")
        digest = hashlib.sha256(normalised).hexdigest()
        self.assertEqual(
            digest,
            self.frozen_sha,
            "The frozen network does not match the configured SHA-256 even "
            "after LF normalisation, so its content has changed. This is not "
            "a line-ending problem and must not be resolved by editing the "
            "frozen hash.",
        )

    def test_gitattributes_pins_the_frozen_network_to_lf(self):
        """The protection itself must not be silently dropped."""
        path = os.path.join(REPOSITORY_ROOT, ".gitattributes")
        self.assertTrue(
            os.path.isfile(path),
            ".gitattributes is missing, so the frozen network's line endings "
            "are governed by each contributor's core.autocrlf setting.",
        )
        with open(path, "r") as handle:
            rules = [
                line.split()
                for line in handle
                if line.strip() and not line.lstrip().startswith("#")
            ]
        matching = [rule for rule in rules if rule and rule[0] == FROZEN_NETWORK]
        self.assertTrue(
            matching,
            "No .gitattributes rule pins {} to a fixed line ending.".format(
                FROZEN_NETWORK
            ),
        )
        self.assertIn(
            "eol=lf",
            matching[0],
            "The .gitattributes rule for the frozen network does not force LF.",
        )

    def test_git_blob_identity_is_unchanged(self):
        """Line-ending pinning must not alter the network's Git identity."""
        try:
            output = subprocess.check_output(
                ["git", "hash-object", "--", FROZEN_NETWORK],
                cwd=REPOSITORY_ROOT,
                stderr=subprocess.STDOUT,
            )
        except (OSError, subprocess.CalledProcessError):
            raise unittest.SkipTest("git is unavailable in this environment")
        blob = output.decode("utf-8", errors="replace").strip()
        self.assertEqual(
            blob,
            self.frozen_blob,
            "Git blob identity changed from {} to {}; the frozen network "
            "content must not be modified.".format(self.frozen_blob, blob),
        )


if __name__ == "__main__":
    unittest.main()
