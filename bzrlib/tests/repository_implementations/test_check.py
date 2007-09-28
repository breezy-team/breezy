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
    inventory,
    repository,
    revision as _mod_revision,
    tests,
    )
from bzrlib.repofmt.knitrepo import RepositoryFormatKnit
from bzrlib.repository import _RevisionTextVersionCache
from bzrlib.tests.repository_implementations import (
    TestCaseWithInconsistentRepository,
    )


class TestFindBadAncestors(TestCaseWithInconsistentRepository):

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

    def make_vf(self, revisions_to_add):
        """Make a versioned file with the specified revision graph.

        :param revisions_to_add: a list of (revision_id, parents) tuples.
        """
        repo = self.make_repository('test-repo')
        repo.lock_write()
        # Leave the repo locked until the test is over, so that changes to the
        # cached state aren't accidentally discarded.  This is useful for
        # intentionally corrupting a knit index.
        self.addCleanup(repo.unlock)
        repo.start_write_group()
        self.addCleanup(repo.commit_write_group)

        for revision_id, parents in revisions_to_add:
            self.add_simple_revision(repo, revision_id, parents)

        return repo.weave_store.get_weave('file-id', repo.get_transaction())


    def add_simple_revision(self, repo, revision_id, parents,
                            file_id='file'):
        """Add a simple revision, consisting of just one file."""
        inv = inventory.Inventory(revision_id=revision_id)
        inv.root.revision = revision_id
        self.add_file(repo, inv, file_id, revision_id, parents)
        repo.add_inventory(revision_id, inv, [])
        revision = _mod_revision.Revision(revision_id,
            committer='jrandom@example.com', timestamp=0,
            inventory_sha1='', timezone=0, message='foo', parent_ids=parents)
        repo.add_revision(revision_id, revision, inv)

    def make_parents_provider(self, graph_description):
        class FakeParentsProvider(object):
            def get_parents(self, revision_ids):
                return [list(graph_description.get(r)) for r in revision_ids]
        return FakeParentsProvider()

    def make_revision_graph(self, graph_description):
        class FakeRevisionGraph(object):
            def __init__(self):
                self.calls = []
            def heads(self, revision_ids):
                self.calls.append(('heads', revision_ids))
                return ['good-parent']
        return FakeRevisionGraph()

    def corrupt_knit_index(self, knit, revision_id, new_parent_ids):
        index_cache = knit._index._cache
        cached_index_entry = list(index_cache[revision_id])
        cached_index_entry[4] = new_parent_ids
        index_cache[revision_id] = tuple(cached_index_entry)

    def test_spurious_parents(self):
        """find_bad_ancestors detects file versions where the per-file graph
        claims more parents than the revision graph does.
        """
        if not isinstance(self.repository_format, RepositoryFormatKnit):
            # XXX: This could happen to weaves too, but they're pretty
            # deprecated.
            raise tests.TestNotApplicable(
                "%s isn't a knit format" % self.repository_format)

        # make a versioned file where:
        #  - the knit index for 'broken-revision' claims parents
        #    ['good-parent', 'bad-parent']
        #  - no unreferenced parents; we don't want to trip that case
        #    accidentally.
        correct_graph = [
            ('bad-parent', []),
            ('good-parent', ['bad-parent']),
            ('broken-revision', ['good-parent'])]
        vf = self.make_vf(correct_graph)
        self.corrupt_knit_index(
            vf, 'broken-revision', ['good-parent', 'bad-parent'])
        
        # Invoke find_bad_ancestors
        repo_graph = self.make_revision_graph(dict(correct_graph))
        parents_provider = self.make_parents_provider(dict(correct_graph))
        def fake_text_version_getter(ignored, revision_id):
            return revision_id
        bad_ancestors = vf.find_bad_ancestors(['broken-revision'],
                fake_text_version_getter, 'ignored',
                parents_provider, repo_graph)

        self.assertEqual(
            {'bad-parent': set(['broken-revision'])}, bad_ancestors)
        self.assertEqual(
            [('heads', set(['good-parent', 'bad-parent']))], repo_graph.calls)

    def too_many_parents_factory(self, repo):
        inv = self.make_one_file_inventory(
            repo, 'bad-parent', [], root_revision='bad-parent')
        self.add_revision(repo, 'bad-parent', inv, [])
        
        inv = self.make_one_file_inventory(
            repo, 'good-parent', ['bad-parent'])
        self.add_revision(repo, 'good-parent', inv, ['bad-parent'])
        
        inv = self.make_one_file_inventory(
            repo, 'broken-revision', ['good-parent', 'bad-parent'])
        self.add_revision(repo, 'broken-revision', inv, ['good-parent'])

    def test_too_many_parents(self):
        repo = self.make_repository_using_factory(
            self.too_many_parents_factory)
        self.require_text_parent_corruption(repo)
        check_result = repo.check(['XXX ignored rev ids'])
        self.assertEqual(
            [('broken-revision', 'a-file-id',
              ['good-parent', 'bad-parent'], ['good-parent']),
            ],
            check_result.inconsistent_parents)

