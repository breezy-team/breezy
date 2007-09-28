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


from bzrlib.inventory import Inventory, InventoryFile
from bzrlib.revision import Revision
from bzrlib.tests import TestNotApplicable
from bzrlib.tests.repository_implementations import TestCaseWithRepository

import sha


class TestReconcile(TestCaseWithRepository):
    """Tests for how reconcile corrects errors in parents of file versions."""

    def assertCheckScenario(self, scenario):
        repo = self.make_repository_using_factory(scenario.populate_repository)
        self.require_text_parent_corruption(repo)
        check_result = repo.check()
        check_result.report_results(verbose=True)
        for pattern in scenario.check_regexes():
            self.assertContainsRe(
                self._get_log(keep_log_file=True),
                pattern)

    def make_repository_using_factory(self, factory):
        """Create a new repository populated by the given factory."""
        repo = self.make_repository('broken-repo')
        repo.lock_write()
        try:
            repo.start_write_group()
            try:
                factory(repo)
                repo.commit_write_group()
                return repo
            except:
                repo.abort_write_group()
                raise
        finally:
            repo.unlock()

    def add_revision(self, repo, revision_id, inv, parent_ids):
        inv.revision_id = revision_id
        inv.root.revision = revision_id
        repo.add_inventory(revision_id, inv, parent_ids)
        revision = Revision(revision_id, committer='jrandom@example.com',
            timestamp=0, inventory_sha1='', timezone=0, message='foo',
            parent_ids=parent_ids)
        repo.add_revision(revision_id,revision, inv)

    def make_one_file_inventory(self, repo, revision, parents,
                                inv_revision=None, root_revision=None):
        """Make an inventory containing a version of a file with ID 'a-file'.

        The file's ID will be 'a-file', and its filename will be 'a file name',
        stored at the tree root.

        :param repo: a repository to add the new file version to.
        :param revision: the revision ID of the new inventory.
        :param parents: the parents for this revision of 'a-file'.
        :param inv_revision: if not None, the revision ID to store in the
            inventory entry.  Otherwise, this defaults to revision.
        :param root_revision: if not None, the inventory's root.revision will
            be set to this.
        """
        inv = Inventory(revision_id=revision)
        if root_revision is not None:
            inv.root.revision = root_revision
        file_id = 'a-file-id'
        entry = InventoryFile(file_id, 'a file name', 'TREE_ROOT')
        if inv_revision is not None:
            entry.revision = inv_revision
        else:
            entry.revision = revision
        entry.text_size = 0
        file_contents = '%sline\n' % entry.revision
        entry.text_sha1 = sha.sha(file_contents).hexdigest()
        inv.add(entry)
        vf = repo.weave_store.get_weave_or_empty(file_id,
                                                 repo.get_transaction())
        vf.add_lines(revision, parents, [file_contents])
        return inv

    def require_text_parent_corruption(self, repo):
        if not repo._reconcile_fixes_text_parents:
            raise TestNotApplicable(
                    "Format does not support text parent reconciliation")

    def file_parents(self, repo, revision_id):
        return repo.weave_store.get_weave('a-file-id',
            repo.get_transaction()).get_parents(revision_id)

    def assertReconcileResults(self, scenario):
        """Construct a repository and reconcile it, verifying the state before
        and after.

        :param scenario: a Scenario to test reconcile on.
        """
        repo = self.make_repository_using_factory(scenario.populate_repository)
        self.require_text_parent_corruption(repo)
        for bad_parents, version in scenario.populated_parents():
            file_parents = self.file_parents(repo, version)
            self.assertEqual(bad_parents, file_parents,
                "Expected version %s of a-file-id to have parents %s before "
                "reconcile, but it has %s instead."
                % (version, bad_parents, file_parents))
        vf = repo.weave_store.get_weave('a-file-id', repo.get_transaction())
        vf_shas = dict((v, vf.get_sha1(v)) for v in scenario.all_versions())
        result = repo.reconcile(thorough=True)
        for good_parents, version in scenario.corrected_parents():
            file_parents = self.file_parents(repo, version)
            self.assertEqual(good_parents, file_parents,
                "Expected version %s of a-file-id to have parents %s after "
                "reconcile, but it has %s instead."
                % (version, good_parents, file_parents))
        # The content of the versionedfile should be the same after the
        # reconcile.
        vf = repo.weave_store.get_weave('a-file-id', repo.get_transaction())
        self.assertEqual(
            vf_shas, dict((v, vf.get_sha1(v)) for v in scenario.all_versions()))

    def test_reconcile(self):
        self.assertReconcileResults(self.scenario_class(self))

    def test_check(self):
        self.assertCheckScenario(self.scenario_class(self))
