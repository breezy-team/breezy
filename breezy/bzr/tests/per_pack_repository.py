# Copyright (C) 2008-2011 Canonical Ltd
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

"""Tests for pack repositories.

These tests are repeated for all pack-based repository formats.
"""

from stat import S_ISDIR

from ... import controldir, errors, gpg, osutils, repository, tests, transport, ui
from ... import revision as _mod_revision
from ...tests import TestCaseWithTransport, TestNotApplicable, test_server
from ...transport import memory
from .. import inventory
from ..btree_index import BTreeGraphIndex
from ..groupcompress_repo import RepositoryFormat2a
from ..index import GraphIndex
from ..smart import client


class TestPackRepository(TestCaseWithTransport):
    """Tests to be repeated across all pack-based formats.

    The following are populated from the test scenario:

    :ivar format_name: Registered name fo the format to test.
    :ivar format_string: On-disk format marker.
    :ivar format_supports_external_lookups: Boolean.
    """

    def get_format(self):
        return controldir.format_registry.make_controldir(self.format_name)

    def test_attribute__fetch_order(self):
        """Packs do not need ordered data retrieval."""
        format = self.get_format()
        repo = self.make_repository(".", format=format)
        self.assertEqual("unordered", repo._format._fetch_order)

    def test_attribute__fetch_uses_deltas(self):
        """Packs reuse deltas."""
        format = self.get_format()
        repo = self.make_repository(".", format=format)
        if isinstance(format.repository_format, RepositoryFormat2a):
            # TODO: This is currently a workaround. CHK format repositories
            #       ignore the 'deltas' flag, but during conversions, we can't
            #       do unordered delta fetches. Remove this clause once we
            #       improve the inter-format fetching.
            self.assertEqual(False, repo._format._fetch_uses_deltas)
        else:
            self.assertEqual(True, repo._format._fetch_uses_deltas)

    def test_disk_layout(self):
        format = self.get_format()
        repo = self.make_repository(".", format=format)
        # in case of side effects of locking.
        repo.lock_write()
        repo.unlock()
        t = repo.controldir.get_repository_transport(None)
        self.check_format(t)
        # XXX: no locks left when unlocked at the moment
        # self.assertEqualDiff('', t.get('lock').read())
        self.check_databases(t)

    def check_format(self, t):
        with t.get("format") as f:
            self.assertEqualDiff(
                self.format_string.encode("ascii"),  # from scenario
                f.read(),
            )

    def assertHasNoKndx(self, t, knit_name):
        """Assert that knit_name has no index on t."""
        self.assertFalse(t.has(knit_name + ".kndx"))

    def assertHasNoKnit(self, t, knit_name):
        """Assert that knit_name exists on t."""
        # no default content
        self.assertFalse(t.has(knit_name + ".knit"))

    def check_databases(self, t):
        """Check knit content for a repository."""
        # check conversion worked
        self.assertHasNoKndx(t, "inventory")
        self.assertHasNoKnit(t, "inventory")
        self.assertHasNoKndx(t, "revisions")
        self.assertHasNoKnit(t, "revisions")
        self.assertHasNoKndx(t, "signatures")
        self.assertHasNoKnit(t, "signatures")
        self.assertFalse(t.has("knits"))
        # revision-indexes file-container directory
        self.assertEqual(
            [], list(self.index_class(t, "pack-names", None).iter_all_entries())
        )
        self.assertTrue(S_ISDIR(t.stat("packs").st_mode))
        self.assertTrue(S_ISDIR(t.stat("upload").st_mode))
        self.assertTrue(S_ISDIR(t.stat("indices").st_mode))
        self.assertTrue(S_ISDIR(t.stat("obsolete_packs").st_mode))

    def test_shared_disk_layout(self):
        format = self.get_format()
        repo = self.make_repository(".", shared=True, format=format)
        # we want:
        t = repo.controldir.get_repository_transport(None)
        self.check_format(t)
        # XXX: no locks left when unlocked at the moment
        # self.assertEqualDiff('', t.get('lock').read())
        # We should have a 'shared-storage' marker file.
        with t.get("shared-storage") as f:
            self.assertEqualDiff(b"", f.read())
        self.check_databases(t)

    def test_shared_no_tree_disk_layout(self):
        format = self.get_format()
        repo = self.make_repository(".", shared=True, format=format)
        repo.set_make_working_trees(False)
        # we want:
        t = repo.controldir.get_repository_transport(None)
        self.check_format(t)
        # XXX: no locks left when unlocked at the moment
        # self.assertEqualDiff('', t.get('lock').read())
        # We should have a 'shared-storage' marker file.
        with t.get("shared-storage") as f:
            self.assertEqualDiff(b"", f.read())
        # We should have a marker for the no-working-trees flag.
        with t.get("no-working-trees") as f:
            self.assertEqualDiff(b"", f.read())
        # The marker should go when we toggle the setting.
        repo.set_make_working_trees(True)
        self.assertFalse(t.has("no-working-trees"))
        self.check_databases(t)

    def test_adding_revision_creates_pack_indices(self):
        format = self.get_format()
        tree = self.make_branch_and_tree(".", format=format)
        trans = tree.branch.repository.controldir.get_repository_transport(None)
        self.assertEqual(
            [], list(self.index_class(trans, "pack-names", None).iter_all_entries())
        )
        tree.commit("foobarbaz")
        index = self.index_class(trans, "pack-names", None)
        index_nodes = list(index.iter_all_entries())
        self.assertEqual(1, len(index_nodes))
        node = index_nodes[0]
        name = node[1][0]
        # the pack sizes should be listed in the index
        pack_value = node[2]
        sizes = [int(digits) for digits in pack_value.split(b" ")]
        for size, suffix in zip(sizes, [".rix", ".iix", ".tix", ".six"]):
            stat = trans.stat("indices/{}{}".format(name.decode("ascii"), suffix))
            self.assertEqual(size, stat.st_size)

    def test_pulling_nothing_leads_to_no_new_names(self):
        format = self.get_format()
        tree1 = self.make_branch_and_tree("1", format=format)
        tree2 = self.make_branch_and_tree("2", format=format)
        tree1.branch.repository.fetch(tree2.branch.repository)
        trans = tree1.branch.repository.controldir.get_repository_transport(None)
        self.assertEqual(
            [], list(self.index_class(trans, "pack-names", None).iter_all_entries())
        )

    def test_commit_across_pack_shape_boundary_autopacks(self):
        format = self.get_format()
        tree = self.make_branch_and_tree(".", format=format)
        trans = tree.branch.repository.controldir.get_repository_transport(None)
        # This test could be a little cheaper by replacing the packs
        # attribute on the repository to allow a different pack distribution
        # and max packs policy - so we are checking the policy is honoured
        # in the test. But for now 11 commits is not a big deal in a single
        # test.
        for x in range(9):
            tree.commit("commit {}".format(x))
        # there should be 9 packs:
        index = self.index_class(trans, "pack-names", None)
        self.assertEqual(9, len(list(index.iter_all_entries())))
        # insert some files in obsolete_packs which should be removed by pack.
        trans.put_bytes("obsolete_packs/foo", b"123")
        trans.put_bytes("obsolete_packs/bar", b"321")
        # committing one more should coalesce to 1 of 10.
        tree.commit("commit triggering pack")
        index = self.index_class(trans, "pack-names", None)
        self.assertEqual(1, len(list(index.iter_all_entries())))
        # packing should not damage data
        tree = tree.controldir.open_workingtree()
        tree.branch.repository.check([tree.branch.last_revision()])
        nb_files = 5  # .pack, .rix, .iix, .tix, .six
        if tree.branch.repository._format.supports_chks:
            nb_files += 1  # .cix
        # We should have 10 x nb_files files in the obsolete_packs directory.
        obsolete_files = list(trans.list_dir("obsolete_packs"))
        self.assertFalse("foo" in obsolete_files)
        self.assertFalse("bar" in obsolete_files)
        self.assertEqual(10 * nb_files, len(obsolete_files))
        # XXX: Todo check packs obsoleted correctly - old packs and indices
        # in the obsolete_packs directory.
        large_pack_name = list(index.iter_all_entries())[0][1][0]
        # finally, committing again should not touch the large pack.
        tree.commit("commit not triggering pack")
        index = self.index_class(trans, "pack-names", None)
        self.assertEqual(2, len(list(index.iter_all_entries())))
        pack_names = [node[1][0] for node in index.iter_all_entries()]
        self.assertTrue(large_pack_name in pack_names)

    def test_commit_write_group_returns_new_pack_names(self):
        # This test doesn't need real disk.
        self.vfs_transport_factory = memory.MemoryServer
        format = self.get_format()
        repo = self.make_repository("foo", format=format)
        with repo.lock_write():
            # All current pack repository styles autopack at 10 revisions; and
            # autopack as well as regular commit write group needs to return
            # the new pack name. Looping is a little ugly, but we don't have a
            # clean way to test both the autopack logic and the normal code
            # path without doing this loop.
            for pos in range(10):
                revid = b"%d" % pos
                repo.start_write_group()
                try:
                    inv = inventory.Inventory(revision_id=revid)
                    inv.root.revision = revid
                    repo.texts.add_lines((inv.root.file_id, revid), [], [])
                    rev = _mod_revision.Revision(
                        timestamp=0,
                        timezone=None,
                        committer="Foo Bar <foo@example.com>",
                        message="Message",
                        revision_id=revid,
                    )
                    rev.parent_ids = ()
                    repo.add_revision(revid, rev, inv=inv)
                except:
                    repo.abort_write_group()
                    raise
                else:
                    old_names = set(repo._pack_collection._names)
                    result = repo.commit_write_group()
                    cur_names = set(repo._pack_collection._names)
                    # In this test, len(result) is always 1, so unordered is ok
                    new_names = list(cur_names - old_names)
                    self.assertEqual(new_names, result)

    def test_fail_obsolete_deletion(self):
        # failing to delete obsolete packs is not fatal
        self.get_format()
        server = test_server.FakeNFSServer()
        self.start_server(server)
        t = transport.get_transport_from_url(server.get_url())
        bzrdir = self.get_format().initialize_on_transport(t)
        repo = bzrdir.create_repository()
        repo_transport = bzrdir.get_repository_transport(None)
        self.assertTrue(repo_transport.has("obsolete_packs"))
        # these files are in use by another client and typically can't be deleted
        repo_transport.put_bytes("obsolete_packs/.nfsblahblah", b"contents")
        repo._pack_collection._clear_obsolete_packs()
        self.assertTrue(repo_transport.has("obsolete_packs/.nfsblahblah"))

    def test_pack_collection_sets_sibling_indices(self):
        """The CombinedGraphIndex objects in the pack collection are all
        siblings of each other, so that search-order reorderings will be copied
        to each other.
        """
        repo = self.make_repository("repo")
        pack_coll = repo._pack_collection
        indices = {
            pack_coll.revision_index,
            pack_coll.inventory_index,
            pack_coll.text_index,
            pack_coll.signature_index,
        }
        if pack_coll.chk_index is not None:
            indices.add(pack_coll.chk_index)
        combined_indices = {idx.combined_index for idx in indices}
        for combined_index in combined_indices:
            self.assertEqual(
                combined_indices.difference([combined_index]),
                combined_index._sibling_indices,
            )

    def test_pack_with_signatures(self):
        format = self.get_format()
        tree = self.make_branch_and_tree(".", format=format)
        trans = tree.branch.repository.controldir.get_repository_transport(None)
        revid1 = tree.commit("start")
        revid2 = tree.commit("more work")
        strategy = gpg.LoopbackGPGStrategy(None)
        repo = tree.branch.repository
        self.addCleanup(repo.lock_write().unlock)
        repo.start_write_group()
        repo.sign_revision(revid1, strategy)
        repo.commit_write_group()
        repo.start_write_group()
        repo.sign_revision(revid2, strategy)
        repo.commit_write_group()
        tree.branch.repository.pack()
        # there should be 1 pack:
        index = self.index_class(trans, "pack-names", None)
        self.assertEqual(1, len(list(index.iter_all_entries())))
        self.assertEqual(2, len(tree.branch.repository.all_revision_ids()))

    def test_pack_after_two_commits_packs_everything(self):
        format = self.get_format()
        tree = self.make_branch_and_tree(".", format=format)
        trans = tree.branch.repository.controldir.get_repository_transport(None)
        tree.commit("start")
        tree.commit("more work")
        tree.branch.repository.pack()
        # there should be 1 pack:
        index = self.index_class(trans, "pack-names", None)
        self.assertEqual(1, len(list(index.iter_all_entries())))
        self.assertEqual(2, len(tree.branch.repository.all_revision_ids()))

    def test_pack_preserves_all_inventories(self):
        # This is related to bug:
        #   https://bugs.launchpad.net/bzr/+bug/412198
        # Stacked repositories need to keep the inventory for parents, even
        # after a pack operation. However, it is harder to test that, then just
        # test that all inventory texts are preserved.
        format = self.get_format()
        builder = self.make_branch_builder("source", format=format)
        builder.start_series()
        builder.build_snapshot(
            None, [("add", ("", b"root-id", "directory", None))], revision_id=b"A-id"
        )
        builder.build_snapshot(
            None,
            [("add", ("file", b"file-id", "file", b"B content\n"))],
            revision_id=b"B-id",
        )
        builder.build_snapshot(
            None, [("modify", ("file", b"C content\n"))], revision_id=b"C-id"
        )
        builder.finish_series()
        b = builder.get_branch()
        b.lock_read()
        self.addCleanup(b.unlock)
        repo = self.make_repository("repo", shared=True, format=format)
        repo.lock_write()
        self.addCleanup(repo.unlock)
        repo.fetch(b.repository, revision_id=b"B-id")
        inv = next(b.repository.iter_inventories([b"C-id"]))
        repo.start_write_group()
        repo.add_inventory(b"C-id", inv, [b"B-id"])
        repo.commit_write_group()
        self.assertEqual(
            [(b"A-id",), (b"B-id",), (b"C-id",)], sorted(repo.inventories.keys())
        )
        repo.pack()
        self.assertEqual(
            [(b"A-id",), (b"B-id",), (b"C-id",)], sorted(repo.inventories.keys())
        )
        # Content should be preserved as well
        self.assertEqual(inv, next(repo.iter_inventories([b"C-id"])))

    def test_pack_layout(self):
        # Test that the ordering of revisions in pack repositories is
        # tip->ancestor
        format = self.get_format()
        tree = self.make_branch_and_tree(".", format=format)
        tree.branch.repository.controldir.get_repository_transport(None)
        tree.commit("start", rev_id=b"1")
        tree.commit("more work", rev_id=b"2")
        tree.branch.repository.pack()
        tree.lock_read()
        self.addCleanup(tree.unlock)
        pack = tree.branch.repository._pack_collection.get_pack_by_name(
            tree.branch.repository._pack_collection.names()[0]
        )
        # revision access tends to be tip->ancestor, so ordering that way on
        # disk is a good idea.
        pos_1 = pos_2 = None
        for _1, key, val, _refs in pack.revision_index.iter_all_entries():
            if isinstance(format.repository_format, RepositoryFormat2a):
                # group_start, group_len, internal_start, internal_len
                pos = list(map(int, val.split()))
            else:
                # eol_flag, start, len
                pos = int(val[1:].split()[0])
            if key == (b"1",):
                pos_1 = pos
            else:
                pos_2 = pos
        self.assertTrue(
            pos_2 < pos_1, "rev 1 came before rev 2 {} > {}".format(pos_1, pos_2)
        )

    def test_pack_repositories_support_multiple_write_locks(self):
        format = self.get_format()
        self.make_repository(".", shared=True, format=format)
        r1 = repository.Repository.open(".")
        r2 = repository.Repository.open(".")
        r1.lock_write()
        self.addCleanup(r1.unlock)
        r2.lock_write()
        r2.unlock()

    def _add_text(self, repo, fileid):
        """Add a text to the repository within a write group."""
        repo.texts.add_lines(
            (fileid, b"samplerev+" + fileid), [], [b"smaplerev+" + fileid]
        )

    def test_concurrent_writers_merge_new_packs(self):
        format = self.get_format()
        self.make_repository(".", shared=True, format=format)
        r1 = repository.Repository.open(".")
        r2 = repository.Repository.open(".")
        with r1.lock_write():
            # access enough data to load the names list
            list(r1.all_revision_ids())
            with r2.lock_write():
                # access enough data to load the names list
                list(r2.all_revision_ids())
                r1.start_write_group()
                try:
                    r2.start_write_group()
                    try:
                        self._add_text(r1, b"fileidr1")
                        self._add_text(r2, b"fileidr2")
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
                self.assertEqual(
                    r1._pack_collection.names(), r2._pack_collection.names()
                )
                self.assertEqual(2, len(r1._pack_collection.names()))

    def test_concurrent_writer_second_preserves_dropping_a_pack(self):
        format = self.get_format()
        self.make_repository(".", shared=True, format=format)
        r1 = repository.Repository.open(".")
        r2 = repository.Repository.open(".")
        # add a pack to drop
        with r1.lock_write():
            with repository.WriteGroup(r1):
                self._add_text(r1, b"fileidr1")
            r1._pack_collection.ensure_loaded()
            name_to_drop = r1._pack_collection.all_packs()[0].name
        with r1.lock_write():
            # access enough data to load the names list
            list(r1.all_revision_ids())
            with r2.lock_write():
                # access enough data to load the names list
                list(r2.all_revision_ids())
                r1._pack_collection.ensure_loaded()
                try:
                    r2.start_write_group()
                    try:
                        # in r1, drop the pack
                        r1._pack_collection._remove_pack_from_memory(
                            r1._pack_collection.get_pack_by_name(name_to_drop)
                        )
                        # in r2, add a pack
                        self._add_text(r2, b"fileidr2")
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
                self.assertEqual(
                    r1._pack_collection.names(), r2._pack_collection.names()
                )
                self.assertEqual(1, len(r1._pack_collection.names()))
                self.assertFalse(name_to_drop in r1._pack_collection.names())

    def test_concurrent_pack_triggers_reload(self):
        # create 2 packs, which we will then collapse
        tree = self.make_branch_and_tree("tree")
        with tree.lock_write():
            rev1 = tree.commit("one")
            rev2 = tree.commit("two")
            r2 = repository.Repository.open("tree")
            with r2.lock_read():
                # Now r2 has read the pack-names file, but will need to reload
                # it after r1 has repacked
                tree.branch.repository.pack()
                self.assertEqual({rev2: (rev1,)}, r2.get_parent_map([rev2]))

    def test_concurrent_pack_during_get_record_reloads(self):
        tree = self.make_branch_and_tree("tree")
        with tree.lock_write():
            rev1 = tree.commit("one")
            rev2 = tree.commit("two")
            keys = [(rev1,), (rev2,)]
            r2 = repository.Repository.open("tree")
            with r2.lock_read():
                # At this point, we will start grabbing a record stream, and
                # trigger a repack mid-way
                packed = False
                result = {}
                record_stream = r2.revisions.get_record_stream(keys, "unordered", False)
                for record in record_stream:
                    result[record.key] = record
                    if not packed:
                        tree.branch.repository.pack()
                        packed = True
                # The first record will be found in the original location, but
                # after the pack, we have to reload to find the next record
                self.assertEqual(sorted(keys), sorted(result.keys()))

    def test_concurrent_pack_during_autopack(self):
        tree = self.make_branch_and_tree("tree")
        with tree.lock_write():
            for i in range(9):
                tree.commit(f"rev {i}")
            r2 = repository.Repository.open("tree")
            with r2.lock_write():
                # Monkey patch so that pack occurs while the other repo is
                # autopacking. This is slightly bad, but all current pack
                # repository implementations have a _pack_collection, and we
                # test that it gets triggered. So if a future format changes
                # things, the test will fail rather than succeed accidentally.
                autopack_count = [0]
                r1 = tree.branch.repository
                orig = r1._pack_collection.pack_distribution

                def trigger_during_auto(*args, **kwargs):
                    ret = orig(*args, **kwargs)
                    if not autopack_count[0]:
                        r2.pack()
                    autopack_count[0] += 1
                    return ret

                r1._pack_collection.pack_distribution = trigger_during_auto
                tree.commit("autopack-rev")
                # This triggers 2 autopacks. The first one causes r2.pack() to
                # fire, but r2 doesn't see the new pack file yet. The
                # autopack restarts and sees there are 2 files and there
                # should be only 1 for 10 commits. So it goes ahead and
                # finishes autopacking.
                self.assertEqual([2], autopack_count)

    def test_lock_write_does_not_physically_lock(self):
        repo = self.make_repository(".", format=self.get_format())
        repo.lock_write()
        self.addCleanup(repo.unlock)
        self.assertFalse(repo.get_physical_lock_status())

    def prepare_for_break_lock(self):
        # Setup the global ui factory state so that a break-lock method call
        # will find usable input in the input stream.
        ui.ui_factory = ui.CannedInputUIFactory([True])

    def test_break_lock_breaks_physical_lock(self):
        repo = self.make_repository(".", format=self.get_format())
        repo._pack_collection.lock_names()
        repo.control_files.leave_in_place()
        repo.unlock()
        repo2 = repository.Repository.open(".")
        self.assertTrue(repo.get_physical_lock_status())
        self.prepare_for_break_lock()
        repo2.break_lock()
        self.assertFalse(repo.get_physical_lock_status())

    def test_broken_physical_locks_error_on__unlock_names_lock(self):
        repo = self.make_repository(".", format=self.get_format())
        repo._pack_collection.lock_names()
        self.assertTrue(repo.get_physical_lock_status())
        repo2 = repository.Repository.open(".")
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
        # ------------------------------
        # 'ghost'             -
        # 'references'    'references'
        # 'tip'               -
        # In this test we fetch 'tip' which should not fetch 'ghost'
        has_ghost = self.make_repository("has_ghost", format=self.get_format())
        missing_ghost = self.make_repository("missing_ghost", format=self.get_format())

        def add_commit(repo, revision_id, parent_ids):
            repo.lock_write()
            repo.start_write_group()
            inv = inventory.Inventory(revision_id=revision_id)
            inv.root.revision = revision_id
            root_id = inv.root.file_id
            sha1 = repo.add_inventory(revision_id, inv, [])
            repo.texts.add_lines((root_id, revision_id), [], [])
            rev = _mod_revision.Revision(
                timestamp=0,
                timezone=None,
                committer="Foo Bar <foo@example.com>",
                message="Message",
                inventory_sha1=sha1,
                revision_id=revision_id,
            )
            rev.parent_ids = parent_ids
            repo.add_revision(revision_id, rev)
            repo.commit_write_group()
            repo.unlock()

        add_commit(has_ghost, b"ghost", [])
        add_commit(has_ghost, b"references", [b"ghost"])
        add_commit(missing_ghost, b"references", [b"ghost"])
        add_commit(has_ghost, b"tip", [b"references"])
        missing_ghost.fetch(has_ghost, b"tip")
        # missing ghost now has tip and not ghost.
        missing_ghost.get_revision(b"tip")
        missing_ghost.get_inventory(b"tip")
        self.assertRaises(errors.NoSuchRevision, missing_ghost.get_revision, b"ghost")
        self.assertRaises(errors.NoSuchRevision, missing_ghost.get_inventory, b"ghost")

    def make_write_ready_repo(self):
        format = self.get_format()
        if isinstance(format.repository_format, RepositoryFormat2a):
            raise TestNotApplicable("No missing compression parents")
        repo = self.make_repository(".", format=format)
        repo.lock_write()
        self.addCleanup(repo.unlock)
        repo.start_write_group()
        self.addCleanup(repo.abort_write_group)
        return repo

    def test_missing_inventories_compression_parent_prevents_commit(self):
        repo = self.make_write_ready_repo()
        key = ("junk",)
        repo.inventories._index._missing_compression_parents.add(key)
        self.assertRaises(errors.BzrCheckError, repo.commit_write_group)
        self.assertRaises(errors.BzrCheckError, repo.commit_write_group)

    def test_missing_revisions_compression_parent_prevents_commit(self):
        repo = self.make_write_ready_repo()
        key = ("junk",)
        repo.revisions._index._missing_compression_parents.add(key)
        self.assertRaises(errors.BzrCheckError, repo.commit_write_group)
        self.assertRaises(errors.BzrCheckError, repo.commit_write_group)

    def test_missing_signatures_compression_parent_prevents_commit(self):
        repo = self.make_write_ready_repo()
        key = ("junk",)
        repo.signatures._index._missing_compression_parents.add(key)
        self.assertRaises(errors.BzrCheckError, repo.commit_write_group)
        self.assertRaises(errors.BzrCheckError, repo.commit_write_group)

    def test_missing_text_compression_parent_prevents_commit(self):
        repo = self.make_write_ready_repo()
        key = ("some", "junk")
        repo.texts._index._missing_compression_parents.add(key)
        self.assertRaises(errors.BzrCheckError, repo.commit_write_group)
        self.assertRaises(errors.BzrCheckError, repo.commit_write_group)

    def test_supports_external_lookups(self):
        repo = self.make_repository(".", format=self.get_format())
        self.assertEqual(
            self.format_supports_external_lookups,
            repo._format.supports_external_lookups,
        )

    def _lock_write(self, write_lockable):
        """Lock write_lockable, add a cleanup and return the result.

        :param write_lockable: An object with a lock_write method.
        :return: The result of write_lockable.lock_write().
        """
        result = write_lockable.lock_write()
        self.addCleanup(result.unlock)
        return result

    def test_abort_write_group_does_not_raise_when_suppressed(self):
        """Similar to per_repository.test_write_group's test of the same name.

        Also requires that the exception is logged.
        """
        self.vfs_transport_factory = memory.MemoryServer
        repo = self.make_repository("repo", format=self.get_format())
        token = self._lock_write(repo).repository_token
        repo.start_write_group()
        # Damage the repository on the filesystem
        self.get_transport("").rename("repo", "foo")
        # abort_write_group will not raise an error
        self.assertEqual(None, repo.abort_write_group(suppress_errors=True))
        # But it does log an error
        log = self.get_log()
        self.assertContainsRe(log, "abort_write_group failed")
        self.assertContainsRe(log, r"INFO  brz: ERROR \(ignored\):")
        if token is not None:
            repo.leave_lock_in_place()

    def test_abort_write_group_does_raise_when_not_suppressed(self):
        self.vfs_transport_factory = memory.MemoryServer
        repo = self.make_repository("repo", format=self.get_format())
        token = self._lock_write(repo).repository_token
        repo.start_write_group()
        # Damage the repository on the filesystem
        self.get_transport("").rename("repo", "foo")
        # abort_write_group will not raise an error
        self.assertRaises(Exception, repo.abort_write_group)
        if token is not None:
            repo.leave_lock_in_place()

    def test_suspend_write_group(self):
        self.vfs_transport_factory = memory.MemoryServer
        repo = self.make_repository("repo", format=self.get_format())
        self._lock_write(repo).repository_token  # noqa: B018
        repo.start_write_group()
        repo.texts.add_lines((b"file-id", b"revid"), (), [b"lines"])
        wg_tokens = repo.suspend_write_group()
        expected_pack_name = wg_tokens[0] + ".pack"
        expected_names = [
            wg_tokens[0] + ext for ext in (".rix", ".iix", ".tix", ".six")
        ]
        if repo.chk_bytes is not None:
            expected_names.append(wg_tokens[0] + ".cix")
        expected_names.append(expected_pack_name)
        upload_transport = repo._pack_collection._upload_transport
        limbo_files = upload_transport.list_dir("")
        self.assertEqual(sorted(expected_names), sorted(limbo_files))
        md5 = osutils.md5(upload_transport.get_bytes(expected_pack_name))
        self.assertEqual(wg_tokens[0], md5.hexdigest())

    def test_resume_chk_bytes(self):
        self.vfs_transport_factory = memory.MemoryServer
        repo = self.make_repository("repo", format=self.get_format())
        if repo.chk_bytes is None:
            raise TestNotApplicable("no chk_bytes for this repository")
        self._lock_write(repo).repository_token  # noqa: B018
        repo.start_write_group()
        text = b"a bit of text\n"
        key = (b"sha1:" + osutils.sha_string(text),)
        repo.chk_bytes.add_lines(key, (), [text])
        wg_tokens = repo.suspend_write_group()
        same_repo = repo.controldir.open_repository()
        same_repo.lock_write()
        self.addCleanup(same_repo.unlock)
        same_repo.resume_write_group(wg_tokens)
        self.assertEqual([key], list(same_repo.chk_bytes.keys()))
        self.assertEqual(
            text,
            next(
                same_repo.chk_bytes.get_record_stream([key], "unordered", True)
            ).get_bytes_as("fulltext"),
        )
        same_repo.abort_write_group()
        self.assertEqual([], list(same_repo.chk_bytes.keys()))

    def test_resume_write_group_then_abort(self):
        # Create a repo, start a write group, insert some data, suspend.
        self.vfs_transport_factory = memory.MemoryServer
        repo = self.make_repository("repo", format=self.get_format())
        self._lock_write(repo).repository_token  # noqa: B018
        repo.start_write_group()
        text_key = (b"file-id", b"revid")
        repo.texts.add_lines(text_key, (), [b"lines"])
        wg_tokens = repo.suspend_write_group()
        # Get a fresh repository object for the repo on the filesystem.
        same_repo = repo.controldir.open_repository()
        # Resume
        same_repo.lock_write()
        self.addCleanup(same_repo.unlock)
        same_repo.resume_write_group(wg_tokens)
        same_repo.abort_write_group()
        self.assertEqual([], same_repo._pack_collection._upload_transport.list_dir(""))
        self.assertEqual([], same_repo._pack_collection._pack_transport.list_dir(""))

    def test_commit_resumed_write_group(self):
        self.vfs_transport_factory = memory.MemoryServer
        repo = self.make_repository("repo", format=self.get_format())
        self._lock_write(repo).repository_token  # noqa: B018
        repo.start_write_group()
        text_key = (b"file-id", b"revid")
        repo.texts.add_lines(text_key, (), [b"lines"])
        wg_tokens = repo.suspend_write_group()
        # Get a fresh repository object for the repo on the filesystem.
        same_repo = repo.controldir.open_repository()
        # Resume
        same_repo.lock_write()
        self.addCleanup(same_repo.unlock)
        same_repo.resume_write_group(wg_tokens)
        same_repo.commit_write_group()
        expected_pack_name = wg_tokens[0] + ".pack"
        expected_names = [
            wg_tokens[0] + ext for ext in (".rix", ".iix", ".tix", ".six")
        ]
        if repo.chk_bytes is not None:
            expected_names.append(wg_tokens[0] + ".cix")
        self.assertEqual([], same_repo._pack_collection._upload_transport.list_dir(""))
        index_names = repo._pack_collection._index_transport.list_dir("")
        self.assertEqual(sorted(expected_names), sorted(index_names))
        pack_names = repo._pack_collection._pack_transport.list_dir("")
        self.assertEqual([expected_pack_name], pack_names)

    def test_resume_malformed_token(self):
        self.vfs_transport_factory = memory.MemoryServer
        # Make a repository with a suspended write group
        repo = self.make_repository("repo", format=self.get_format())
        self._lock_write(repo).repository_token  # noqa: B018
        repo.start_write_group()
        text_key = (b"file-id", b"revid")
        repo.texts.add_lines(text_key, (), [b"lines"])
        wg_tokens = repo.suspend_write_group()
        # Make a new repository
        new_repo = self.make_repository("new_repo", format=self.get_format())
        self._lock_write(new_repo).repository_token  # noqa: B018
        hacked_wg_token = "../../../../repo/.bzr/repository/upload/" + wg_tokens[0]
        self.assertRaises(
            errors.UnresumableWriteGroup, new_repo.resume_write_group, [hacked_wg_token]
        )


