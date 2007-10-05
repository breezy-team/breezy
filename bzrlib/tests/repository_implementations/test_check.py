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
from bzrlib.repository import _RevisionTextVersionCache
from bzrlib.tests import TestNotApplicable
from bzrlib.tests.repository_implementations import TestCaseWithRepository
from bzrlib.tests.repository_implementations.helpers import (
    TestCaseWithBrokenRevisionIndex,
    )


class TestFindInconsistentRevisionParents(TestCaseWithBrokenRevisionIndex):

    def test__find_inconsistent_revision_parents(self):
        """_find_inconsistent_revision_parents finds revisions with broken
        parents.
        """
        repo = self.make_repo_with_extra_ghost_index()
        self.assertEqual(
            [('revision-id', ['incorrect-parent'], [])],
            list(repo._find_inconsistent_revision_parents()))

    def test__check_for_inconsistent_revision_parents(self):
        """_check_for_inconsistent_revision_parents raises BzrCheckError if
        there are any revisions with inconsistent parents.
        """
        repo = self.make_repo_with_extra_ghost_index()
        self.assertRaises(
            errors.BzrCheckError,
            repo._check_for_inconsistent_revision_parents)

    def test__check_for_inconsistent_revision_parents_on_clean_repo(self):
        """_check_for_inconsistent_revision_parents does nothing if there are
        no broken revisions.
        """
        repo = self.make_repository('empty-repo')
        if not repo.revision_graph_can_have_wrong_parents():
            raise TestNotApplicable(
                '%r cannot have corrupt revision index.' % repo)
        repo._check_for_inconsistent_revision_parents()  # nothing happens

    def test_check_reports_bad_ancestor(self):
        repo = self.make_repo_with_extra_ghost_index()
        # XXX: check requires a non-empty revision IDs list, but it ignores the
        # contents of it!
        check_object = repo.check(['ignored'])
        check_object.report_results(verbose=False)
        log = self._get_log(keep_log_file=True)
        self.assertContainsRe(
            log, '1 revisions have incorrect parents in the revision index')
        check_object.report_results(verbose=True)
        log = self._get_log(keep_log_file=True)
        self.assertContainsRe(
            log,
            "revision-id has wrong parents in index: "
            r"\['incorrect-parent'\] should be \[\]")

class TestFindBadAncestors(TestCaseWithRepository):

    def make_broken_repository(self):
        repo = self.make_repository('.')
        cleanups = []
        try:
            repo.lock_write()
            cleanups.append(repo.unlock)
            repo.start_write_group()
            cleanups.append(repo.commit_write_group)
            # make rev1a: A well-formed revision, containing 'file1'
            inv = inventory.Inventory(revision_id='rev1a')
            inv.root.revision = 'rev1a'
            self.add_file(repo, inv, 'file1', 'rev1a', [])
            repo.add_inventory('rev1a', inv, [])
            revision = _mod_revision.Revision('rev1a',
                committer='jrandom@example.com', timestamp=0,
                inventory_sha1='', timezone=0, message='foo', parent_ids=[])
            repo.add_revision('rev1a',revision, inv)

            # make rev1b, which has no Revision, but has an Inventory, and
            # file1
            inv = inventory.Inventory(revision_id='rev1b')
            inv.root.revision = 'rev1b'
            self.add_file(repo, inv, 'file1', 'rev1b', [])
            repo.add_inventory('rev1b', inv, [])

            # make rev2, with file1 and file2
            # file2 is sane
            # file1 has 'rev1b' as an ancestor, even though this is not
            # mentioned by 'rev1a', making it an unreferenced ancestor
            inv = inventory.Inventory()
            self.add_file(repo, inv, 'file1', 'rev2', ['rev1a', 'rev1b'])
            self.add_file(repo, inv, 'file2', 'rev2', [])
            self.add_revision(repo, 'rev2', inv, ['rev1a'])

            # make ghost revision rev1c
            inv = inventory.Inventory()
            self.add_file(repo, inv, 'file2', 'rev1c', [])

            # make rev3 with file2
            # file2 refers to 'rev1c', which is a ghost in this repository, so
            # file2 cannot have rev1c as its ancestor.
            inv = inventory.Inventory()
            self.add_file(repo, inv, 'file2', 'rev3', ['rev1c'])
            self.add_revision(repo, 'rev3', inv, ['rev1c'])
            return repo
        finally:
            for cleanup in reversed(cleanups):
                cleanup()

    def add_revision(self, repo, revision_id, inv, parent_ids):
        inv.revision_id = revision_id
        inv.root.revision = revision_id
        repo.add_inventory(revision_id, inv, parent_ids)
        revision = _mod_revision.Revision(revision_id,
            committer='jrandom@example.com', timestamp=0, inventory_sha1='',
            timezone=0, message='foo', parent_ids=parent_ids)
        repo.add_revision(revision_id,revision, inv)

    def add_file(self, repo, inv, filename, revision, parents):
        file_id = filename + '-id'
        entry = inventory.InventoryFile(file_id, filename, 'TREE_ROOT')
        entry.revision = revision
        entry.text_size = 0
        inv.add(entry)
        vf = repo.weave_store.get_weave_or_empty(file_id,
                                                 repo.get_transaction())
        vf.add_lines(revision, parents, ['line\n'])

    def find_bad_ancestors(self, file_id, revision_ids):
        repo = self.make_broken_repository()
        vf = repo.weave_store.get_weave(file_id, repo.get_transaction())
        return repo.find_bad_ancestors(revision_ids, file_id, vf,
                                       _RevisionTextVersionCache(repo))

    def test_normal_first_revision(self):
        repo = self.make_broken_repository()
        vf = repo.weave_store.get_weave('file1-id', repo.get_transaction())
        inventory_versions =_RevisionTextVersionCache(repo)
        result = repo.find_bad_ancestors(['rev1a'], 'file1-id', vf,
            inventory_versions)
        self.assertSubset(['rev1a'],
                          inventory_versions.revision_versions.keys())
        self.assertEqual('rev1a',
                         inventory_versions.get_text_version('file1-id',
                                                             'rev1a'))
        self.assertEqual({}, result)

    def test_not_present_in_revision(self):
        # It is not an error to check a revision that does not contain the file
        result = self.find_bad_ancestors('file2-id', ['rev1a'])
        self.assertEqual({}, result)

    def test_second_revision(self):
        repo = self.make_broken_repository()
        vf = repo.weave_store.get_weave('file1-id', repo.get_transaction())
        inventory_versions =_RevisionTextVersionCache(repo)
        result = repo.find_bad_ancestors(['rev2'], 'file1-id', vf,
            inventory_versions)
        self.assertEqual({'rev1b': set(['rev2'])}, result)

    def test_ghost(self):
        result = self.find_bad_ancestors('file2-id', ['rev3'])
        self.assertEqual({'rev1c': set(['rev3'])}, result)

