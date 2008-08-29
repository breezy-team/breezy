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

"""Tests for pack repositories.

These tests are repeated for all pack-based repository formats.
"""

from cStringIO import StringIO
from stat import S_ISDIR

from bzrlib.index import GraphIndex, InMemoryGraphIndex
from bzrlib import (
    bzrdir,
    errors,
    inventory,
    progress,
    repository,
    revision as _mod_revision,
    symbol_versioning,
    tests,
    ui,
    upgrade,
    workingtree,
    )
from bzrlib.tests import (
    TestCase,
    TestCaseWithTransport,
    TestNotApplicable,
    TestSkipped,
    )
from bzrlib.transport import (
    fakenfs,
    get_transport,
    )


class TestPackRepository(TestCaseWithTransport):
    """Tests to be repeated across all pack-based formats.

    The following are populated from the test scenario:

    :ivar format_name: Registered name fo the format to test.
    :ivar format_string: On-disk format marker.
    :ivar format_supports_external_lookups: Boolean.
    """

    def get_format(self):
        return bzrdir.format_registry.make_bzrdir(self.format_name)

    def test_attribute__fetch_order(self):
        """Packs do not need ordered data retrieval."""
        format = self.get_format()
        repo = self.make_repository('.', format=format)
        self.assertEqual('unordered', repo._fetch_order)

    def test_attribute__fetch_uses_deltas(self):
        """Packs reuse deltas."""
        format = self.get_format()
        repo = self.make_repository('.', format=format)
        self.assertEqual(True, repo._fetch_uses_deltas)

    def test_disk_layout(self):
        format = self.get_format()
        repo = self.make_repository('.', format=format)
        # in case of side effects of locking.
        repo.lock_write()
        repo.unlock()
        t = repo.bzrdir.get_repository_transport(None)
        self.check_format(t)
        # XXX: no locks left when unlocked at the moment
        # self.assertEqualDiff('', t.get('lock').read())
        self.check_databases(t)

    def check_format(self, t):
        self.assertEqualDiff(
            self.format_string, # from scenario
            t.get('format').read())

    def assertHasNoKndx(self, t, knit_name):
        """Assert that knit_name has no index on t."""
        self.assertFalse(t.has(knit_name + '.kndx'))

    def assertHasNoKnit(self, t, knit_name):
        """Assert that knit_name exists on t."""
        # no default content
        self.assertFalse(t.has(knit_name + '.knit'))

    def check_databases(self, t):
        """check knit content for a repository."""
        # check conversion worked
        self.assertHasNoKndx(t, 'inventory')
        self.assertHasNoKnit(t, 'inventory')
        self.assertHasNoKndx(t, 'revisions')
        self.assertHasNoKnit(t, 'revisions')
        self.assertHasNoKndx(t, 'signatures')
        self.assertHasNoKnit(t, 'signatures')
        self.assertFalse(t.has('knits'))
        # revision-indexes file-container directory
        self.assertEqual([],
            list(GraphIndex(t, 'pack-names', None).iter_all_entries()))
        self.assertTrue(S_ISDIR(t.stat('packs').st_mode))
        self.assertTrue(S_ISDIR(t.stat('upload').st_mode))
        self.assertTrue(S_ISDIR(t.stat('indices').st_mode))
        self.assertTrue(S_ISDIR(t.stat('obsolete_packs').st_mode))

    def test_shared_disk_layout(self):
        format = self.get_format()
        repo = self.make_repository('.', shared=True, format=format)
        # we want:
        t = repo.bzrdir.get_repository_transport(None)
        self.check_format(t)
        # XXX: no locks left when unlocked at the moment
        # self.assertEqualDiff('', t.get('lock').read())
        # We should have a 'shared-storage' marker file.
        self.assertEqualDiff('', t.get('shared-storage').read())
        self.check_databases(t)

    def test_shared_no_tree_disk_layout(self):
        format = self.get_format()
        repo = self.make_repository('.', shared=True, format=format)
        repo.set_make_working_trees(False)
        # we want:
        t = repo.bzrdir.get_repository_transport(None)
        self.check_format(t)
        # XXX: no locks left when unlocked at the moment
        # self.assertEqualDiff('', t.get('lock').read())
        # We should have a 'shared-storage' marker file.
        self.assertEqualDiff('', t.get('shared-storage').read())
        # We should have a marker for the no-working-trees flag.
        self.assertEqualDiff('', t.get('no-working-trees').read())
        # The marker should go when we toggle the setting.
        repo.set_make_working_trees(True)
        self.assertFalse(t.has('no-working-trees'))
        self.check_databases(t)

    def test_adding_revision_creates_pack_indices(self):
        format = self.get_format()
        tree = self.make_branch_and_tree('.', format=format)
        trans = tree.branch.repository.bzrdir.get_repository_transport(None)
        self.assertEqual([],
            list(GraphIndex(trans, 'pack-names', None).iter_all_entries()))
        tree.commit('foobarbaz')
        index = GraphIndex(trans, 'pack-names', None)
        index_nodes = list(index.iter_all_entries())
        self.assertEqual(1, len(index_nodes))
        node = index_nodes[0]
        name = node[1][0]
        # the pack sizes should be listed in the index
        pack_value = node[2]
        sizes = [int(digits) for digits in pack_value.split(' ')]
        for size, suffix in zip(sizes, ['.rix', '.iix', '.tix', '.six']):
            stat = trans.stat('indices/%s%s' % (name, suffix))
            self.assertEqual(size, stat.st_size)

    def test_pulling_nothing_leads_to_no_new_names(self):
        format = self.get_format()
        tree1 = self.make_branch_and_tree('1', format=format)
        tree2 = self.make_branch_and_tree('2', format=format)
        tree1.branch.repository.fetch(tree2.branch.repository)
        trans = tree1.branch.repository.bzrdir.get_repository_transport(None)
        self.assertEqual([],
            list(GraphIndex(trans, 'pack-names', None).iter_all_entries()))

    def test_commit_across_pack_shape_boundary_autopacks(self):
        format = self.get_format()
        tree = self.make_branch_and_tree('.', format=format)
        trans = tree.branch.repository.bzrdir.get_repository_transport(None)
        # This test could be a little cheaper by replacing the packs
        # attribute on the repository to allow a different pack distribution
        # and max packs policy - so we are checking the policy is honoured
        # in the test. But for now 11 commits is not a big deal in a single
        # test.
        for x in range(9):
            tree.commit('commit %s' % x)
        # there should be 9 packs:
        index = GraphIndex(trans, 'pack-names', None)
        self.assertEqual(9, len(list(index.iter_all_entries())))
        # insert some files in obsolete_packs which should be removed by pack.
        trans.put_bytes('obsolete_packs/foo', '123')
        trans.put_bytes('obsolete_packs/bar', '321')
        # committing one more should coalesce to 1 of 10.
        tree.commit('commit triggering pack')
        index = GraphIndex(trans, 'pack-names', None)
        self.assertEqual(1, len(list(index.iter_all_entries())))
        # packing should not damage data
        tree = tree.bzrdir.open_workingtree()
        check_result = tree.branch.repository.check(
            [tree.branch.last_revision()])
        # We should have 50 (10x5) files in the obsolete_packs directory.
        obsolete_files = list(trans.list_dir('obsolete_packs'))
        self.assertFalse('foo' in obsolete_files)
        self.assertFalse('bar' in obsolete_files)
        self.assertEqual(50, len(obsolete_files))
        # XXX: Todo check packs obsoleted correctly - old packs and indices
        # in the obsolete_packs directory.
        large_pack_name = list(index.iter_all_entries())[0][1][0]
        # finally, committing again should not touch the large pack.
        tree.commit('commit not triggering pack')
        index = GraphIndex(trans, 'pack-names', None)
        self.assertEqual(2, len(list(index.iter_all_entries())))
        pack_names = [node[1][0] for node in index.iter_all_entries()]
        self.assertTrue(large_pack_name in pack_names)

    def test_fail_obsolete_deletion(self):
        # failing to delete obsolete packs is not fatal
        format = self.get_format()
        server = fakenfs.FakeNFSServer()
        server.setUp()
        self.addCleanup(server.tearDown)
        transport = get_transport(server.get_url())
        bzrdir = self.get_format().initialize_on_transport(transport)
        repo = bzrdir.create_repository()
        repo_transport = bzrdir.get_repository_transport(None)
        self.assertTrue(repo_transport.has('obsolete_packs'))
        # these files are in use by another client and typically can't be deleted
        repo_transport.put_bytes('obsolete_packs/.nfsblahblah', 'contents')
        repo._pack_collection._clear_obsolete_packs()
        self.assertTrue(repo_transport.has('obsolete_packs/.nfsblahblah'))

    def test_pack_after_two_commits_packs_everything(self):
        format = self.get_format()
        tree = self.make_branch_and_tree('.', format=format)
        trans = tree.branch.repository.bzrdir.get_repository_transport(None)
        tree.commit('start')
        tree.commit('more work')
        tree.branch.repository.pack()
        # there should be 1 pack:
        index = GraphIndex(trans, 'pack-names', None)
        self.assertEqual(1, len(list(index.iter_all_entries())))
        self.assertEqual(2, len(tree.branch.repository.all_revision_ids()))

    def test_pack_layout(self):
        format = self.get_format()
        tree = self.make_branch_and_tree('.', format=format)
        trans = tree.branch.repository.bzrdir.get_repository_transport(None)
        tree.commit('start', rev_id='1')
        tree.commit('more work', rev_id='2')
        tree.branch.repository.pack()
        tree.lock_read()
        self.addCleanup(tree.unlock)
        pack = tree.branch.repository._pack_collection.get_pack_by_name(
            tree.branch.repository._pack_collection.names()[0])
        # revision access tends to be tip->ancestor, so ordering that way on 
        # disk is a good idea.
        for _1, key, val, refs in pack.revision_index.iter_all_entries():
            if key == ('1',):
                pos_1 = int(val[1:].split()[0])
            else:
                pos_2 = int(val[1:].split()[0])
        self.assertTrue(pos_2 < pos_1)

    def test_pack_repositories_support_multiple_write_locks(self):
        format = self.get_format()
        self.make_repository('.', shared=True, format=format)
        r1 = repository.Repository.open('.')
        r2 = repository.Repository.open('.')
        r1.lock_write()
        self.addCleanup(r1.unlock)
        r2.lock_write()
        r2.unlock()

    def _add_text(self, repo, fileid):
        """Add a text to the repository within a write group."""
        repo.texts.add_lines((fileid, 'samplerev+'+fileid), [], [])

    def test_concurrent_writers_merge_new_packs(self):
        format = self.get_format()
        self.make_repository('.', shared=True, format=format)
        r1 = repository.Repository.open('.')
        r2 = repository.Repository.open('.')
        r1.lock_write()
        try:
            # access enough data to load the names list
            list(r1.all_revision_ids())
            r2.lock_write()
            try:
                # access enough data to load the names list
                list(r2.all_revision_ids())
                r1.start_write_group()
                try:
                    r2.start_write_group()
                    try:
                        self._add_text(r1, 'fileidr1')
                        self._add_text(r2, 'fileidr2')
                    except:
                        r2.abort_write_group()
                        raise
                except:
                    r1.abort_write_group()
                    raise
                # both r1 and r2 have open write groups with data in them
                # created while the other's write group was open.
                # Commit both which requires a merge to the pack-names.
                try:
                    r1.commit_write_group()
                except:
                    r1.abort_write_group()
                    r2.abort_write_group()
                    raise
                r2.commit_write_group()
                # tell r1 to reload from disk
                r1._pack_collection.reset()
                # Now both repositories should know about both names
                r1._pack_collection.ensure_loaded()
                r2._pack_collection.ensure_loaded()
                self.assertEqual(r1._pack_collection.names(), r2._pack_collection.names())
                self.assertEqual(2, len(r1._pack_collection.names()))
            finally:
                r2.unlock()
        finally:
            r1.unlock()

    def test_concurrent_writer_second_preserves_dropping_a_pack(self):
        format = self.get_format()
        self.make_repository('.', shared=True, format=format)
        r1 = repository.Repository.open('.')
        r2 = repository.Repository.open('.')
        # add a pack to drop
        r1.lock_write()
        try:
            r1.start_write_group()
            try:
                self._add_text(r1, 'fileidr1')
            except:
                r1.abort_write_group()
                raise
            else:
                r1.commit_write_group()
            r1._pack_collection.ensure_loaded()
            name_to_drop = r1._pack_collection.all_packs()[0].name
        finally:
            r1.unlock()
        r1.lock_write()
        try:
            # access enough data to load the names list
            list(r1.all_revision_ids())
            r2.lock_write()
            try:
                # access enough data to load the names list
                list(r2.all_revision_ids())
                r1._pack_collection.ensure_loaded()
                try:
                    r2.start_write_group()
                    try:
                        # in r1, drop the pack
                        r1._pack_collection._remove_pack_from_memory(
                            r1._pack_collection.get_pack_by_name(name_to_drop))
                        # in r2, add a pack
                        self._add_text(r2, 'fileidr2')
                    except:
                        r2.abort_write_group()
                        raise
                except:
                    r1._pack_collection.reset()
                    raise
                # r1 has a changed names list, and r2 an open write groups with
                # changes.
                # save r1, and then commit the r2 write group, which requires a
                # merge to the pack-names, which should not reinstate
                # name_to_drop
                try:
                    r1._pack_collection._save_pack_names()
                    r1._pack_collection.reset()
                except:
                    r2.abort_write_group()
                    raise
                try:
                    r2.commit_write_group()
                except:
                    r2.abort_write_group()
                    raise
                # Now both repositories should now about just one name.
                r1._pack_collection.ensure_loaded()
                r2._pack_collection.ensure_loaded()
                self.assertEqual(r1._pack_collection.names(), r2._pack_collection.names())
                self.assertEqual(1, len(r1._pack_collection.names()))
                self.assertFalse(name_to_drop in r1._pack_collection.names())
            finally:
                r2.unlock()
        finally:
            r1.unlock()

    def test_lock_write_does_not_physically_lock(self):
        repo = self.make_repository('.', format=self.get_format())
        repo.lock_write()
        self.addCleanup(repo.unlock)
        self.assertFalse(repo.get_physical_lock_status())

    def prepare_for_break_lock(self):
        # Setup the global ui factory state so that a break-lock method call
        # will find usable input in the input stream.
        old_factory = ui.ui_factory
        def restoreFactory():
            ui.ui_factory = old_factory
        self.addCleanup(restoreFactory)
        ui.ui_factory = ui.SilentUIFactory()
        ui.ui_factory.stdin = StringIO("y\n")

    def test_break_lock_breaks_physical_lock(self):
        repo = self.make_repository('.', format=self.get_format())
        repo._pack_collection.lock_names()
        repo2 = repository.Repository.open('.')
        self.assertTrue(repo.get_physical_lock_status())
        self.prepare_for_break_lock()
        repo2.break_lock()
        self.assertFalse(repo.get_physical_lock_status())

    def test_broken_physical_locks_error_on__unlock_names_lock(self):
        repo = self.make_repository('.', format=self.get_format())
        repo._pack_collection.lock_names()
        self.assertTrue(repo.get_physical_lock_status())
        repo2 = repository.Repository.open('.')
        self.prepare_for_break_lock()
        repo2.break_lock()
        self.assertRaises(errors.LockBroken, repo._pack_collection._unlock_names)

    def test_fetch_without_find_ghosts_ignores_ghosts(self):
        # we want two repositories at this point:
        # one with a revision that is a ghost in the other
        # repository.
        # 'ghost' is present in has_ghost, 'ghost' is absent in 'missing_ghost'.
        # 'references' is present in both repositories, and 'tip' is present
        # just in has_ghost.
        # has_ghost       missing_ghost
        #------------------------------
        # 'ghost'             -
        # 'references'    'references'
        # 'tip'               -
        # In this test we fetch 'tip' which should not fetch 'ghost'
        has_ghost = self.make_repository('has_ghost', format=self.get_format())
        missing_ghost = self.make_repository('missing_ghost',
            format=self.get_format())

        def add_commit(repo, revision_id, parent_ids):
            repo.lock_write()
            repo.start_write_group()
            inv = inventory.Inventory(revision_id=revision_id)
            inv.root.revision = revision_id
            root_id = inv.root.file_id
            sha1 = repo.add_inventory(revision_id, inv, [])
            repo.texts.add_lines((root_id, revision_id), [], [])
            rev = _mod_revision.Revision(timestamp=0,
                                         timezone=None,
                                         committer="Foo Bar <foo@example.com>",
                                         message="Message",
                                         inventory_sha1=sha1,
                                         revision_id=revision_id)
            rev.parent_ids = parent_ids
            repo.add_revision(revision_id, rev)
            repo.commit_write_group()
            repo.unlock()
        add_commit(has_ghost, 'ghost', [])
        add_commit(has_ghost, 'references', ['ghost'])
        add_commit(missing_ghost, 'references', ['ghost'])
        add_commit(has_ghost, 'tip', ['references'])
        missing_ghost.fetch(has_ghost, 'tip')
        # missing ghost now has tip and not ghost.
        rev = missing_ghost.get_revision('tip')
        inv = missing_ghost.get_inventory('tip')
        self.assertRaises(errors.NoSuchRevision,
            missing_ghost.get_revision, 'ghost')
        self.assertRaises(errors.NoSuchRevision,
            missing_ghost.get_inventory, 'ghost')

    def test_supports_external_lookups(self):
        repo = self.make_repository('.', format=self.get_format())
        self.assertEqual(self.format_supports_external_lookups,
            repo._format.supports_external_lookups)


