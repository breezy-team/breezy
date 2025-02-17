# Copyright (C) 2011, 2016 Canonical Ltd
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

"""Tests for weave repositories.

For interface tests see tests/per_repository/*.py.

"""

import sys
from io import BytesIO
from stat import S_ISDIR

from ...bzr.bzrdir import BzrDirMetaFormat1
from ...bzr.serializer import revision_format_registry
from ...errors import IllegalPath
from ...repository import InterRepository, Repository
from ...tests import TestCase, TestCaseWithTransport
from ...transport import NoSuchFile
from . import xml4
from .bzrdir import BzrDirFormat6
from .repository import (
    InterWeaveRepo,
    RepositoryFormat4,
    RepositoryFormat5,
    RepositoryFormat6,
    RepositoryFormat7,
)


class TestFormat6(TestCaseWithTransport):
    def test_attribute__fetch_order(self):
        """Weaves need topological data insertion."""
        control = BzrDirFormat6().initialize(self.get_url())
        repo = RepositoryFormat6().initialize(control)
        self.assertEqual("topological", repo._format._fetch_order)

    def test_attribute__fetch_uses_deltas(self):
        """Weaves do not reuse deltas."""
        control = BzrDirFormat6().initialize(self.get_url())
        repo = RepositoryFormat6().initialize(control)
        self.assertEqual(False, repo._format._fetch_uses_deltas)

    def test_attribute__fetch_reconcile(self):
        """Weave repositories need a reconcile after fetch."""
        control = BzrDirFormat6().initialize(self.get_url())
        repo = RepositoryFormat6().initialize(control)
        self.assertEqual(True, repo._format._fetch_reconcile)

    def test_no_ancestry_weave(self):
        control = BzrDirFormat6().initialize(self.get_url())
        RepositoryFormat6().initialize(control)
        # We no longer need to create the ancestry.weave file
        # since it is *never* used.
        self.assertRaises(NoSuchFile, control.transport.get, "ancestry.weave")

    def test_supports_external_lookups(self):
        control = BzrDirFormat6().initialize(self.get_url())
        repo = RepositoryFormat6().initialize(control)
        self.assertFalse(repo._format.supports_external_lookups)