class TestPackRepositoryStacking(TestCaseWithTransport):
    """Tests for stacking pack repositories."""

    def setUp(self):
        if not self.format_supports_external_lookups:
            raise TestNotApplicable("{!r} doesn't support stacking".format(self.format_name))
        super().setUp()

    def get_format(self):
        return controldir.format_registry.make_controldir(self.format_name)

    def test_stack_checks_rich_root_compatibility(self):
        # early versions of the packing code relied on pack internals to
        # stack, but the current version should be able to stack on any
        # format.
        #
        # TODO: Possibly this should be run per-repository-format and raise
        # TestNotApplicable on formats that don't support stacking. -- mbp
        # 20080729
        repo = self.make_repository("repo", format=self.get_format())
        if repo.supports_rich_root():
            # can only stack on repositories that have compatible internal
            # metadata
            if getattr(repo._format, "supports_tree_reference", False):
                matching_format_name = "2a"
            else:
                if repo._format.supports_chks:
                    matching_format_name = "2a"
                else:
                    matching_format_name = "rich-root-pack"
            mismatching_format_name = "pack-0.92"
        else:
            # We don't have a non-rich-root CHK format.
            if repo._format.supports_chks:
                raise AssertionError("no non-rich-root CHK formats known")
            else:
                matching_format_name = "pack-0.92"
            mismatching_format_name = "pack-0.92-subtree"
        base = self.make_repository("base", format=matching_format_name)
        repo.add_fallback_repository(base)
        # you can't stack on something with incompatible data
        bad_repo = self.make_repository("mismatch", format=mismatching_format_name)
        e = self.assertRaises(
            errors.IncompatibleRepositories, repo.add_fallback_repository, bad_repo
        )
        self.assertContainsRe(
            str(e),
            r"(?m)KnitPackRepository.*/mismatch/.*\nis not compatible with\n"
            r".*Repository.*/repo/.*\n"
            r"different rich-root support",
        )

    def test_stack_checks_serializers_compatibility(self):
        repo = self.make_repository("repo", format=self.get_format())
        if getattr(repo._format, "supports_tree_reference", False):
            # can only stack on repositories that have compatible internal
            # metadata
            matching_format_name = "2a"
            mismatching_format_name = "rich-root-pack"
        else:
            if repo.supports_rich_root():
                if repo._format.supports_chks:
                    matching_format_name = "2a"
                else:
                    matching_format_name = "rich-root-pack"
                mismatching_format_name = "pack-0.92-subtree"
            else:
                raise TestNotApplicable(
                    "No formats use non-v5 serializer without having rich-root also set"
                )
        base = self.make_repository("base", format=matching_format_name)
        repo.add_fallback_repository(base)
        # you can't stack on something with incompatible data
        bad_repo = self.make_repository("mismatch", format=mismatching_format_name)
        e = self.assertRaises(
            errors.IncompatibleRepositories, repo.add_fallback_repository, bad_repo
        )
        self.assertContainsRe(
            str(e),
            r"(?m)KnitPackRepository.*/mismatch/.*\nis not compatible with\n"
            r".*Repository.*/repo/.*\n"
            r"different serializers",
        )

    def test_adding_pack_does_not_record_pack_names_from_other_repositories(self):
        base = self.make_branch_and_tree("base", format=self.get_format())
        base.commit("foo")
        referencing = self.make_branch_and_tree("repo", format=self.get_format())
        referencing.branch.repository.add_fallback_repository(base.branch.repository)
        local_tree = referencing.branch.create_checkout("local")
        local_tree.commit("bar")
        new_instance = referencing.controldir.open_repository()
        new_instance.lock_read()
        self.addCleanup(new_instance.unlock)
        new_instance._pack_collection.ensure_loaded()
        self.assertEqual(1, len(new_instance._pack_collection.all_packs()))

    def test_autopack_only_considers_main_repo_packs(self):
        format = self.get_format()
        base = self.make_branch_and_tree("base", format=format)
        base.commit("foo")
        tree = self.make_branch_and_tree("repo", format=format)
        tree.branch.repository.add_fallback_repository(base.branch.repository)
        trans = tree.branch.repository.controldir.get_repository_transport(None)
        # This test could be a little cheaper by replacing the packs
        # attribute on the repository to allow a different pack distribution
        # and max packs policy - so we are checking the policy is honoured
        # in the test. But for now 11 commits is not a big deal in a single
        # test.
        local_tree = tree.branch.create_checkout("local")
        for x in range(9):
            local_tree.commit("commit {}".format(x))
        # there should be 9 packs:
        index = self.index_class(trans, "pack-names", None)
        self.assertEqual(9, len(list(index.iter_all_entries())))
        # committing one more should coalesce to 1 of 10.
        local_tree.commit("commit triggering pack")
        index = self.index_class(trans, "pack-names", None)
        self.assertEqual(1, len(list(index.iter_all_entries())))
        # packing should not damage data
        tree = tree.controldir.open_workingtree()
        tree.branch.repository.check([tree.branch.last_revision()])
        nb_files = 5  # .pack, .rix, .iix, .tix, .six
        if tree.branch.repository._format.supports_chks:
            nb_files += 1  # .cix
        # We should have 10 x nb_files files in the obsolete_packs directory.
        obsolete_files = list(trans.list_dir("obsolete_packs"))
        self.assertFalse("foo" in obsolete_files)
        self.assertFalse("bar" in obsolete_files)
        self.assertEqual(10 * nb_files, len(obsolete_files))
        # XXX: Todo check packs obsoleted correctly - old packs and indices
        # in the obsolete_packs directory.
        large_pack_name = list(index.iter_all_entries())[0][1][0]
        # finally, committing again should not touch the large pack.
        local_tree.commit("commit not triggering pack")
        index = self.index_class(trans, "pack-names", None)
        self.assertEqual(2, len(list(index.iter_all_entries())))
        pack_names = [node[1][0] for node in index.iter_all_entries()]
        self.assertTrue(large_pack_name in pack_names)


