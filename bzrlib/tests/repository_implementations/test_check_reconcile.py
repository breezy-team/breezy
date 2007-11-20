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

"""Tests that use BrokenRepoScenario objects.

That is, tests for reconcile and check.
"""


from bzrlib.inventory import Inventory, InventoryFile
from bzrlib.osutils import sha
from bzrlib.revision import Revision
from bzrlib.tests import TestNotApplicable
from bzrlib.tests.repository_implementations import TestCaseWithRepository


class TestFileParentReconciliation(TestCaseWithRepository):
    """Tests for how reconcile corrects errors in parents of file versions."""

    def make_populated_repository(self, factory):
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
        """Add a revision with a given inventory and parents to a repository.
        
        :param repo: a repository.
        :param revision_id: the revision ID for the new revision.
        :param inv: an inventory (such as created by
            `make_one_file_inventory`).
        :param parent_ids: the parents for the new revision.
        """
        inv.revision_id = revision_id
        inv.root.revision = revision_id
        if repo.supports_rich_root():
            root_id = inv.root.file_id
            vf = repo.weave_store.get_weave_or_empty(root_id,
                repo.get_transaction())
            vf.add_lines(revision_id, [], [])
        repo.add_inventory(revision_id, inv, parent_ids)
        revision = Revision(revision_id, committer='jrandom@example.com',
            timestamp=0, inventory_sha1='', timezone=0, message='foo',
            parent_ids=parent_ids)
        repo.add_revision(revision_id,revision, inv)

    def make_one_file_inventory(self, repo, revision, parents,
                                inv_revision=None, root_revision=None,
                                file_contents=None, make_file_version=True):
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
        :param file_contents: if not None, the contents of this file version.
            Otherwise a unique default (based on revision ID) will be
            generated.
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
        if file_contents is None:
            file_contents = '%sline\n' % entry.revision
        entry.text_sha1 = sha(file_contents).hexdigest()
        inv.add(entry)
        if make_file_version:
            vf = repo.weave_store.get_weave_or_empty(file_id,
                                                     repo.get_transaction())
            vf.add_lines(revision, parents, [file_contents])
        return inv

    def require_repo_suffers_text_parent_corruption(self, repo):
        if not repo._reconcile_fixes_text_parents:
            raise TestNotApplicable(
                    "Format does not support text parent reconciliation")

    def file_parents(self, repo, revision_id):
        return tuple(repo.weave_store.get_weave('a-file-id',
            repo.get_transaction()).get_parents(revision_id))

    def assertFileVersionAbsent(self, repo, revision_id):
        self.assertFalse(repo.weave_store.get_weave('a-file-id',
            repo.get_transaction()).has_version(revision_id),
            'File version %s wrongly present.' % (revision_id,))

    def assertParentsMatch(self, expected_parents_for_versions, repo,
                           when_description):
        for expected_parents, version in expected_parents_for_versions:
            if expected_parents is None:
                self.assertFileVersionAbsent(repo, version)
            else:
                found_parents = self.file_parents(repo, version)
                self.assertEqual(expected_parents, found_parents,
                    "%s reconcile %s has parents %s, should have %s."
                    % (when_description, version, found_parents,
                       expected_parents))

    def shas_for_versions_of_file(self, repo, versions):
        """Get the SHA-1 hashes of the versions of 'a-file' in the repository.
        
        :param repo: the repository to get the hashes from.
        :param versions: a list of versions to get hashes for.

        :returns: A dict of `{version: hash}`.
        """
        vf = repo.weave_store.get_weave('a-file-id', repo.get_transaction())
        return dict((v, vf.get_sha1(v)) for v in versions)

    def test_reconcile_behaviour(self):
        """Populate a repository and reconcile it, verifying the state before
        and after.
        """
        scenario = self.scenario_class(self)
        repo = self.make_populated_repository(scenario.populate_repository)
        self.require_repo_suffers_text_parent_corruption(repo)
        repo.lock_read()
        try:
            self.assertParentsMatch(scenario.populated_parents(), repo,
                'before')
            vf_shas = self.shas_for_versions_of_file(
                repo, scenario.all_versions_after_reconcile())
        finally:
            repo.unlock()
        result = repo.reconcile(thorough=True)
        repo.lock_read()
        try:
            self.assertParentsMatch(scenario.corrected_parents(), repo,
                'after')
            # The contents of the versions in the versionedfile should be the
            # same after the reconcile.
            self.assertEqual(
                vf_shas,
                self.shas_for_versions_of_file(
                    repo, scenario.all_versions_after_reconcile()))

            for file_version in scenario.corrected_fulltexts():
                vf = repo.weave_store.get_weave(
                    'a-file-id', repo.get_transaction())
                self.assertEqual('fulltext',
                    vf._index.get_method(file_version),
                    '%r should be fulltext' % (file_version,))
        finally:
            repo.unlock()

    def test_check_behaviour(self):
        """Populate a repository and check it, and verify the output."""
        scenario = self.scenario_class(self)
        repo = self.make_populated_repository(scenario.populate_repository)
        self.require_repo_suffers_text_parent_corruption(repo)
        check_result = repo.check()
        check_result.report_results(verbose=True)
        for pattern in scenario.check_regexes(repo):
            self.assertContainsRe(
                self._get_log(keep_log_file=True),
                pattern)

