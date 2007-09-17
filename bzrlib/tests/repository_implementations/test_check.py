# Copyright (C) 2007 Canonical Ltd
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


"""Test operations that check the repository for corruption"""


from bzrlib import (
    errors,
    inventory,
    revision as _mod_revision,
    )
from bzrlib.repofmt.knitrepo import RepositoryFormatKnit
from bzrlib.tests.repository_implementations import TestCaseWithRepository
from bzrlib.tests import TestNotApplicable


class TestFindInconsistentRevisionParents(TestCaseWithRepository):

    def setUp(self):
        if not isinstance(self.repository_format, RepositoryFormatKnit):
            # XXX: This could happen to weaves too, but they're pretty
            # deprecated.
            raise TestNotApplicable(
                "%s isn't a knit format" % self.repository_format)
        TestCaseWithRepository.setUp(self)

    def make_repo_with_extra_ghost_index(self):
        """Make a corrupt repository.
        
        It will contain one revision, 'revision-id'.  The knit index will claim
        that it has one parent, 'incorrect-parent', but the revision text will
        claim it has no parents.`

        Note: only the *cache* of the knit index is corrupted.  Thus the
        corruption will only last while the repository is locked.  For this
        reason, the returned repo is (read) locked.
        """
        repo = self.make_repository('broken')
        inv = inventory.Inventory(revision_id='revision-id')
        inv.root.revision = 'revision-id'
        repo.add_inventory('revision-id', inv, [])
        revision = _mod_revision.Revision('revision-id',
            committer='jrandom@example.com', timestamp=0,
            inventory_sha1='', timezone=0, message='message', parent_ids=[])
        repo.add_revision('revision-id',revision, inv)

        # Change the knit index's record of the parents for 'revision-id' to
        # claim it has a parent, 'incorrect-parent', that doesn't exist in this
        # knit at all.
        repo.lock_read()
        rev_knit = repo._get_revision_vf()
        index_cache = rev_knit._index._cache
        cached_index_entry = list(index_cache['revision-id'])
        cached_index_entry[4] = ['incorrect-parent']
        index_cache['revision-id'] = tuple(cached_index_entry)
        return repo

    def test__find_inconsistent_revision_parents(self):
        """_find_inconsistent_revision_parents finds revisions with broken
        parents.
        """
        repo = self.make_repo_with_extra_ghost_index()
        self.assertEqual(
            [('revision-id', ['incorrect-parent'], [])],
            list(repo._find_inconsistent_revision_parents()))
        repo.unlock()

    def test__check_for_inconsistent_revision_parents(self):
        """_check_for_inconsistent_revision_parents raises BzrCheckError if
        there are any revisions with inconsistent parents.
        """
        repo = self.make_repo_with_extra_ghost_index()
        self.assertRaises(
            errors.BzrCheckError,
            repo._check_for_inconsistent_revision_parents)
        repo.unlock()

    def test__check_for_inconsistent_revision_parents_on_clean_repo(self):
        """_check_for_inconsistent_revision_parents does nothing if there are
        no broken revisions.
        """
        repo = self.make_repository('empty-repo')
        repo._check_for_inconsistent_revision_parents()  # nothing happens