class TestKeyDependencies(TestCaseWithTransport):
    def get_format(self):
        return controldir.format_registry.make_controldir(self.format_name)

    def create_source_and_target(self):
        builder = self.make_branch_builder("source", format=self.get_format())
        builder.start_series()
        builder.build_snapshot(
            None, [("add", ("", b"root-id", "directory", None))], revision_id=b"A-id"
        )
        builder.build_snapshot(
            [b"A-id", b"ghost-id"],
            [],
            revision_id=b"B-id",
        )
        builder.finish_series()
        repo = self.make_repository("target", format=self.get_format())
        b = builder.get_branch()
        b.lock_read()
        self.addCleanup(b.unlock)
        repo.lock_write()
        self.addCleanup(repo.unlock)
        return b.repository, repo

    def test_key_dependencies_cleared_on_abort(self):
        source_repo, target_repo = self.create_source_and_target()
        target_repo.start_write_group()
        try:
            stream = source_repo.revisions.get_record_stream(
                [(b"B-id",)], "unordered", True
            )
            target_repo.revisions.insert_record_stream(stream)
            key_refs = target_repo.revisions._index._key_dependencies
            self.assertEqual([(b"B-id",)], sorted(key_refs.get_referrers()))
        finally:
            target_repo.abort_write_group()
        self.assertEqual([], sorted(key_refs.get_referrers()))

    def test_key_dependencies_cleared_on_suspend(self):
        source_repo, target_repo = self.create_source_and_target()
        target_repo.start_write_group()
        try:
            stream = source_repo.revisions.get_record_stream(
                [(b"B-id",)], "unordered", True
            )
            target_repo.revisions.insert_record_stream(stream)
            key_refs = target_repo.revisions._index._key_dependencies
            self.assertEqual([(b"B-id",)], sorted(key_refs.get_referrers()))
        finally:
            target_repo.suspend_write_group()
        self.assertEqual([], sorted(key_refs.get_referrers()))

    def test_key_dependencies_cleared_on_commit(self):
        source_repo, target_repo = self.create_source_and_target()
        target_repo.start_write_group()
        try:
            # Copy all texts, inventories, and chks so that nothing is missing
            # for revision B-id.
            for vf_name in ["texts", "chk_bytes", "inventories"]:
                source_vf = getattr(source_repo, vf_name, None)
                if source_vf is None:
                    continue
                target_vf = getattr(target_repo, vf_name)
                stream = source_vf.get_record_stream(
                    source_vf.keys(), "unordered", True
                )
                target_vf.insert_record_stream(stream)
            # Copy just revision B-id
            stream = source_repo.revisions.get_record_stream(
                [(b"B-id",)], "unordered", True
            )
            target_repo.revisions.insert_record_stream(stream)
            key_refs = target_repo.revisions._index._key_dependencies
            self.assertEqual([(b"B-id",)], sorted(key_refs.get_referrers()))
        finally:
            target_repo.commit_write_group()
        self.assertEqual([], sorted(key_refs.get_referrers()))