class TestFormat7(TestCaseWithTransport):
    def test_attribute__fetch_order(self):
        """Weaves need topological data insertion."""
        control = BzrDirMetaFormat1().initialize(self.get_url())
        repo = RepositoryFormat7().initialize(control)
        self.assertEqual("topological", repo._format._fetch_order)

    def test_attribute__fetch_uses_deltas(self):
        """Weaves do not reuse deltas."""
        control = BzrDirMetaFormat1().initialize(self.get_url())
        repo = RepositoryFormat7().initialize(control)
        self.assertEqual(False, repo._format._fetch_uses_deltas)

    def test_attribute__fetch_reconcile(self):
        """Weave repositories need a reconcile after fetch."""
        control = BzrDirMetaFormat1().initialize(self.get_url())
        repo = RepositoryFormat7().initialize(control)
        self.assertEqual(True, repo._format._fetch_reconcile)

    def test_disk_layout(self):
        control = BzrDirMetaFormat1().initialize(self.get_url())
        repo = RepositoryFormat7().initialize(control)
        # in case of side effects of locking.
        repo.lock_write()
        repo.unlock()
        # we want:
        # format 'Bazaar-NG Repository format 7'
        # lock ''
        # inventory.weave == empty_weave
        # empty revision-store directory
        # empty weaves directory
        t = control.get_repository_transport(None)
        with t.get("format") as f:
            self.assertEqualDiff(b"Bazaar-NG Repository format 7", f.read())
        self.assertTrue(S_ISDIR(t.stat("revision-store").st_mode))
        self.assertTrue(S_ISDIR(t.stat("weaves").st_mode))
        with t.get("inventory.weave") as f:
            self.assertEqualDiff(b"# bzr weave file v5\nw\nW\n", f.read())
        # Creating a file with id Foo:Bar results in a non-escaped file name on
        # disk.
        control.create_branch()
        tree = control.create_workingtree()
        tree.add(["foo"], ["file"], ids=[b"Foo:Bar"])
        tree.put_file_bytes_non_atomic("foo", b"content\n")
        try:
            tree.commit("first post", rev_id=b"first")
        except IllegalPath:
            if sys.platform != "win32":
                raise
            self.knownFailure(
                "Foo:Bar cannot be used as a file-id on windows in repo format 7"
            )
            return
        with t.get("weaves/74/Foo%3ABar.weave") as f:
            self.assertEqualDiff(
                b"# bzr weave file v5\n"
                b"i\n"
                b"1 7fe70820e08a1aac0ef224d9c66ab66831cc4ab1\n"
                b"n first\n"
                b"\n"
                b"w\n"
                b"{ 0\n"
                b". content\n"
                b"}\n"
                b"W\n",
                f.read(),
            )

    def test_shared_disk_layout(self):
        control = BzrDirMetaFormat1().initialize(self.get_url())
        RepositoryFormat7().initialize(control, shared=True)
        # we want:
        # format 'Bazaar-NG Repository format 7'
        # inventory.weave == empty_weave
        # empty revision-store directory
        # empty weaves directory
        # a 'shared-storage' marker file.
        # lock is not present when unlocked
        t = control.get_repository_transport(None)
        with t.get("format") as f:
            self.assertEqualDiff(b"Bazaar-NG Repository format 7", f.read())
        with t.get("shared-storage") as f:
            self.assertEqualDiff(b"", f.read())
        self.assertTrue(S_ISDIR(t.stat("revision-store").st_mode))
        self.assertTrue(S_ISDIR(t.stat("weaves").st_mode))
        with t.get("inventory.weave") as f:
            self.assertEqualDiff(b"# bzr weave file v5\nw\nW\n", f.read())
        self.assertFalse(t.has("branch-lock"))

    def test_creates_lockdir(self):
        """Make sure it appears to be controlled by a LockDir existence."""
        control = BzrDirMetaFormat1().initialize(self.get_url())
        repo = RepositoryFormat7().initialize(control, shared=True)
        t = control.get_repository_transport(None)
        # TODO: Should check there is a 'lock' toplevel directory,
        # regardless of contents
        self.assertFalse(t.has("lock/held/info"))
        with repo.lock_write():
            self.assertTrue(t.has("lock/held/info"))

    def test_uses_lockdir(self):
        """Repo format 7 actually locks on lockdir."""
        base_url = self.get_url()
        control = BzrDirMetaFormat1().initialize(base_url)
        repo = RepositoryFormat7().initialize(control, shared=True)
        t = control.get_repository_transport(None)
        repo.lock_write()
        repo.unlock()
        del repo
        # make sure the same lock is created by opening it
        repo = Repository.open(base_url)
        repo.lock_write()
        self.assertTrue(t.has("lock/held/info"))
        repo.unlock()
        self.assertFalse(t.has("lock/held/info"))

    def test_shared_no_tree_disk_layout(self):
        control = BzrDirMetaFormat1().initialize(self.get_url())
        repo = RepositoryFormat7().initialize(control, shared=True)
        repo.set_make_working_trees(False)
        # we want:
        # format 'Bazaar-NG Repository format 7'
        # lock ''
        # inventory.weave == empty_weave
        # empty revision-store directory
        # empty weaves directory
        # a 'shared-storage' marker file.
        t = control.get_repository_transport(None)
        with t.get("format") as f:
            self.assertEqualDiff(b"Bazaar-NG Repository format 7", f.read())
        ## self.assertEqualDiff('', t.get('lock').read())
        with t.get("shared-storage") as f:
            self.assertEqualDiff(b"", f.read())
        with t.get("no-working-trees") as f:
            self.assertEqualDiff(b"", f.read())
        repo.set_make_working_trees(True)
        self.assertFalse(t.has("no-working-trees"))
        self.assertTrue(S_ISDIR(t.stat("revision-store").st_mode))
        self.assertTrue(S_ISDIR(t.stat("weaves").st_mode))
        with t.get("inventory.weave") as f:
            self.assertEqualDiff(b"# bzr weave file v5\nw\nW\n", f.read())

    def test_supports_external_lookups(self):
        control = BzrDirMetaFormat1().initialize(self.get_url())
        repo = RepositoryFormat7().initialize(control)
        self.assertFalse(repo._format.supports_external_lookups)


