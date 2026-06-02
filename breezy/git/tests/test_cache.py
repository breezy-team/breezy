# Copyright (C) 2009-2018 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Tests for GitShaMap."""

import contextlib
import os
import stat

from dulwich.objects import Blob, Commit, Tree

from ...revision import Revision
from ...tests import TestCase, TestCaseInTempDir, UnavailableFeature
from ...transport import get_transport
from ..cache import (
    DictBzrGitCache,
    IndexBzrGitCache,
    IndexGitCacheFormat,
    SqliteBzrGitCache,
    TdbBzrGitCache,
)


class TestGitShaMap:
    def _get_test_commit(self):
        c = Commit()
        c.committer = b"Jelmer <jelmer@samba.org>"
        c.commit_time = 0
        c.commit_timezone = 0
        c.author = b"Jelmer <jelmer@samba.org>"
        c.author_time = 0
        c.author_timezone = 0
        c.message = b"Teh foo bar"
        c.tree = b"cc9462f7f8263ef5adfbeff2fb936bb36b504cba"
        return c

    def test_commit(self):
        self.map.start_write_group()
        updater = self.cache.get_updater(
            Revision(
                b"myrevid",
                parent_ids=[],
                message="",
                committer="",
                timezone=0,
                timestamp=0,
                properties={},
                inventory_sha1=None,
            )
        )
        c = self._get_test_commit()
        updater.add_object(
            c, {"testament3-sha1": b"cc9462f7f8263ef5adf8eff2fb936bb36b504cba"}, None
        )
        updater.finish()
        self.map.commit_write_group()
        self.assertEqual(
            [
                (
                    "commit",
                    (
                        b"myrevid",
                        b"cc9462f7f8263ef5adfbeff2fb936bb36b504cba",
                        {
                            "testament3-sha1": b"cc9462f7f8263ef5adf8eff2fb936bb36b504cba"
                        },
                    ),
                )
            ],
            list(self.map.lookup_git_sha(c.id)),
        )
        self.assertEqual(c.id, self.map.lookup_commit(b"myrevid"))

    def test_lookup_notfound(self):
        self.assertRaises(
            KeyError,
            list,
            self.map.lookup_git_sha(b"5686645d49063c73d35436192dfc9a160c672301"),
        )

    def test_blob(self):
        self.map.start_write_group()
        updater = self.cache.get_updater(
            Revision(
                b"myrevid",
                parent_ids=[],
                message="",
                committer="",
                timezone=0,
                timestamp=0,
                properties={},
                inventory_sha1=None,
            )
        )
        updater.add_object(self._get_test_commit(), {"testament3-sha1": b"Test"}, None)
        b = Blob()
        b.data = b"TEH BLOB"
        updater.add_object(b, (b"myfileid", b"myrevid"), None)
        updater.finish()
        self.map.commit_write_group()
        self.assertEqual(
            [("blob", (b"myfileid", b"myrevid"))], list(self.map.lookup_git_sha(b.id))
        )
        self.assertEqual(b.id, self.map.lookup_blob_id(b"myfileid", b"myrevid"))

    def test_tree(self):
        self.map.start_write_group()
        updater = self.cache.get_updater(
            Revision(
                b"somerevid",
                parent_ids=[],
                message="",
                committer="",
                timezone=0,
                timestamp=0,
                properties={},
                inventory_sha1=None,
            )
        )
        updater.add_object(
            self._get_test_commit(), {"testament3-sha1": b"mytestamentsha"}, None
        )
        t = Tree()
        t.add(b"somename", stat.S_IFREG, Blob().id)
        updater.add_object(t, (b"fileid", b"myrevid"), b"")
        updater.finish()
        self.map.commit_write_group()
        self.assertEqual(
            [("tree", (b"fileid", b"myrevid"))], list(self.map.lookup_git_sha(t.id))
        )
        # It's possible for a backend to not implement lookup_tree
        with contextlib.suppress(NotImplementedError):
            self.assertEqual(t.id, self.map.lookup_tree_id(b"fileid", b"myrevid"))

    def test_revids(self):
        self.map.start_write_group()
        updater = self.cache.get_updater(
            Revision(
                b"myrevid",
                parent_ids=[],
                message="",
                committer="",
                timezone=0,
                timestamp=0,
                properties={},
                inventory_sha1=None,
            )
        )
        c = self._get_test_commit()
        updater.add_object(c, {"testament3-sha1": b"mtestament"}, None)
        updater.finish()
        self.map.commit_write_group()
        self.assertEqual([b"myrevid"], list(self.map.revids()))

    def test_missing_revisions(self):
        self.map.start_write_group()
        updater = self.cache.get_updater(
            Revision(
                b"myrevid",
                parent_ids=[],
                message="",
                committer="",
                timezone=0,
                timestamp=0,
                properties={},
                inventory_sha1=None,
            )
        )
        c = self._get_test_commit()
        updater.add_object(c, {"testament3-sha1": b"testament"}, None)
        updater.finish()
        self.map.commit_write_group()
        self.assertEqual(
            {b"lala", b"bla"},
            set(self.map.missing_revisions([b"myrevid", b"lala", b"bla"])),
        )


class DictGitShaMapTests(TestCase, TestGitShaMap):
    def setUp(self):
        TestCase.setUp(self)
        self.cache = DictBzrGitCache()
        self.map = self.cache.idmap


class SqliteGitShaMapTests(TestCaseInTempDir, TestGitShaMap):
    def setUp(self):
        TestCaseInTempDir.setUp(self)
        self.cache = SqliteBzrGitCache(os.path.join(self.test_dir, "foo.db"))
        self.map = self.cache.idmap


class TdbGitShaMapTests(TestCaseInTempDir, TestGitShaMap):
    def setUp(self):
        TestCaseInTempDir.setUp(self)
        try:
            self.cache = TdbBzrGitCache(os.path.join(self.test_dir, "foo.tdb"))
        except ModuleNotFoundError as err:
            raise UnavailableFeature("Missing tdb") from err
        self.map = self.cache.idmap


class IndexGitShaMapTests(TestCaseInTempDir, TestGitShaMap):
    def setUp(self):
        TestCaseInTempDir.setUp(self)
        transport = get_transport(self.test_dir)
        IndexGitCacheFormat().initialize(transport)
        self.cache = IndexBzrGitCache(transport)
        self.map = self.cache.idmap
