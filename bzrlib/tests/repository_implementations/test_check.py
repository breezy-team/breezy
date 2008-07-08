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
    revision as _mod_revision,
    )
from bzrlib.tests import TestNotApplicable
from bzrlib.tests.repository_implementations import TestCaseWithRepository
from bzrlib.tests.repository_implementations.helpers import (
    TestCaseWithBrokenRevisionIndex,
    )


class TestNoSpuriousInconsistentAncestors(TestCaseWithRepository):

    def test_two_files_different_versions_no_inconsistencies_bug_165071(self):
        """Two files, with different versions can be clean."""
        tree = self.make_branch_and_tree('.')
        self.build_tree(['foo'])
        tree.smart_add(['.'])
        tree.commit('1')
        self.build_tree(['bar'])
        tree.smart_add(['.'])
        tree.commit('2')
        # XXX: check requires a non-empty revision IDs list, but it ignores the
        # contents of it!
        check_object = tree.branch.repository.check(['ignored'])
        check_object.report_results(verbose=False)
        log = self._get_log(keep_log_file=True)
        self.assertContainsRe(
            log,
            "0 unreferenced text versions")


class TestFindInconsistentRevisionParents(TestCaseWithBrokenRevisionIndex):

    def test__find_inconsistent_revision_parents(self):
        """_find_inconsistent_revision_parents finds revisions with broken
        parents.
        """
        repo = self.make_repo_with_extra_ghost_index()
        self.assertEqual(
            [('revision-id', ('incorrect-parent',), ())],
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
        repo.lock_read()
        try:
            repo._check_for_inconsistent_revision_parents()  # nothing happens
        finally:
            repo.unlock()

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
            r"\('incorrect-parent',\) should be \(\)")

