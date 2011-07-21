# Copyright (C) 2007-2011 Canonical Ltd
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


"""Test operations that check the repository for corruption"""

from bzrlib import (
    config as _mod_config,
    revision as _mod_revision,
    )
from bzrlib.tests.per_repository import TestCaseWithRepository


class TestNoSpuriousInconsistentAncestors(TestCaseWithRepository):

    def test_two_files_different_versions_no_inconsistencies_bug_165071(self):
        """Two files, with different versions can be clean."""
        tree = self.make_branch_and_tree('.')
        self.build_tree(['foo'])
        tree.smart_add(['.'])
        revid1 = tree.commit('1')
        self.build_tree(['bar'])
        tree.smart_add(['.'])
        revid2 = tree.commit('2')
        check_object = tree.branch.repository.check([revid1, revid2])
        check_object.report_results(verbose=True)
        self.assertContainsRe(self.get_log(), "0 unreferenced text versions")


class TestCleanRepository(TestCaseWithRepository):

    def test_new_repo(self):
        repo = self.make_repository('foo')
        repo.lock_write()
        self.addCleanup(repo.unlock)
        config = _mod_config.Config()
        self.overrideEnv('BZR_EMAIL', 'foo@sample.com')
        builder = repo.get_commit_builder(None, [], config)
        list(builder.record_iter_changes(None, _mod_revision.NULL_REVISION, [
            ('TREE_ROOT', (None, ''), True, (False, True), (None, None),
            (None, ''), (None, 'directory'), (None, False))]))
        builder.finish_inventory()
        rev_id = builder.commit('first post')
        result = repo.check(None, check_repo=True)
        result.report_results(True)
        log = self.get_log()
        self.assertFalse('Missing' in log, "Something was missing in %r" % log)