class TestPackRepositoryStacking(TestCaseWithTransport):

    """Tests for stacking pack repositories"""

    def setUp(self):
        if not self.format_supports_external_lookups:
            raise TestNotApplicable("%r doesn't support stacking" 
                % (self.format_name,))
        super(TestPackRepositoryStacking, self).setUp()

    def get_format(self):
        return bzrdir.format_registry.make_bzrdir(self.format_name)

    def test_stack_checks_rich_root_compatibility(self):
        # early versions of the packing code relied on pack internals to
        # stack, but the current version should be able to stack on any
        # format.
        #
        # TODO: Possibly this should be run per-repository-format and raise
        # TestNotApplicable on formats that don't support stacking. -- mbp
        # 20080729
        repo = self.make_repository('repo', format=self.get_format())
        if repo.supports_rich_root():
            # can only stack on repositories that have compatible internal
            # metadata
            if getattr(repo._format, 'supports_tree_reference', False):
                matching_format_name = 'pack-0.92-subtree'
            else:
                matching_format_name = 'rich-root-pack'
            mismatching_format_name = 'pack-0.92'
        else:
            matching_format_name = 'pack-0.92'
            mismatching_format_name = 'pack-0.92-subtree'
        base = self.make_repository('base', format=matching_format_name)
        repo.add_fallback_repository(base)
        # you can't stack on something with incompatible data
        bad_repo = self.make_repository('mismatch',
            format=mismatching_format_name)
        e = self.assertRaises(errors.IncompatibleRepositories,
            repo.add_fallback_repository, bad_repo)
        self.assertContainsRe(str(e),
            r'(?m)KnitPackRepository.*/mismatch/.*\nis not compatible with\n'
            r'KnitPackRepository.*/repo/.*\n'
            r'different rich-root support')

    def test_stack_checks_serializers_compatibility(self):
        repo = self.make_repository('repo', format=self.get_format())
        if getattr(repo._format, 'supports_tree_reference', False):
            # can only stack on repositories that have compatible internal
            # metadata
            matching_format_name = 'pack-0.92-subtree'
            mismatching_format_name = 'rich-root-pack'
        else:
            if repo.supports_rich_root():
                matching_format_name = 'rich-root-pack'
                mismatching_format_name = 'pack-0.92-subtree'
            else:
                raise TestNotApplicable('No formats use non-v5 serializer'
                    ' without having rich-root also set')
        base = self.make_repository('base', format=matching_format_name)
        repo.add_fallback_repository(base)
        # you can't stack on something with incompatible data
        bad_repo = self.make_repository('mismatch',
            format=mismatching_format_name)
        e = self.assertRaises(errors.IncompatibleRepositories,
            repo.add_fallback_repository, bad_repo)
        self.assertContainsRe(str(e),
            r'(?m)KnitPackRepository.*/mismatch/.*\nis not compatible with\n'
            r'KnitPackRepository.*/repo/.*\n'
            r'different serializers')

    def test_adding_pack_does_not_record_pack_names_from_other_repositories(self):
        base = self.make_branch_and_tree('base', format=self.get_format())
        base.commit('foo')
        referencing = self.make_branch_and_tree('repo', format=self.get_format())
        referencing.branch.repository.add_fallback_repository(base.branch.repository)
        referencing.commit('bar')
        new_instance = referencing.bzrdir.open_repository()
        new_instance.lock_read()
        self.addCleanup(new_instance.unlock)
        new_instance._pack_collection.ensure_loaded()
        self.assertEqual(1, len(new_instance._pack_collection.all_packs()))

    def test_autopack_only_considers_main_repo_packs(self):
        base = self.make_branch_and_tree('base', format=self.get_format())
        base.commit('foo')
        tree = self.make_branch_and_tree('repo', format=self.get_format())
        tree.branch.repository.add_fallback_repository(base.branch.repository)
        trans = tree.branch.repository.bzrdir.get_repository_transport(None)
        # This test could be a little cheaper by replacing the packs
        # attribute on the repository to allow a different pack distribution
        # and max packs policy - so we are checking the policy is honoured
        # in the test. But for now 11 commits is not a big deal in a single
        # test.
        for x in range(9):
            tree.commit('commit %s' % x)
        # there should be 9 packs:
        index = GraphIndex(trans, 'pack-names', None)
        self.assertEqual(9, len(list(index.iter_all_entries())))
        # committing one more should coalesce to 1 of 10.
        tree.commit('commit triggering pack')
        index = GraphIndex(trans, 'pack-names', None)
        self.assertEqual(1, len(list(index.iter_all_entries())))
        # packing should not damage data
        tree = tree.bzrdir.open_workingtree()
        check_result = tree.branch.repository.check(
            [tree.branch.last_revision()])
        # We should have 50 (10x5) files in the obsolete_packs directory.
        obsolete_files = list(trans.list_dir('obsolete_packs'))
        self.assertFalse('foo' in obsolete_files)
        self.assertFalse('bar' in obsolete_files)
        self.assertEqual(50, len(obsolete_files))
        # XXX: Todo check packs obsoleted correctly - old packs and indices
        # in the obsolete_packs directory.
        large_pack_name = list(index.iter_all_entries())[0][1][0]
        # finally, committing again should not touch the large pack.
        tree.commit('commit not triggering pack')
        index = GraphIndex(trans, 'pack-names', None)
        self.assertEqual(2, len(list(index.iter_all_entries())))
        pack_names = [node[1][0] for node in index.iter_all_entries()]
        self.assertTrue(large_pack_name in pack_names)