class TestInterWeaveRepo(TestCaseWithTransport):
    def test_make_repository(self):
        out, err = self.run_bzr("init-shared-repository --format=weave a")
        self.assertEqual(
            out,
            """Standalone tree (format: weave)
Location:
  branch root: a
""",
        )
        self.assertEqual(err, "")

    def test_is_compatible_and_registered(self):
        # InterWeaveRepo is compatible when either side
        # is a format 5/6/7 branch
        from ...bzr import knitrepo

        formats = [RepositoryFormat5(), RepositoryFormat6(), RepositoryFormat7()]
        incompatible_formats = [
            RepositoryFormat4(),
            knitrepo.RepositoryFormatKnit1(),
        ]
        repo_a = self.make_repository("a")
        repo_b = self.make_repository("b")
        is_compatible = InterWeaveRepo.is_compatible
        for source in incompatible_formats:
            # force incompatible left then right
            repo_a._format = source
            repo_b._format = formats[0]
            self.assertFalse(is_compatible(repo_a, repo_b))
            self.assertFalse(is_compatible(repo_b, repo_a))
        for source in formats:
            repo_a._format = source
            for target in formats:
                repo_b._format = target
                self.assertTrue(is_compatible(repo_a, repo_b))
        self.assertEqual(InterWeaveRepo, InterRepository.get(repo_a, repo_b).__class__)


_working_inventory_v4 = b"""<inventory file_id="TREE_ROOT">
<entry file_id="bar-20050901064931-73b4b1138abc9cd2" kind="file" name="bar" parent_id="TREE_ROOT" />
<entry file_id="foo-20050801201819-4139aa4a272f4250" kind="directory" name="foo" parent_id="TREE_ROOT" />
<entry file_id="bar-20050824000535-6bc48cfad47ed134" kind="file" name="bar" parent_id="foo-20050801201819-4139aa4a272f4250" />
</inventory>"""


_revision_v4 = b"""<revision committer="Martin Pool &lt;mbp@sourcefrog.net&gt;"
    inventory_id="mbp@sourcefrog.net-20050905080035-e0439293f8b6b9f9"
    inventory_sha1="e79c31c1deb64c163cf660fdedd476dd579ffd41"
    revision_id="mbp@sourcefrog.net-20050905080035-e0439293f8b6b9f9"
    timestamp="1125907235.212"
    timezone="36000">
<message>- start splitting code for xml (de)serialization away from objects
  preparatory to supporting multiple formats by a single library
</message>
<parents>
<revision_ref revision_id="mbp@sourcefrog.net-20050905063503-43948f59fa127d92" revision_sha1="7bdf4cc8c5bdac739f8cf9b10b78cf4b68f915ff" />
</parents>
</revision>
"""


class TestSerializer(TestCase):
    """Test serializer."""

    def test_registry(self):
        self.assertIs(xml4.revision_serializer_v4, revision_format_registry.get("4"))

    def test_canned_inventory(self):
        """Test unpacked a canned inventory v4 file."""
        inp = BytesIO(_working_inventory_v4)
        inv = xml4.inventory_serializer_v4.read_inventory(inp)
        self.assertEqual(len(inv), 4)
        self.assertTrue(inv.has_id(b"bar-20050901064931-73b4b1138abc9cd2"))

    def test_unpack_revision(self):
        """Test unpacking a canned revision v4."""
        inp = BytesIO(_revision_v4)
        rev = xml4.revision_serializer_v4.read_revision(inp)
        eq = self.assertEqual
        eq(rev.committer, "Martin Pool <mbp@sourcefrog.net>")
        eq(rev.inventory_id, b"mbp@sourcefrog.net-20050905080035-e0439293f8b6b9f9")
        eq(len(rev.parent_ids), 1)
        eq(rev.parent_ids[0], b"mbp@sourcefrog.net-20050905063503-43948f59fa127d92")