class TestSmartServerAutopack(TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        # Create a smart server that publishes whatever the backing VFS server
        # does.
        self.smart_server = test_server.SmartTCPServer_for_testing()
        self.start_server(self.smart_server, self.get_server())
        # Log all HPSS calls into self.hpss_calls.
        client._SmartClient.hooks.install_named_hook(
            "call", self.capture_hpss_call, None
        )
        self.hpss_calls = []

    def capture_hpss_call(self, params):
        self.hpss_calls.append(params.method)

    def get_format(self):
        return controldir.format_registry.make_controldir(self.format_name)

    def test_autopack_or_streaming_rpc_is_used_when_using_hpss(self):
        # Make local and remote repos
        format = self.get_format()
        tree = self.make_branch_and_tree("local", format=format)
        self.make_branch_and_tree("remote", format=format)
        remote_branch_url = self.smart_server.get_url() + "remote"
        remote_branch = controldir.ControlDir.open(remote_branch_url).open_branch()
        # Make 9 local revisions, and push them one at a time to the remote
        # repo to produce 9 pack files.
        for x in range(9):
            tree.commit("commit {}".format(x))
            tree.branch.push(remote_branch)
        # Make one more push to trigger an autopack
        self.hpss_calls = []
        tree.commit("commit triggering pack")
        tree.branch.push(remote_branch)
        autopack_calls = len(
            [call for call in self.hpss_calls if call == b"PackRepository.autopack"]
        )
        streaming_calls = len(
            [
                call
                for call in self.hpss_calls
                if call
                in (b"Repository.insert_stream", b"Repository.insert_stream_1.19")
            ]
        )
        if autopack_calls:
            # Non streaming server
            self.assertEqual(1, autopack_calls)
            self.assertEqual(0, streaming_calls)
        else:
            # Streaming was used, which autopacks on the remote end.
            self.assertEqual(0, autopack_calls)
            # NB: The 2 calls are because of the sanity check that the server
            # supports the verb (see remote.py:RemoteSink.insert_stream for
            # details).
            self.assertEqual(2, streaming_calls)


def load_tests(loader, basic_tests, pattern):
    # these give the bzrdir canned format name, and the repository on-disk
    # format string
    scenarios_params = [
        {
            "format_name": "pack-0.92",
            "format_string": "Bazaar pack repository format 1 (needs bzr 0.92)\n",
            "format_supports_external_lookups": False,
            "index_class": GraphIndex,
        },
        {
            "format_name": "pack-0.92-subtree",
            "format_string": "Bazaar pack repository format 1 "
            "with subtree support (needs bzr 0.92)\n",
            "format_supports_external_lookups": False,
            "index_class": GraphIndex,
        },
        {
            "format_name": "1.6",
            "format_string": "Bazaar RepositoryFormatKnitPack5 (bzr 1.6)\n",
            "format_supports_external_lookups": True,
            "index_class": GraphIndex,
        },
        {
            "format_name": "1.6.1-rich-root",
            "format_string": "Bazaar RepositoryFormatKnitPack5RichRoot (bzr 1.6.1)\n",
            "format_supports_external_lookups": True,
            "index_class": GraphIndex,
        },
        {
            "format_name": "1.9",
            "format_string": "Bazaar RepositoryFormatKnitPack6 (bzr 1.9)\n",
            "format_supports_external_lookups": True,
            "index_class": BTreeGraphIndex,
        },
        {
            "format_name": "1.9-rich-root",
            "format_string": "Bazaar RepositoryFormatKnitPack6RichRoot (bzr 1.9)\n",
            "format_supports_external_lookups": True,
            "index_class": BTreeGraphIndex,
        },
        {
            "format_name": "2a",
            "format_string": "Bazaar repository format 2a (needs bzr 1.16 or later)\n",
            "format_supports_external_lookups": True,
            "index_class": BTreeGraphIndex,
        },
    ]
    # name of the scenario is the format name
    scenarios = [(s["format_name"], s) for s in scenarios_params]
    return tests.multiply_tests(basic_tests, scenarios, loader.suiteClass())