def load_tests(basic_tests, module, test_loader):
    # these give the bzrdir canned format name, and the repository on-disk
    # format string
    scenarios_params = [
         dict(format_name='pack-0.92',
              format_string="Bazaar pack repository format 1 (needs bzr 0.92)\n",
              format_supports_external_lookups=False),
         dict(format_name='pack-0.92-subtree',
              format_string="Bazaar pack repository format 1 "
              "with subtree support (needs bzr 0.92)\n",
              format_supports_external_lookups=False),
         dict(format_name='1.6',
              format_string="Bazaar RepositoryFormatKnitPack5 (bzr 1.6)\n",
              format_supports_external_lookups=True),
         dict(format_name='1.6.1-rich-root',
              format_string="Bazaar RepositoryFormatKnitPack5RichRoot "
                  "(bzr 1.6.1)\n",
              format_supports_external_lookups=True),
         dict(format_name='development0',
              format_string="Bazaar development format 0 "
                  "(needs bzr.dev from before 1.3)\n",
              format_supports_external_lookups=False),
         dict(format_name='development0-subtree',
              format_string="Bazaar development format 0 "
                  "with subtree support (needs bzr.dev from before 1.3)\n",
              format_supports_external_lookups=False),
         dict(format_name='development',
              format_string="Bazaar development format 1 "
                  "(needs bzr.dev from before 1.6)\n",
              format_supports_external_lookups=True),
         dict(format_name='development-subtree',
              format_string="Bazaar development format 1 "
                  "with subtree support (needs bzr.dev from before 1.6)\n",
              format_supports_external_lookups=True),
         ]
    adapter = tests.TestScenarioApplier()
    # name of the scenario is the format name
    adapter.scenarios = [(s['format_name'], s) for s in scenarios_params]
    suite = tests.TestSuite()
    tests.adapt_tests(basic_tests, adapter, suite)
    return suite
