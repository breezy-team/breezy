# Copyright (C) 2005-2010 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA


"""Black-box tests for brz re-sign."""

from breezy import gpg, tests
from breezy.bzr.testament import Testament
from breezy.controldir import ControlDir


class ReSign(tests.TestCaseInTempDir):
    def monkey_patch_gpg(self):
        """Monkey patch the gpg signing strategy to be a loopback.

        This also registers the cleanup, so that we will revert to
        the original gpg strategy when done.
        """
        # monkey patch gpg signing mechanism
        self.overrideAttr(gpg, "GPGStrategy", gpg.LoopbackGPGStrategy)

    def setup_tree(self):
        wt = ControlDir.create_standalone_workingtree(".")
        a = wt.commit("base A", allow_pointless=True)
        b = wt.commit("base B", allow_pointless=True)
        c = wt.commit("base C", allow_pointless=True)

        return wt, [a, b, c]

    def assertEqualSignature(self, repo, revision_id):
        """Assert a signature is stored correctly in repository."""
        self.assertEqual(
            b"-----BEGIN PSEUDO-SIGNED CONTENT-----\n"
            + Testament.from_revision(repo, revision_id).as_short_text()
            + b"-----END PSEUDO-SIGNED CONTENT-----\n",
            repo.get_signature_text(revision_id),
        )

    def test_resign(self):
        # Test re signing of data.
        wt, [a, b, c] = self.setup_tree()
        repo = wt.branch.repository

        self.monkey_patch_gpg()
        self.run_bzr("re-sign -r revid:{}".format(a.decode("utf-8")))

        self.assertEqualSignature(repo, a)

        self.run_bzr("re-sign {}".format(b.decode("utf-8")))
        self.assertEqualSignature(repo, b)

    def test_resign_range(self):
        wt, [a, b, c] = self.setup_tree()
        repo = wt.branch.repository

        self.monkey_patch_gpg()
        self.run_bzr("re-sign -r 1..")
        self.assertEqualSignature(repo, a)
        self.assertEqualSignature(repo, b)
        self.assertEqualSignature(repo, c)

    def test_resign_multiple(self):
        wt, rs = self.setup_tree()
        repo = wt.branch.repository

        self.monkey_patch_gpg()
        self.run_bzr("re-sign " + " ".join(r.decode("utf-8") for r in rs))
        for r in rs:
            self.assertEqualSignature(repo, r)

    def test_resign_directory(self):
        """Test --directory option."""
        wt = ControlDir.create_standalone_workingtree("a")
        a = wt.commit("base A", allow_pointless=True)
        b = wt.commit("base B", allow_pointless=True)
        wt.commit("base C", allow_pointless=True)
        repo = wt.branch.repository
        self.monkey_patch_gpg()
        self.run_bzr("re-sign --directory=a -r revid:" + a.decode("utf-8"))
        self.assertEqualSignature(repo, a)
        self.run_bzr("re-sign -d a {}".format(b.decode("utf-8")))
        self.assertEqualSignature(repo, b)
