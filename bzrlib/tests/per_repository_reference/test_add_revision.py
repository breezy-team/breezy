# Copyright (C) 2008 Canonical Ltd
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

"""Tests for add_revision on a repository with external references."""

from bzrlib import errors
from bzrlib.tests.per_repository_reference import (
    TestCaseWithExternalReferenceRepository,
    )


class TestAddRevision(TestCaseWithExternalReferenceRepository):

    def test_add_revision_goes_to_repo(self):
        # adding a revision only writes to the repository add_revision is
        # called on.
        tree = self.make_branch_and_tree('sample')
        revid = tree.commit('one')
        inv = tree.branch.repository.get_inventory(revid)
        rev = tree.branch.repository.get_revision(revid)
        base = self.make_repository('base')
        repo = self.make_referring('referring', 'base')
        repo.lock_write()
        try:
            repo.start_write_group()
            try:
                rev = tree.branch.repository.get_revision(revid)
                repo.add_revision(revid, rev, inv=inv)
            except:
                repo.abort_write_group()
                raise
            else:
                repo.commit_write_group()
        finally:
            repo.unlock()
        rev2 = repo.get_revision(revid)
        self.assertEqual(rev, rev2)
        self.assertRaises(errors.NoSuchRevision, base.get_revision, revid)
