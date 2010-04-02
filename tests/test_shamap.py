# Copyright (C) 2009 Jelmer Vernooij <jelmer@samba.org>
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for GitShaMap."""

from dulwich.objects import (
    Commit,
    )

import os

from bzrlib.revision import (
    Revision,
    )

from bzrlib.tests import (
    TestCase,
    TestCaseInTempDir,
    UnavailableFeature,
    )
from bzrlib.transport import (
    get_transport,
    )

from bzrlib.plugins.git.shamap import (
    DictBzrGitCache,
    IndexBzrGitCache,
    SqliteBzrGitCache,
    TdbBzrGitCache,
    )

class TestGitShaMap:

    def test_commit(self):
        self.map.start_write_group()
        updater = self.cache.get_updater(Revision("myrevid"))
        c = Commit()
        c.committer = "Jelmer <jelmer@samba.org>"
        c.message = "Teh foo bar"
        c.tree = "cc9462f7f8263ef5adfbeff2fb936bb36b504cba"
        updater.add_object(c, None)
        self.map.commit_write_group()
        self.assertEquals(
            ("commit", ("myrevid", "cc9462f7f8263ef5adfbeff2fb936bb36b504cba")),
            self.map.lookup_git_sha(c.id))

    def test_lookup_notfound(self):
        self.assertRaises(KeyError,
            self.map.lookup_git_sha, "5686645d49063c73d35436192dfc9a160c672301")

    def test_blob(self):
        thesha = "9686645d49063c73d35436192dfc9a160c672301"
        self.map.start_write_group()
        updater = self.cache.get_updater(Revision("myrevid"))
        updater.add_object(Commit(), None)
        self.map.add_entries("myrevid", [], 
            "5686645d49063c73d35436192dfc9a160c672301",
            "cc9462f7f8263ef5adfbeff2fb936bb36b504cba", [
                ("myfileid", "blob", thesha, "myrevid")
                ])
        self.map.commit_write_group()
        self.assertEquals(
            ("blob", ("myfileid", "myrevid")),
            self.map.lookup_git_sha(thesha))
        self.assertEquals(thesha,
            self.map.lookup_blob_id("myfileid", "myrevid"))

    def test_tree(self):
        thesha = "8686645d49063c73d35436192dfc9a160c672301"
        self.map.start_write_group()
        self.map.add_entries("myrevid", [], 
            "5686645d49063c73d35436192dfc9a160c672301",
            "cc9462f7f8263ef5adfbeff2fb936bb36b504cba", [
            ("somepath", "tree", thesha, "myrevid")])
        self.map.commit_write_group()
        self.assertEquals(
            ("tree", ("somepath", "myrevid")),
            self.map.lookup_git_sha(thesha))

    def test_revids(self):
        self.map.start_write_group()
        self.map.add_entries("myrevid", [], 
            "5686645d49063c73d35436192dfc9a160c672301",
            "cc9462f7f8263ef5adfbeff2fb936bb36b504cba", [])
        self.map.commit_write_group()
        self.assertEquals(["myrevid"], list(self.map.revids()))

    def test_missing_revisions(self):
        self.map.start_write_group()
        self.map.add_entries("myrevid", [], 
            "5686645d49063c73d35436192dfc9a160c672301",
            "cc9462f7f8263ef5adfbeff2fb936bb36b504cba", [])
        self.map.commit_write_group()
        self.assertEquals(set(["lala", "bla"]),
            set(self.map.missing_revisions(["myrevid", "lala", "bla"])))


class DictGitShaMapTests(TestCase,TestGitShaMap):

    def setUp(self):
        TestCase.setUp(self)
        self.cache = DictBzrGitCache()
        self.map = self.cache.idmap


class SqliteGitShaMapTests(TestCase,TestGitShaMap):

    def setUp(self):
        TestCase.setUp(self)
        self.cache = SqliteBzrGitCache(os.path.join(self.test_dir, 'foo.db'))
        self.map = self.cache.idmap


class TdbGitShaMapTests(TestCaseInTempDir,TestGitShaMap):

    def setUp(self):
        TestCaseInTempDir.setUp(self)
        try:
            self.cache = TdbBzrGitCache(os.path.join(self.test_dir, 'foo.tdb'))
        except ImportError:
            raise UnavailableFeature("Missing tdb")
        self.map = self.cache.idmap


class IndexGitShaMapTests(TestCaseInTempDir,TestGitShaMap):

    def setUp(self):
        TestCaseInTempDir.setUp(self)
        self.cache = IndexBzrGitCache(get_transport(self.test_dir))
        self.map = self.cache.idmap
