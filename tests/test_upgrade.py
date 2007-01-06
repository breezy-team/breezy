# Copyright (C) 2007 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from bzrlib.bzrdir import BzrDir
from bzrlib.errors import NoRepositoryPresent, InvalidRevisionId
from bzrlib.tests import TestCase, TestCaseWithTransport

from repository import SvnRepository, MAPPING_VERSION
from tests import TestCaseWithSubversionRepository
from upgrade import (change_revision_parent, upgrade_repository, 
                     UpgradeChangesContent, parse_legacy_revision_id,
                     create_upgraded_revid)

class TestUpgradeChangesContent(TestCase):
    def test_init(self):
        x = UpgradeChangesContent("revisionx")
        self.assertEqual("revisionx", x.revid)


class ParserTests(TestCase):
    def test_current(self):
        self.assertEqual(("uuid", "trunk", 1, 2), 
                         parse_legacy_revision_id("svn-v2:1@uuid-trunk"))

    def test_legacy(self):
        self.assertEqual(("uuid", "trunk", 1, 1), 
                         parse_legacy_revision_id("svn-v1:1@uuid-trunk"))

    def test_except(self):
        self.assertRaises(InvalidRevisionId, 
                         parse_legacy_revision_id, "svn-v0:1@uuid-trunk")

    def test_except_nonsvn(self):
        self.assertRaises(InvalidRevisionId, 
                         parse_legacy_revision_id, "blah")

    def test_create_upgraded_revid_new(self):
        self.assertEqual("bla-svn%d-upgrade" % MAPPING_VERSION,
                         create_upgraded_revid("bla"))

    def test_create_upgraded_revid_upgrade(self):
        self.assertEqual("bla-svn%d-upgrade" % MAPPING_VERSION,
                         create_upgraded_revid("bla-svn1-upgrade"))


class ConversionTests(TestCaseWithTransport):
    def test_simple(self):
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        file('hello', 'w').write('hello world')
        wt.add('hello')
        wt.commit(message='add hello', rev_id="bla")
        file('hello', 'w').write('world')
        wt.commit(message='change hello', rev_id="bloe")
        wt.set_last_revision("bla")
        b.set_revision_history(["bla"])
        file('hello', 'w').write('world')
        wt.commit(message='change hello', rev_id="bla2")
        
        newrev = change_revision_parent(wt.branch.repository, "bla2", "bla4", 
                                        ["bloe"])
        self.assertEqual("bla4", newrev)
        self.assertTrue(wt.branch.repository.has_revision(newrev))
        self.assertEqual(["bloe"], wt.branch.repository.revision_parents(newrev))


class UpgradeTests(TestCase):
    pass
