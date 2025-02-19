# Copyright (C) 2006-2012, 2016 Canonical Ltd
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

"""Tests for the Repository facility that are not interface tests.

For interface tests see tests/per_repository/*.py.

For concrete class tests see this file, and for storage formats tests
also see this file.
"""

from stat import S_ISDIR

import breezy
from breezy import (
    controldir,
    errors,
    osutils,
    repository,
    tests,
    transport,
    upgrade,
    workingtree,
)
from breezy import revision as _mod_revision
from breezy.bzr import (
    btree_index,
    bzrdir,
    groupcompress_repo,
    inventory,
    knitpack_repo,
    knitrepo,
    pack_repo,
    versionedfile,
    vf_repository,
    vf_search,
)
from breezy.bzr import repository as bzrrepository
from breezy.bzr.btree_index import BTreeBuilder, BTreeGraphIndex
from breezy.bzr.index import GraphIndex
from breezy.errors import UnknownFormatError
from breezy.repository import RepositoryFormat
from breezy.tests import TestCase, TestCaseWithTransport


class TestDefaultFormat(TestCase):
    def test_get_set_default_format(self):
        old_default = controldir.format_registry.get("default")
        old_default_help = controldir.format_registry.get_help("default")
        private_default = old_default().repository_format.__class__
        old_format = repository.format_registry.get_default()
        self.assertTrue(isinstance(old_format, private_default))

        def make_sample_bzrdir():
            my_bzrdir = bzrdir.BzrDirMetaFormat1()
            my_bzrdir.repository_format = SampleRepositoryFormat()
            return my_bzrdir

        controldir.format_registry.remove("default")
        controldir.format_registry.register("sample", make_sample_bzrdir, "")
        controldir.format_registry.set_default("sample")
        # creating a repository should now create an instrumented dir.
        try:
            # the default branch format is used by the meta dir format
            # which is not the default bzrdir format at this point
            dir = bzrdir.BzrDirMetaFormat1().initialize("memory:///")
            result = dir.create_repository()
            self.assertEqual(result, "A bzr repository dir")
        finally:
            controldir.format_registry.remove("default")
            controldir.format_registry.remove("sample")
            controldir.format_registry.register(
                "default", old_default, old_default_help
            )
        self.assertIsInstance(
            repository.format_registry.get_default(), old_format.__class__
        )


class SampleRepositoryFormat(bzrrepository.RepositoryFormatMetaDir):
    """A sample format

    this format is initializable, unsupported to aid in testing the
    open and open(unsupported=True) routines.
    """

    @classmethod
    def get_format_string(cls):
        """See RepositoryFormat.get_format_string()."""
        return b"Sample .bzr repository format."

    def initialize(self, a_controldir, shared=False):
        """Initialize a repository in a BzrDir"""
        t = a_controldir.get_repository_transport(self)
        t.put_bytes("format", self.get_format_string())
        return "A bzr repository dir"

    def is_supported(self):
        return False

    def open(self, a_controldir, _found=False):
        return "opened repository."


class SampleExtraRepositoryFormat(repository.RepositoryFormat):
    """A sample format that can not be used in a metadir"""

    def get_format_string(self):
        raise NotImplementedError


class TestRepositoryFormat(TestCaseWithTransport):
    """Tests for the Repository format detection used by the bzr meta dir facility.BzrBranchFormat facility."""

    def test_find_format(self):
        # is the right format object found for a repository?
        # create a branch with a few known format objects.
        # this is not quite the same as
        self.build_tree(["foo/", "bar/"])

        def check_format(format, url):
            dir = format._matchingcontroldir.initialize(url)
            format.initialize(dir)
            found_format = bzrrepository.RepositoryFormatMetaDir.find_format(dir)
            self.assertIsInstance(found_format, format.__class__)

        check_format(repository.format_registry.get_default(), "bar")

    def test_find_format_no_repository(self):
        dir = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        self.assertRaises(
            errors.NoRepositoryPresent,
            bzrrepository.RepositoryFormatMetaDir.find_format,
            dir,
        )

    def test_from_string(self):
        self.assertIsInstance(
            SampleRepositoryFormat.from_string(b"Sample .bzr repository format."),
            SampleRepositoryFormat,
        )
        self.assertRaises(
            AssertionError,
            SampleRepositoryFormat.from_string,
            b"Different .bzr repository format.",
        )

    def test_find_format_unknown_format(self):
        dir = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        SampleRepositoryFormat().initialize(dir)
        self.assertRaises(
            UnknownFormatError, bzrrepository.RepositoryFormatMetaDir.find_format, dir
        )

    def test_find_format_with_features(self):
        tree = self.make_branch_and_tree(".", format="2a")
        tree.branch.repository.update_feature_flags({b"name": b"necessity"})
        found_format = bzrrepository.RepositoryFormatMetaDir.find_format(
            tree.controldir
        )
        self.assertIsInstance(found_format, bzrrepository.RepositoryFormatMetaDir)
        self.assertEqual(found_format.features.get(b"name"), b"necessity")
        self.assertRaises(
            bzrdir.MissingFeature, found_format.check_support_status, True
        )
        self.addCleanup(
            bzrrepository.RepositoryFormatMetaDir.unregister_feature, b"name"
        )
        bzrrepository.RepositoryFormatMetaDir.register_feature(b"name")
        found_format.check_support_status(True)


class TestRepositoryFormatRegistry(TestCase):
    def setUp(self):
        super().setUp()
        self.registry = repository.RepositoryFormatRegistry()

    def test_register_unregister_format(self):
        format = SampleRepositoryFormat()
        self.registry.register(format)
        self.assertEqual(format, self.registry.get(b"Sample .bzr repository format."))
        self.registry.remove(format)
        self.assertRaises(
            KeyError, self.registry.get, b"Sample .bzr repository format."
        )

    def test_get_all(self):
        format = SampleRepositoryFormat()
        self.assertEqual([], self.registry._get_all())
        self.registry.register(format)
        self.assertEqual([format], self.registry._get_all())

    def test_register_extra(self):
        format = SampleExtraRepositoryFormat()
        self.assertEqual([], self.registry._get_all())
        self.registry.register_extra(format)
        self.assertEqual([format], self.registry._get_all())

    def test_register_extra_lazy(self):
        self.assertEqual([], self.registry._get_all())
        self.registry.register_extra_lazy(__name__, "SampleExtraRepositoryFormat")
        formats = self.registry._get_all()
        self.assertEqual(1, len(formats))
        self.assertIsInstance(formats[0], SampleExtraRepositoryFormat)


class TestFormatKnit1(TestCaseWithTransport):
    def test_attribute__fetch_order(self):
        """Knits need topological data insertion."""
        repo = self.make_repository(
            ".", format=controldir.format_registry.get("knit")()
        )
        self.assertEqual("topological", repo._format._fetch_order)

    def test_attribute__fetch_uses_deltas(self):
        """Knits reuse deltas."""
        repo = self.make_repository(
            ".", format=controldir.format_registry.get("knit")()
        )
        self.assertEqual(True, repo._format._fetch_uses_deltas)

    def test_disk_layout(self):
        control = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        repo = knitrepo.RepositoryFormatKnit1().initialize(control)
        # in case of side effects of locking.
        repo.lock_write()
        repo.unlock()
        # we want:
        # format 'Bazaar-NG Knit Repository Format 1'
        # lock: is a directory
        # inventory.weave == empty_weave
        # empty revision-store directory
        # empty weaves directory
        t = control.get_repository_transport(None)
        with t.get("format") as f:
            self.assertEqualDiff(b"Bazaar-NG Knit Repository Format 1", f.read())
        # XXX: no locks left when unlocked at the moment
        # self.assertEqualDiff('', t.get('lock').read())
        self.assertTrue(S_ISDIR(t.stat("knits").st_mode))
        self.check_knits(t)
        # Check per-file knits.
        control.create_branch()
        tree = control.create_workingtree()
        tree.add(["foo"], ["file"], [b"Nasty-IdC:"])
        tree.put_file_bytes_non_atomic("foo", b"")
        tree.commit("1st post", rev_id=b"foo")
        self.assertHasKnit(
            t, "knits/e8/%254easty-%2549d%2543%253a", b"\nfoo fulltext 0 81  :"
        )

    def assertHasKnit(self, t, knit_name, extra_content=b""):
        """Assert that knit_name exists on t."""
        with t.get(knit_name + ".kndx") as f:
            self.assertEqualDiff(b"# bzr knit index 8\n" + extra_content, f.read())

    def check_knits(self, t):
        """Check knit content for a repository."""
        self.assertHasKnit(t, "inventory")
        self.assertHasKnit(t, "revisions")
        self.assertHasKnit(t, "signatures")

    def test_shared_disk_layout(self):
        control = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        knitrepo.RepositoryFormatKnit1().initialize(control, shared=True)
        # we want:
        # format 'Bazaar-NG Knit Repository Format 1'
        # lock: is a directory
        # inventory.weave == empty_weave
        # empty revision-store directory
        # empty weaves directory
        # a 'shared-storage' marker file.
        t = control.get_repository_transport(None)
        with t.get("format") as f:
            self.assertEqualDiff(b"Bazaar-NG Knit Repository Format 1", f.read())
        # XXX: no locks left when unlocked at the moment
        # self.assertEqualDiff('', t.get('lock').read())
        with t.get("shared-storage") as f:
            self.assertEqualDiff(b"", f.read())
        self.assertTrue(S_ISDIR(t.stat("knits").st_mode))
        self.check_knits(t)

    def test_shared_no_tree_disk_layout(self):
        control = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        repo = knitrepo.RepositoryFormatKnit1().initialize(control, shared=True)
        repo.set_make_working_trees(False)
        # we want:
        # format 'Bazaar-NG Knit Repository Format 1'
        # lock ''
        # inventory.weave == empty_weave
        # empty revision-store directory
        # empty weaves directory
        # a 'shared-storage' marker file.
        t = control.get_repository_transport(None)
        with t.get("format") as f:
            self.assertEqualDiff(b"Bazaar-NG Knit Repository Format 1", f.read())
        # XXX: no locks left when unlocked at the moment
        # self.assertEqualDiff('', t.get('lock').read())
        with t.get("shared-storage") as f:
            self.assertEqualDiff(b"", f.read())
        with t.get("no-working-trees") as f:
            self.assertEqualDiff(b"", f.read())
        repo.set_make_working_trees(True)
        self.assertFalse(t.has("no-working-trees"))
        self.assertTrue(S_ISDIR(t.stat("knits").st_mode))
        self.check_knits(t)

    def test_deserialise_sets_root_revision(self):
        """We must have a inventory.root.revision

        Old versions of the XML5 serializer did not set the revision_id for
        the whole inventory. So we grab the one from the expected text. Which
        is valid when the api is not being abused.
        """
        repo = self.make_repository(
            ".", format=controldir.format_registry.get("knit")()
        )
        inv_xml = b'<inventory format="5">\n</inventory>\n'
        inv = repo._deserialise_inventory(b"test-rev-id", [inv_xml])
        self.assertEqual(b"test-rev-id", inv.root.revision)

    def test_deserialise_uses_global_revision_id(self):
        """If it is set, then we re-use the global revision id"""
        repo = self.make_repository(
            ".", format=controldir.format_registry.get("knit")()
        )
        inv_xml = b'<inventory format="5" revision_id="other-rev-id">\n</inventory>\n'
        # Arguably, the deserialise_inventory should detect a mismatch, and
        # raise an error, rather than silently using one revision_id over the
        # other.
        self.assertRaises(
            AssertionError, repo._deserialise_inventory, b"test-rev-id", [inv_xml]
        )
        inv = repo._deserialise_inventory(b"other-rev-id", [inv_xml])
        self.assertEqual(b"other-rev-id", inv.root.revision)

    def test_supports_external_lookups(self):
        repo = self.make_repository(
            ".", format=controldir.format_registry.get("knit")()
        )
        self.assertFalse(repo._format.supports_external_lookups)


class DummyRepository:
    """A dummy repository for testing."""

    _format = None
    _serializer = None

    def supports_rich_root(self):
        if self._format is not None:
            return self._format.rich_root_data
        return False

    def get_graph(self):
        raise NotImplementedError

    def get_parent_map(self, revision_ids):
        raise NotImplementedError


class InterDummy(repository.InterRepository):
    """An inter-repository optimised code path for DummyRepository.

    This is for use during testing where we use DummyRepository as repositories
    so that none of the default regsitered inter-repository classes will
    MATCH.
    """

    @staticmethod
    def is_compatible(repo_source, repo_target):
        """InterDummy is compatible with DummyRepository."""
        return isinstance(repo_source, DummyRepository) and isinstance(
            repo_target, DummyRepository
        )


class TestInterRepository(TestCaseWithTransport):
    def test_get_default_inter_repository(self):
        # test that the InterRepository.get(repo_a, repo_b) probes
        # for a inter_repo class where is_compatible(repo_a, repo_b) returns
        # true and returns a default inter_repo otherwise.
        # This also tests that the default registered optimised interrepository
        # classes do not barf inappropriately when a surprising repository type
        # is handed to them.
        dummy_a = DummyRepository()
        dummy_a._format = RepositoryFormat()
        dummy_a._format.supports_full_versioned_files = True
        dummy_a._format.rich_root_data = True
        dummy_b = DummyRepository()
        dummy_b._format = RepositoryFormat()
        dummy_b._format.supports_full_versioned_files = True
        dummy_b._format.rich_root_data = True
        self.assertGetsDefaultInterRepository(dummy_a, dummy_b)

    def assertGetsDefaultInterRepository(self, repo_a, repo_b):
        """Asserts that InterRepository.get(repo_a, repo_b) -> the default.

        The effective default is now InterSameDataRepository because there is
        no actual sane default in the presence of incompatible data models.
        """
        inter_repo = repository.InterRepository.get(repo_a, repo_b)
        self.assertEqual(vf_repository.InterSameDataRepository, inter_repo.__class__)
        self.assertEqual(repo_a, inter_repo.source)
        self.assertEqual(repo_b, inter_repo.target)

    def test_register_inter_repository_class(self):
        # test that a optimised code path provider - a
        # InterRepository subclass can be registered and unregistered
        # and that it is correctly selected when given a repository
        # pair that it returns true on for the is_compatible static method
        # check
        dummy_a = DummyRepository()
        dummy_a._format = RepositoryFormat()
        dummy_b = DummyRepository()
        dummy_b._format = RepositoryFormat()
        repo = self.make_repository(".")
        # hack dummies to look like repo somewhat.
        dummy_a._serializer = repo._serializer
        dummy_a._format.supports_tree_reference = repo._format.supports_tree_reference
        dummy_a._format.rich_root_data = repo._format.rich_root_data
        dummy_a._format.supports_full_versioned_files = (
            repo._format.supports_full_versioned_files
        )
        dummy_b._serializer = repo._serializer
        dummy_b._format.supports_tree_reference = repo._format.supports_tree_reference
        dummy_b._format.rich_root_data = repo._format.rich_root_data
        dummy_b._format.supports_full_versioned_files = (
            repo._format.supports_full_versioned_files
        )
        repository.InterRepository.register_optimiser(InterDummy)
        try:
            # we should get the default for something InterDummy returns False
            # to
            self.assertFalse(InterDummy.is_compatible(dummy_a, repo))
            self.assertGetsDefaultInterRepository(dummy_a, repo)
            # and we should get an InterDummy for a pair it 'likes'
            self.assertTrue(InterDummy.is_compatible(dummy_a, dummy_b))
            inter_repo = repository.InterRepository.get(dummy_a, dummy_b)
            self.assertEqual(InterDummy, inter_repo.__class__)
            self.assertEqual(dummy_a, inter_repo.source)
            self.assertEqual(dummy_b, inter_repo.target)
        finally:
            repository.InterRepository.unregister_optimiser(InterDummy)
        # now we should get the default InterRepository object again.
        self.assertGetsDefaultInterRepository(dummy_a, dummy_b)


class TestRepositoryFormat1(knitrepo.RepositoryFormatKnit1):
    @classmethod
    def get_format_string(cls):
        return b"Test Format 1"


class TestRepositoryFormat2(knitrepo.RepositoryFormatKnit1):
    @classmethod
    def get_format_string(cls):
        return b"Test Format 2"


class TestRepositoryConverter(TestCaseWithTransport):
    def test_convert_empty(self):
        source_format = TestRepositoryFormat1()
        target_format = TestRepositoryFormat2()
        repository.format_registry.register(source_format)
        self.addCleanup(repository.format_registry.remove, source_format)
        repository.format_registry.register(target_format)
        self.addCleanup(repository.format_registry.remove, target_format)
        t = self.get_transport()
        t.mkdir("repository")
        repo_dir = bzrdir.BzrDirMetaFormat1().initialize("repository")
        repo = TestRepositoryFormat1().initialize(repo_dir)
        converter = repository.CopyConverter(target_format)
        with breezy.ui.ui_factory.nested_progress_bar() as pb:
            converter.convert(repo, pb)
        repo = repo_dir.open_repository()
        self.assertTrue(isinstance(target_format, repo._format.__class__))


class TestRepositoryFormatKnit3(TestCaseWithTransport):
    def test_attribute__fetch_order(self):
        """Knits need topological data insertion."""
        format = bzrdir.BzrDirMetaFormat1()
        format.repository_format = knitrepo.RepositoryFormatKnit3()
        repo = self.make_repository(".", format=format)
        self.assertEqual("topological", repo._format._fetch_order)

    def test_attribute__fetch_uses_deltas(self):
        """Knits reuse deltas."""
        format = bzrdir.BzrDirMetaFormat1()
        format.repository_format = knitrepo.RepositoryFormatKnit3()
        repo = self.make_repository(".", format=format)
        self.assertEqual(True, repo._format._fetch_uses_deltas)

    def test_convert(self):
        """Ensure the upgrade adds weaves for roots"""
        format = bzrdir.BzrDirMetaFormat1()
        format.repository_format = knitrepo.RepositoryFormatKnit1()
        tree = self.make_branch_and_tree(".", format)
        tree.commit("Dull commit", rev_id=b"dull")
        revision_tree = tree.branch.repository.revision_tree(b"dull")
        with revision_tree.lock_read():
            self.assertRaises(transport.NoSuchFile, revision_tree.get_file_lines, "")
        format = bzrdir.BzrDirMetaFormat1()
        format.repository_format = knitrepo.RepositoryFormatKnit3()
        upgrade.Convert(".", format)
        tree = workingtree.WorkingTree.open(".")
        revision_tree = tree.branch.repository.revision_tree(b"dull")
        with revision_tree.lock_read():
            revision_tree.get_file_lines("")
        tree.commit("Another dull commit", rev_id=b"dull2")
        revision_tree = tree.branch.repository.revision_tree(b"dull2")
        revision_tree.lock_read()
        self.addCleanup(revision_tree.unlock)
        self.assertEqual(b"dull", revision_tree.get_file_revision(""))

    def test_supports_external_lookups(self):
        format = bzrdir.BzrDirMetaFormat1()
        format.repository_format = knitrepo.RepositoryFormatKnit3()
        repo = self.make_repository(".", format=format)
        self.assertFalse(repo._format.supports_external_lookups)


class Test2a(tests.TestCaseWithMemoryTransport):
    def test_chk_bytes_uses_custom_btree_parser(self):
        mt = self.make_branch_and_memory_tree("test", format="2a")
        mt.lock_write()
        self.addCleanup(mt.unlock)
        mt.add([""], [b"root-id"])
        mt.commit("first")
        index = mt.branch.repository.chk_bytes._index._graph_index._indices[0]
        self.assertEqual(btree_index._gcchk_factory, index._leaf_factory)
        # It should also work if we re-open the repo
        repo = mt.branch.repository.controldir.open_repository()
        repo.lock_read()
        self.addCleanup(repo.unlock)
        index = repo.chk_bytes._index._graph_index._indices[0]
        self.assertEqual(btree_index._gcchk_factory, index._leaf_factory)

    def test_fetch_combines_groups(self):
        builder = self.make_branch_builder("source", format="2a")
        builder.start_series()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"root-id", "directory", "")),
                ("add", ("file", b"file-id", "file", b"content\n")),
            ],
            revision_id=b"1",
        )
        builder.build_snapshot(
            [b"1"], [("modify", ("file", b"content-2\n"))], revision_id=b"2"
        )
        builder.finish_series()
        source = builder.get_branch()
        target = self.make_repository("target", format="2a")
        target.fetch(source.repository)
        target.lock_read()
        self.addCleanup(target.unlock)
        details = target.texts._index.get_build_details(
            [
                (
                    b"file-id",
                    b"1",
                ),
                (
                    b"file-id",
                    b"2",
                ),
            ]
        )
        file_1_details = details[(b"file-id", b"1")]
        file_2_details = details[(b"file-id", b"2")]
        # The index, and what to read off disk, should be the same for both
        # versions of the file.
        self.assertEqual(file_1_details[0][:3], file_2_details[0][:3])

    def test_format_pack_compresses_True(self):
        repo = self.make_repository("repo", format="2a")
        self.assertTrue(repo._format.pack_compresses)

    def test_inventories_use_chk_map_with_parent_base_dict(self):
        tree = self.make_branch_and_memory_tree("repo", format="2a")
        tree.lock_write()
        tree.add([""], ids=[b"TREE_ROOT"])
        revid = tree.commit("foo")
        tree.unlock()
        tree.lock_read()
        self.addCleanup(tree.unlock)
        inv = tree.branch.repository.get_inventory(revid)
        self.assertNotEqual(None, inv.parent_id_basename_to_file_id)
        inv.parent_id_basename_to_file_id._ensure_root()
        inv.id_to_entry._ensure_root()
        self.assertEqual(65536, inv.id_to_entry._root_node.maximum_size)
        self.assertEqual(
            65536, inv.parent_id_basename_to_file_id._root_node.maximum_size
        )

    def test_autopack_unchanged_chk_nodes(self):
        # at 20 unchanged commits, chk pages are packed that are split into
        # two groups such that the new pack being made doesn't have all its
        # pages in the source packs (though they are in the repository).
        # Use a memory backed repository, we don't need to hit disk for this
        tree = self.make_branch_and_memory_tree("tree", format="2a")
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.add([""], ids=[b"TREE_ROOT"])
        for pos in range(20):
            tree.commit(str(pos))

    def test_pack_with_hint(self):
        tree = self.make_branch_and_memory_tree("tree", format="2a")
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.add([""], ids=[b"TREE_ROOT"])
        # 1 commit to leave untouched
        tree.commit("1")
        to_keep = tree.branch.repository._pack_collection.names()
        # 2 to combine
        tree.commit("2")
        tree.commit("3")
        all = tree.branch.repository._pack_collection.names()
        combine = list(set(all) - set(to_keep))
        self.assertLength(3, all)
        self.assertLength(2, combine)
        tree.branch.repository.pack(hint=combine)
        final = tree.branch.repository._pack_collection.names()
        self.assertLength(2, final)
        self.assertFalse(combine[0] in final)
        self.assertFalse(combine[1] in final)
        self.assertSubset(to_keep, final)

    def test_stream_source_to_gc(self):
        source = self.make_repository("source", format="2a")
        target = self.make_repository("target", format="2a")
        stream = source._get_source(target._format)
        self.assertIsInstance(stream, groupcompress_repo.GroupCHKStreamSource)

    def test_stream_source_to_non_gc(self):
        source = self.make_repository("source", format="2a")
        target = self.make_repository("target", format="rich-root-pack")
        stream = source._get_source(target._format)
        # We don't want the child GroupCHKStreamSource
        self.assertIs(type(stream), vf_repository.StreamSource)

    def test_get_stream_for_missing_keys_includes_all_chk_refs(self):
        source_builder = self.make_branch_builder("source", format="2a")
        # We have to build a fairly large tree, so that we are sure the chk
        # pages will have split into multiple pages.
        entries = [("add", ("", b"a-root-id", "directory", None))]
        for i in "abcdefghijklmnopqrstuvwxyz123456789":
            for j in "abcdefghijklmnopqrstuvwxyz123456789":
                fname = i + j
                fid = fname.encode("utf-8") + b"-id"
                content = b"content for %s\n" % (fname.encode("utf-8"),)
                entries.append(("add", (fname, fid, "file", content)))
        source_builder.start_series()
        source_builder.build_snapshot(None, entries, revision_id=b"rev-1")
        # Now change a few of them, so we get a few new pages for the second
        # revision
        source_builder.build_snapshot(
            [b"rev-1"],
            [
                ("modify", ("aa", b"new content for aa-id\n")),
                ("modify", ("cc", b"new content for cc-id\n")),
                ("modify", ("zz", b"new content for zz-id\n")),
            ],
            revision_id=b"rev-2",
        )
        source_builder.finish_series()
        source_branch = source_builder.get_branch()
        source_branch.lock_read()
        self.addCleanup(source_branch.unlock)
        target = self.make_repository("target", format="2a")
        source = source_branch.repository._get_source(target._format)
        self.assertIsInstance(source, groupcompress_repo.GroupCHKStreamSource)

        # On a regular pass, getting the inventories and chk pages for rev-2
        # would only get the newly created chk pages
        search = vf_search.SearchResult({b"rev-2"}, {b"rev-1"}, 1, {b"rev-2"})
        simple_chk_records = set()
        for vf_name, substream in source.get_stream(search):
            if vf_name == "chk_bytes":
                for record in substream:
                    simple_chk_records.add(record.key)
            else:
                for _ in substream:
                    continue
        # 3 pages, the root (InternalNode), + 2 pages which actually changed
        self.assertEqual(
            {
                (b"sha1:91481f539e802c76542ea5e4c83ad416bf219f73",),
                (b"sha1:4ff91971043668583985aec83f4f0ab10a907d3f",),
                (b"sha1:81e7324507c5ca132eedaf2d8414ee4bb2226187",),
                (b"sha1:b101b7da280596c71a4540e9a1eeba8045985ee0",),
            },
            set(simple_chk_records),
        )
        # Now, when we do a similar call using 'get_stream_for_missing_keys'
        # we should get a much larger set of pages.
        missing = [("inventories", b"rev-2")]
        full_chk_records = set()
        for vf_name, substream in source.get_stream_for_missing_keys(missing):
            if vf_name == "inventories":
                for record in substream:
                    self.assertEqual((b"rev-2",), record.key)
            elif vf_name == "chk_bytes":
                for record in substream:
                    full_chk_records.add(record.key)
            else:
                self.fail("Should not be getting a stream of {}".format(vf_name))
        # We have 257 records now. This is because we have 1 root page, and 256
        # leaf pages in a complete listing.
        self.assertEqual(257, len(full_chk_records))
        self.assertSubset(simple_chk_records, full_chk_records)

    def test_inconsistency_fatal(self):
        repo = self.make_repository("repo", format="2a")
        self.assertTrue(repo.revisions._index._inconsistency_fatal)
        self.assertFalse(repo.texts._index._inconsistency_fatal)
        self.assertFalse(repo.inventories._index._inconsistency_fatal)
        self.assertFalse(repo.signatures._index._inconsistency_fatal)
        self.assertFalse(repo.chk_bytes._index._inconsistency_fatal)


class TestKnitPackStreamSource(tests.TestCaseWithMemoryTransport):
    def test_source_to_exact_pack_092(self):
        source = self.make_repository("source", format="pack-0.92")
        target = self.make_repository("target", format="pack-0.92")
        stream_source = source._get_source(target._format)
        self.assertIsInstance(stream_source, knitpack_repo.KnitPackStreamSource)

    def test_source_to_exact_pack_rich_root_pack(self):
        source = self.make_repository("source", format="rich-root-pack")
        target = self.make_repository("target", format="rich-root-pack")
        stream_source = source._get_source(target._format)
        self.assertIsInstance(stream_source, knitpack_repo.KnitPackStreamSource)

    def test_source_to_exact_pack_19(self):
        source = self.make_repository("source", format="1.9")
        target = self.make_repository("target", format="1.9")
        stream_source = source._get_source(target._format)
        self.assertIsInstance(stream_source, knitpack_repo.KnitPackStreamSource)

    def test_source_to_exact_pack_19_rich_root(self):
        source = self.make_repository("source", format="1.9-rich-root")
        target = self.make_repository("target", format="1.9-rich-root")
        stream_source = source._get_source(target._format)
        self.assertIsInstance(stream_source, knitpack_repo.KnitPackStreamSource)

    def test_source_to_remote_exact_pack_19(self):
        trans = self.make_smart_server("target")
        trans.ensure_base()
        source = self.make_repository("source", format="1.9")
        target = self.make_repository("target", format="1.9")
        target = repository.Repository.open(trans.base)
        stream_source = source._get_source(target._format)
        self.assertIsInstance(stream_source, knitpack_repo.KnitPackStreamSource)

    def test_stream_source_to_non_exact(self):
        source = self.make_repository("source", format="pack-0.92")
        target = self.make_repository("target", format="1.9")
        stream = source._get_source(target._format)
        self.assertIs(type(stream), vf_repository.StreamSource)

    def test_stream_source_to_non_exact_rich_root(self):
        source = self.make_repository("source", format="1.9")
        target = self.make_repository("target", format="1.9-rich-root")
        stream = source._get_source(target._format)
        self.assertIs(type(stream), vf_repository.StreamSource)

    def test_source_to_remote_non_exact_pack_19(self):
        trans = self.make_smart_server("target")
        trans.ensure_base()
        source = self.make_repository("source", format="1.9")
        target = self.make_repository("target", format="1.6")
        target = repository.Repository.open(trans.base)
        stream_source = source._get_source(target._format)
        self.assertIs(type(stream_source), vf_repository.StreamSource)

    def test_stream_source_to_knit(self):
        source = self.make_repository("source", format="pack-0.92")
        target = self.make_repository("target", format="dirstate")
        stream = source._get_source(target._format)
        self.assertIs(type(stream), vf_repository.StreamSource)


class TestDevelopment6FindParentIdsOfRevisions(TestCaseWithTransport):
    """Tests for _find_parent_ids_of_revisions."""

    def setUp(self):
        super().setUp()
        self.builder = self.make_branch_builder("source")
        self.builder.start_series()
        self.builder.build_snapshot(
            None,
            [("add", ("", b"tree-root", "directory", None))],
            revision_id=b"initial",
        )
        self.repo = self.builder.get_branch().repository
        self.addCleanup(self.builder.finish_series)

    def assertParentIds(self, expected_result, rev_set):
        self.assertEqual(
            sorted(expected_result),
            sorted(self.repo._find_parent_ids_of_revisions(rev_set)),
        )

    def test_simple(self):
        self.builder.build_snapshot(None, [], revision_id=b"revid1")
        self.builder.build_snapshot([b"revid1"], [], revision_id=b"revid2")
        rev_set = [b"revid2"]
        self.assertParentIds([b"revid1"], rev_set)

    def test_not_first_parent(self):
        self.builder.build_snapshot(None, [], revision_id=b"revid1")
        self.builder.build_snapshot([b"revid1"], [], revision_id=b"revid2")
        self.builder.build_snapshot([b"revid2"], [], revision_id=b"revid3")
        rev_set = [b"revid3", b"revid2"]
        self.assertParentIds([b"revid1"], rev_set)

    def test_not_null(self):
        rev_set = [b"initial"]
        self.assertParentIds([], rev_set)

    def test_not_null_set(self):
        self.builder.build_snapshot(None, [], revision_id=b"revid1")
        rev_set = [_mod_revision.NULL_REVISION]
        self.assertParentIds([], rev_set)

    def test_ghost(self):
        self.builder.build_snapshot(None, [], revision_id=b"revid1")
        rev_set = [b"ghost", b"revid1"]
        self.assertParentIds([b"initial"], rev_set)

    def test_ghost_parent(self):
        self.builder.build_snapshot(None, [], revision_id=b"revid1")
        self.builder.build_snapshot([b"revid1", b"ghost"], [], revision_id=b"revid2")
        rev_set = [b"revid2", b"revid1"]
        self.assertParentIds([b"ghost", b"initial"], rev_set)

    def test_righthand_parent(self):
        self.builder.build_snapshot(None, [], revision_id=b"revid1")
        self.builder.build_snapshot([b"revid1"], [], revision_id=b"revid2a")
        self.builder.build_snapshot([b"revid1"], [], revision_id=b"revid2b")
        self.builder.build_snapshot([b"revid2a", b"revid2b"], [], revision_id=b"revid3")
        rev_set = [b"revid3", b"revid2a"]
        self.assertParentIds([b"revid1", b"revid2b"], rev_set)


class TestWithBrokenRepo(TestCaseWithTransport):
    """These tests seem to be more appropriate as interface tests?"""

    def make_broken_repository(self):
        # XXX: This function is borrowed from Aaron's "Reconcile can fix bad
        # parent references" branch which is due to land in bzr.dev soon.  Once
        # it does, this duplication should be removed.
        repo = self.make_repository("broken-repo")
        cleanups = []
        try:
            repo.lock_write()
            cleanups.append(repo.unlock)
            repo.start_write_group()
            cleanups.append(repo.commit_write_group)
            # make rev1a: A well-formed revision, containing 'file1'
            inv = inventory.Inventory(revision_id=b"rev1a")
            inv.root.revision = b"rev1a"
            self.add_file(repo, inv, "file1", b"rev1a", [])
            repo.texts.add_lines((inv.root.file_id, b"rev1a"), [], [])
            repo.add_inventory(b"rev1a", inv, [])
            revision = _mod_revision.Revision(
                b"rev1a",
                committer="jrandom@example.com",
                timestamp=0,
                inventory_sha1="",
                timezone=0,
                message="foo",
                parent_ids=[],
            )
            repo.add_revision(b"rev1a", revision, inv)

            # make rev1b, which has no Revision, but has an Inventory, and
            # file1
            inv = inventory.Inventory(revision_id=b"rev1b")
            inv.root.revision = b"rev1b"
            self.add_file(repo, inv, "file1", b"rev1b", [])
            repo.add_inventory(b"rev1b", inv, [])

            # make rev2, with file1 and file2
            # file2 is sane
            # file1 has 'rev1b' as an ancestor, even though this is not
            # mentioned by 'rev1a', making it an unreferenced ancestor
            inv = inventory.Inventory()
            self.add_file(repo, inv, "file1", b"rev2", [b"rev1a", b"rev1b"])
            self.add_file(repo, inv, "file2", b"rev2", [])
            self.add_revision(repo, b"rev2", inv, [b"rev1a"])

            # make ghost revision rev1c
            inv = inventory.Inventory()
            self.add_file(repo, inv, "file2", b"rev1c", [])

            # make rev3 with file2
            # file2 refers to 'rev1c', which is a ghost in this repository, so
            # file2 cannot have rev1c as its ancestor.
            inv = inventory.Inventory()
            self.add_file(repo, inv, "file2", b"rev3", [b"rev1c"])
            self.add_revision(repo, b"rev3", inv, [b"rev1c"])
            return repo
        finally:
            for cleanup in reversed(cleanups):
                cleanup()

    def add_revision(self, repo, revision_id, inv, parent_ids):
        inv.revision_id = revision_id
        inv.root.revision = revision_id
        repo.texts.add_lines((inv.root.file_id, revision_id), [], [])
        repo.add_inventory(revision_id, inv, parent_ids)
        revision = _mod_revision.Revision(
            revision_id,
            committer="jrandom@example.com",
            timestamp=0,
            inventory_sha1="",
            timezone=0,
            message="foo",
            parent_ids=parent_ids,
        )
        repo.add_revision(revision_id, revision, inv)

    def add_file(self, repo, inv, filename, revision, parents):
        file_id = filename.encode("utf-8") + b"-id"
        content = [b"line\n"]
        entry = inventory.InventoryFile(file_id, filename, b"TREE_ROOT")
        entry.revision = revision
        entry.text_sha1 = osutils.sha_strings(content)
        entry.text_size = 0
        inv.add(entry)
        text_key = (file_id, revision)
        parent_keys = [(file_id, parent) for parent in parents]
        repo.texts.add_lines(text_key, parent_keys, content)

    def test_insert_from_broken_repo(self):
        """Inserting a data stream from a broken repository won't silently
        corrupt the target repository.
        """
        broken_repo = self.make_broken_repository()
        empty_repo = self.make_repository("empty-repo")
        try:
            empty_repo.fetch(broken_repo)
        except (errors.RevisionNotPresent, errors.BzrCheckError):
            # Test successful: compression parent not being copied leads to
            # error.
            return
        empty_repo.lock_read()
        self.addCleanup(empty_repo.unlock)
        text = next(
            empty_repo.texts.get_record_stream(
                [(b"file2-id", b"rev3")], "topological", True
            )
        )
        self.assertEqual(b"line\n", text.get_bytes_as("fulltext"))


class TestRepositoryPackCollection(TestCaseWithTransport):
    def get_format(self):
        return controldir.format_registry.make_controldir("pack-0.92")

    def get_packs(self):
        format = self.get_format()
        repo = self.make_repository(".", format=format)
        return repo._pack_collection

    def make_packs_and_alt_repo(self, write_lock=False):
        """Create a pack repo with 3 packs, and access it via a second repo."""
        tree = self.make_branch_and_tree(".", format=self.get_format())
        tree.lock_write()
        self.addCleanup(tree.unlock)
        rev1 = tree.commit("one")
        rev2 = tree.commit("two")
        rev3 = tree.commit("three")
        r = repository.Repository.open(".")
        if write_lock:
            r.lock_write()
        else:
            r.lock_read()
        self.addCleanup(r.unlock)
        packs = r._pack_collection
        packs.ensure_loaded()
        return tree, r, packs, [rev1, rev2, rev3]

    def test__clear_obsolete_packs(self):
        packs = self.get_packs()
        obsolete_pack_trans = packs.transport.clone("obsolete_packs")
        obsolete_pack_trans.put_bytes("a-pack.pack", b"content\n")
        obsolete_pack_trans.put_bytes("a-pack.rix", b"content\n")
        obsolete_pack_trans.put_bytes("a-pack.iix", b"content\n")
        obsolete_pack_trans.put_bytes("another-pack.pack", b"foo\n")
        obsolete_pack_trans.put_bytes("not-a-pack.rix", b"foo\n")
        res = packs._clear_obsolete_packs()
        self.assertEqual(["a-pack", "another-pack"], sorted(res))
        self.assertEqual([], obsolete_pack_trans.list_dir("."))

    def test__clear_obsolete_packs_preserve(self):
        packs = self.get_packs()
        obsolete_pack_trans = packs.transport.clone("obsolete_packs")
        obsolete_pack_trans.put_bytes("a-pack.pack", b"content\n")
        obsolete_pack_trans.put_bytes("a-pack.rix", b"content\n")
        obsolete_pack_trans.put_bytes("a-pack.iix", b"content\n")
        obsolete_pack_trans.put_bytes("another-pack.pack", b"foo\n")
        obsolete_pack_trans.put_bytes("not-a-pack.rix", b"foo\n")
        res = packs._clear_obsolete_packs(preserve={"a-pack"})
        self.assertEqual(["a-pack", "another-pack"], sorted(res))
        self.assertEqual(
            ["a-pack.iix", "a-pack.pack", "a-pack.rix"],
            sorted(obsolete_pack_trans.list_dir(".")),
        )

    def test__max_pack_count(self):
        """The maximum pack count is a function of the number of revisions."""
        # no revisions - one pack, so that we can have a revision free repo
        # without it blowing up
        packs = self.get_packs()
        self.assertEqual(1, packs._max_pack_count(0))
        # after that the sum of the digits, - check the first 1-9
        self.assertEqual(1, packs._max_pack_count(1))
        self.assertEqual(2, packs._max_pack_count(2))
        self.assertEqual(3, packs._max_pack_count(3))
        self.assertEqual(4, packs._max_pack_count(4))
        self.assertEqual(5, packs._max_pack_count(5))
        self.assertEqual(6, packs._max_pack_count(6))
        self.assertEqual(7, packs._max_pack_count(7))
        self.assertEqual(8, packs._max_pack_count(8))
        self.assertEqual(9, packs._max_pack_count(9))
        # check the boundary cases with two digits for the next decade
        self.assertEqual(1, packs._max_pack_count(10))
        self.assertEqual(2, packs._max_pack_count(11))
        self.assertEqual(10, packs._max_pack_count(19))
        self.assertEqual(2, packs._max_pack_count(20))
        self.assertEqual(3, packs._max_pack_count(21))
        # check some arbitrary big numbers
        self.assertEqual(25, packs._max_pack_count(112894))

    def test_repr(self):
        packs = self.get_packs()
        self.assertContainsRe(repr(packs), "RepositoryPackCollection(.*Repository(.*))")

    def test__obsolete_packs(self):
        tree, r, packs, revs = self.make_packs_and_alt_repo(write_lock=True)
        names = packs.names()
        pack = packs.get_pack_by_name(names[0])
        # Schedule this one for removal
        packs._remove_pack_from_memory(pack)
        # Simulate a concurrent update by renaming the .pack file and one of
        # the indices
        packs.transport.rename(
            "packs/{}.pack".format(names[0]), "obsolete_packs/{}.pack".format(names[0])
        )
        packs.transport.rename(
            "indices/{}.iix".format(names[0]), "obsolete_packs/{}.iix".format(names[0])
        )
        # Now trigger the obsoletion, and ensure that all the remaining files
        # are still renamed
        packs._obsolete_packs([pack])
        self.assertEqual(
            [n + ".pack" for n in names[1:]],
            sorted(packs._pack_transport.list_dir(".")),
        )
        # names[0] should not be present in the index anymore
        self.assertEqual(
            names[1:],
            sorted(
                {osutils.splitext(n)[0] for n in packs._index_transport.list_dir(".")}
            ),
        )

    def test__obsolete_packs_missing_directory(self):
        tree, r, packs, revs = self.make_packs_and_alt_repo(write_lock=True)
        r.control_transport.rmdir("obsolete_packs")
        names = packs.names()
        pack = packs.get_pack_by_name(names[0])
        # Schedule this one for removal
        packs._remove_pack_from_memory(pack)
        # Now trigger the obsoletion, and ensure that all the remaining files
        # are still renamed
        packs._obsolete_packs([pack])
        self.assertEqual(
            [n + ".pack" for n in names[1:]],
            sorted(packs._pack_transport.list_dir(".")),
        )
        # names[0] should not be present in the index anymore
        self.assertEqual(
            names[1:],
            sorted(
                {osutils.splitext(n)[0] for n in packs._index_transport.list_dir(".")}
            ),
        )

    def test_pack_distribution_zero(self):
        packs = self.get_packs()
        self.assertEqual([0], packs.pack_distribution(0))

    def test_ensure_loaded_unlocked(self):
        packs = self.get_packs()
        self.assertRaises(errors.ObjectNotLocked, packs.ensure_loaded)

    def test_pack_distribution_one_to_nine(self):
        packs = self.get_packs()
        self.assertEqual([1], packs.pack_distribution(1))
        self.assertEqual([1, 1], packs.pack_distribution(2))
        self.assertEqual([1, 1, 1], packs.pack_distribution(3))
        self.assertEqual([1, 1, 1, 1], packs.pack_distribution(4))
        self.assertEqual([1, 1, 1, 1, 1], packs.pack_distribution(5))
        self.assertEqual([1, 1, 1, 1, 1, 1], packs.pack_distribution(6))
        self.assertEqual([1, 1, 1, 1, 1, 1, 1], packs.pack_distribution(7))
        self.assertEqual([1, 1, 1, 1, 1, 1, 1, 1], packs.pack_distribution(8))
        self.assertEqual([1, 1, 1, 1, 1, 1, 1, 1, 1], packs.pack_distribution(9))

    def test_pack_distribution_stable_at_boundaries(self):
        """When there are multi-rev packs the counts are stable."""
        packs = self.get_packs()
        # in 10s:
        self.assertEqual([10], packs.pack_distribution(10))
        self.assertEqual([10, 1], packs.pack_distribution(11))
        self.assertEqual([10, 10], packs.pack_distribution(20))
        self.assertEqual([10, 10, 1], packs.pack_distribution(21))
        # 100s
        self.assertEqual([100], packs.pack_distribution(100))
        self.assertEqual([100, 1], packs.pack_distribution(101))
        self.assertEqual([100, 10, 1], packs.pack_distribution(111))
        self.assertEqual([100, 100], packs.pack_distribution(200))
        self.assertEqual([100, 100, 1], packs.pack_distribution(201))
        self.assertEqual([100, 100, 10, 1], packs.pack_distribution(211))

    def test_plan_pack_operations_2009_revisions_skip_all_packs(self):
        packs = self.get_packs()
        existing_packs = [(2000, "big"), (9, "medium")]
        # rev count - 2009 -> 2x1000 + 9x1
        pack_operations = packs.plan_autopack_combinations(
            existing_packs, [1000, 1000, 1, 1, 1, 1, 1, 1, 1, 1, 1]
        )
        self.assertEqual([], pack_operations)

    def test_plan_pack_operations_2010_revisions_skip_all_packs(self):
        packs = self.get_packs()
        existing_packs = [(2000, "big"), (9, "medium"), (1, "single")]
        # rev count - 2010 -> 2x1000 + 1x10
        pack_operations = packs.plan_autopack_combinations(
            existing_packs, [1000, 1000, 10]
        )
        self.assertEqual([], pack_operations)

    def test_plan_pack_operations_2010_combines_smallest_two(self):
        packs = self.get_packs()
        existing_packs = [(1999, "big"), (9, "medium"), (1, "single2"), (1, "single1")]
        # rev count - 2010 -> 2x1000 + 1x10 (3)
        pack_operations = packs.plan_autopack_combinations(
            existing_packs, [1000, 1000, 10]
        )
        self.assertEqual([[2, ["single2", "single1"]]], pack_operations)

    def test_plan_pack_operations_creates_a_single_op(self):
        packs = self.get_packs()
        existing_packs = [
            (50, "a"),
            (40, "b"),
            (30, "c"),
            (10, "d"),
            (10, "e"),
            (6, "f"),
            (4, "g"),
        ]
        # rev count 150 -> 1x100 and 5x10
        # The two size 10 packs do not need to be touched. The 50, 40, 30 would
        # be combined into a single 120 size pack, and the 6 & 4 would
        # becombined into a size 10 pack. However, if we have to rewrite them,
        # we save a pack file with no increased I/O by putting them into the
        # same file.
        distribution = packs.pack_distribution(150)
        pack_operations = packs.plan_autopack_combinations(existing_packs, distribution)
        self.assertEqual([[130, ["a", "b", "c", "f", "g"]]], pack_operations)

    def test_all_packs_none(self):
        format = self.get_format()
        tree = self.make_branch_and_tree(".", format=format)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        packs = tree.branch.repository._pack_collection
        packs.ensure_loaded()
        self.assertEqual([], packs.all_packs())

    def test_all_packs_one(self):
        format = self.get_format()
        tree = self.make_branch_and_tree(".", format=format)
        tree.commit("start")
        tree.lock_read()
        self.addCleanup(tree.unlock)
        packs = tree.branch.repository._pack_collection
        packs.ensure_loaded()
        self.assertEqual([packs.get_pack_by_name(packs.names()[0])], packs.all_packs())

    def test_all_packs_two(self):
        format = self.get_format()
        tree = self.make_branch_and_tree(".", format=format)
        tree.commit("start")
        tree.commit("continue")
        tree.lock_read()
        self.addCleanup(tree.unlock)
        packs = tree.branch.repository._pack_collection
        packs.ensure_loaded()
        self.assertEqual(
            [
                packs.get_pack_by_name(packs.names()[0]),
                packs.get_pack_by_name(packs.names()[1]),
            ],
            packs.all_packs(),
        )

    def test_get_pack_by_name(self):
        format = self.get_format()
        tree = self.make_branch_and_tree(".", format=format)
        tree.commit("start")
        tree.lock_read()
        self.addCleanup(tree.unlock)
        packs = tree.branch.repository._pack_collection
        packs.reset()
        packs.ensure_loaded()
        name = packs.names()[0]
        pack_1 = packs.get_pack_by_name(name)
        # the pack should be correctly initialised
        sizes = packs._names[name]
        rev_index = GraphIndex(packs._index_transport, name + ".rix", sizes[0])
        inv_index = GraphIndex(packs._index_transport, name + ".iix", sizes[1])
        txt_index = GraphIndex(packs._index_transport, name + ".tix", sizes[2])
        sig_index = GraphIndex(packs._index_transport, name + ".six", sizes[3])
        self.assertEqual(
            pack_repo.ExistingPack(
                packs._pack_transport, name, rev_index, inv_index, txt_index, sig_index
            ),
            pack_1,
        )
        # and the same instance should be returned on successive calls.
        self.assertTrue(pack_1 is packs.get_pack_by_name(name))

    def test_reload_pack_names_new_entry(self):
        tree, r, packs, revs = self.make_packs_and_alt_repo()
        names = packs.names()
        # Add a new pack file into the repository
        rev4 = tree.commit("four")
        new_names = tree.branch.repository._pack_collection.names()
        new_name = set(new_names).difference(names)
        self.assertEqual(1, len(new_name))
        new_name = new_name.pop()
        # The old collection hasn't noticed yet
        self.assertEqual(names, packs.names())
        self.assertTrue(packs.reload_pack_names())
        self.assertEqual(new_names, packs.names())
        # And the repository can access the new revision
        self.assertEqual({rev4: (revs[-1],)}, r.get_parent_map([rev4]))
        self.assertFalse(packs.reload_pack_names())

    def test_reload_pack_names_added_and_removed(self):
        tree, r, packs, revs = self.make_packs_and_alt_repo()
        names = packs.names()
        # Now repack the whole thing
        tree.branch.repository.pack()
        new_names = tree.branch.repository._pack_collection.names()
        # The other collection hasn't noticed yet
        self.assertEqual(names, packs.names())
        self.assertTrue(packs.reload_pack_names())
        self.assertEqual(new_names, packs.names())
        self.assertEqual({revs[-1]: (revs[-2],)}, r.get_parent_map([revs[-1]]))
        self.assertFalse(packs.reload_pack_names())

    def test_reload_pack_names_preserves_pending(self):
        # TODO: Update this to also test for pending-deleted names
        tree, r, packs, revs = self.make_packs_and_alt_repo(write_lock=True)
        # We will add one pack (via start_write_group + insert_record_stream),
        # and remove another pack (via _remove_pack_from_memory)
        orig_names = packs.names()
        orig_at_load = packs._packs_at_load
        to_remove_name = next(iter(orig_names))
        r.start_write_group()
        self.addCleanup(r.abort_write_group)
        r.texts.insert_record_stream(
            [
                versionedfile.FulltextContentFactory(
                    (b"text", b"rev"), (), None, b"content\n"
                )
            ]
        )
        new_pack = packs._new_pack
        self.assertTrue(new_pack.data_inserted())
        new_pack.finish()
        packs.allocate(new_pack)
        packs._new_pack = None
        removed_pack = packs.get_pack_by_name(to_remove_name)
        packs._remove_pack_from_memory(removed_pack)
        names = packs.names()
        all_nodes, deleted_nodes, new_nodes, _ = packs._diff_pack_names()
        new_names = {x[0] for x in new_nodes}
        self.assertEqual(names, sorted([x[0] for x in all_nodes]))
        self.assertEqual(set(names) - set(orig_names), new_names)
        self.assertEqual({new_pack.name}, new_names)
        self.assertEqual([to_remove_name], sorted([x[0] for x in deleted_nodes]))
        packs.reload_pack_names()
        reloaded_names = packs.names()
        self.assertEqual(orig_at_load, packs._packs_at_load)
        self.assertEqual(names, reloaded_names)
        all_nodes, deleted_nodes, new_nodes, _ = packs._diff_pack_names()
        new_names = {x[0] for x in new_nodes}
        self.assertEqual(names, sorted([x[0] for x in all_nodes]))
        self.assertEqual(set(names) - set(orig_names), new_names)
        self.assertEqual({new_pack.name}, new_names)
        self.assertEqual([to_remove_name], sorted([x[0] for x in deleted_nodes]))

    def test_autopack_obsoletes_new_pack(self):
        tree, r, packs, revs = self.make_packs_and_alt_repo(write_lock=True)
        packs._max_pack_count = lambda x: 1
        packs.pack_distribution = lambda x: [10]
        r.start_write_group()
        r.revisions.insert_record_stream(
            [
                versionedfile.FulltextContentFactory(
                    (b"bogus-rev",), (), None, b"bogus-content\n"
                )
            ]
        )
        # This should trigger an autopack, which will combine everything into a
        # single pack file.
        r.commit_write_group()
        names = packs.names()
        self.assertEqual(1, len(names))
        self.assertEqual([names[0] + ".pack"], packs._pack_transport.list_dir("."))

    def test_autopack_reloads_and_stops(self):
        tree, r, packs, revs = self.make_packs_and_alt_repo(write_lock=True)
        # After we have determined what needs to be autopacked, trigger a
        # full-pack via the other repo which will cause us to re-evaluate and
        # decide we don't need to do anything
        orig_execute = packs._execute_pack_operations

        def _munged_execute_pack_ops(*args, **kwargs):
            tree.branch.repository.pack()
            return orig_execute(*args, **kwargs)

        packs._execute_pack_operations = _munged_execute_pack_ops
        packs._max_pack_count = lambda x: 1
        packs.pack_distribution = lambda x: [10]
        self.assertFalse(packs.autopack())
        self.assertEqual(1, len(packs.names()))
        self.assertEqual(tree.branch.repository._pack_collection.names(), packs.names())

    def test__save_pack_names(self):
        tree, r, packs, revs = self.make_packs_and_alt_repo(write_lock=True)
        names = packs.names()
        pack = packs.get_pack_by_name(names[0])
        packs._remove_pack_from_memory(pack)
        packs._save_pack_names(obsolete_packs=[pack])
        cur_packs = packs._pack_transport.list_dir(".")
        self.assertEqual([n + ".pack" for n in names[1:]], sorted(cur_packs))
        # obsolete_packs will also have stuff like .rix and .iix present.
        obsolete_packs = packs.transport.list_dir("obsolete_packs")
        obsolete_names = {osutils.splitext(n)[0] for n in obsolete_packs}
        self.assertEqual([pack.name], sorted(obsolete_names))

    def test__save_pack_names_already_obsoleted(self):
        tree, r, packs, revs = self.make_packs_and_alt_repo(write_lock=True)
        names = packs.names()
        pack = packs.get_pack_by_name(names[0])
        packs._remove_pack_from_memory(pack)
        # We are going to simulate a concurrent autopack by manually obsoleting
        # the pack directly.
        packs._obsolete_packs([pack])
        packs._save_pack_names(clear_obsolete_packs=True, obsolete_packs=[pack])
        cur_packs = packs._pack_transport.list_dir(".")
        self.assertEqual([n + ".pack" for n in names[1:]], sorted(cur_packs))
        # Note that while we set clear_obsolete_packs=True, it should not
        # delete a pack file that we have also scheduled for obsoletion.
        obsolete_packs = packs.transport.list_dir("obsolete_packs")
        obsolete_names = {osutils.splitext(n)[0] for n in obsolete_packs}
        self.assertEqual([pack.name], sorted(obsolete_names))

    def test_pack_no_obsolete_packs_directory(self):
        """Bug #314314, don't fail if obsolete_packs directory does
        not exist.
        """
        tree, r, packs, revs = self.make_packs_and_alt_repo(write_lock=True)
        r.control_transport.rmdir("obsolete_packs")
        packs._clear_obsolete_packs()


class TestPack(TestCaseWithTransport):
    """Tests for the Pack object."""

    def assertCurrentlyEqual(self, left, right):
        self.assertTrue(left == right)
        self.assertTrue(right == left)
        self.assertFalse(left != right)
        self.assertFalse(right != left)

    def assertCurrentlyNotEqual(self, left, right):
        self.assertFalse(left == right)
        self.assertFalse(right == left)
        self.assertTrue(left != right)
        self.assertTrue(right != left)

    def test___eq____ne__(self):
        left = pack_repo.ExistingPack("", "", "", "", "", "")
        right = pack_repo.ExistingPack("", "", "", "", "", "")
        self.assertCurrentlyEqual(left, right)
        # change all attributes and ensure equality changes as we do.
        left.revision_index = "a"
        self.assertCurrentlyNotEqual(left, right)
        right.revision_index = "a"
        self.assertCurrentlyEqual(left, right)
        left.inventory_index = "a"
        self.assertCurrentlyNotEqual(left, right)
        right.inventory_index = "a"
        self.assertCurrentlyEqual(left, right)
        left.text_index = "a"
        self.assertCurrentlyNotEqual(left, right)
        right.text_index = "a"
        self.assertCurrentlyEqual(left, right)
        left.signature_index = "a"
        self.assertCurrentlyNotEqual(left, right)
        right.signature_index = "a"
        self.assertCurrentlyEqual(left, right)
        left.name = "a"
        self.assertCurrentlyNotEqual(left, right)
        right.name = "a"
        self.assertCurrentlyEqual(left, right)
        left.transport = "a"
        self.assertCurrentlyNotEqual(left, right)
        right.transport = "a"
        self.assertCurrentlyEqual(left, right)

    def test_file_name(self):
        pack = pack_repo.ExistingPack("", "a_name", "", "", "", "")
        self.assertEqual("a_name.pack", pack.file_name())


class TestNewPack(TestCaseWithTransport):
    """Tests for pack_repo.NewPack."""

    def test_new_instance_attributes(self):
        upload_transport = self.get_transport("upload")
        pack_transport = self.get_transport("pack")
        index_transport = self.get_transport("index")
        upload_transport.mkdir(".")
        collection = pack_repo.RepositoryPackCollection(
            repo=None,
            transport=self.get_transport("."),
            index_transport=index_transport,
            upload_transport=upload_transport,
            pack_transport=pack_transport,
            index_builder_class=BTreeBuilder,
            index_class=BTreeGraphIndex,
            use_chk_index=False,
        )
        pack = pack_repo.NewPack(collection)
        self.addCleanup(pack.abort)  # Make sure the write stream gets closed
        self.assertIsInstance(pack.revision_index, BTreeBuilder)
        self.assertIsInstance(pack.inventory_index, BTreeBuilder)
        self.assertIsInstance(pack._hash, type(osutils.md5()))
        self.assertTrue(pack.upload_transport is upload_transport)
        self.assertTrue(pack.index_transport is index_transport)
        self.assertTrue(pack.pack_transport is pack_transport)
        self.assertEqual(None, pack.index_sizes)
        self.assertEqual(20, len(pack.random_name))
        self.assertIsInstance(pack.random_name, str)
        self.assertIsInstance(pack.start_time, float)


class TestPacker(TestCaseWithTransport):
    """Tests for the packs repository Packer class."""

    def test_pack_optimizes_pack_order(self):
        builder = self.make_branch_builder(".", format="1.9")
        builder.start_series()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"root-id", "directory", None)),
                ("add", ("f", b"f-id", "file", b"content\n")),
            ],
            revision_id=b"A",
        )
        builder.build_snapshot(
            [b"A"], [("modify", ("f", b"new-content\n"))], revision_id=b"B"
        )
        builder.build_snapshot(
            [b"B"], [("modify", ("f", b"third-content\n"))], revision_id=b"C"
        )
        builder.build_snapshot(
            [b"C"], [("modify", ("f", b"fourth-content\n"))], revision_id=b"D"
        )
        b = builder.get_branch()
        b.lock_read()
        builder.finish_series()
        self.addCleanup(b.unlock)
        # At this point, we should have 4 pack files available
        # Because of how they were built, they correspond to
        # ['D', 'C', 'B', 'A']
        packs = b.repository._pack_collection.packs
        packer = knitpack_repo.KnitPacker(
            b.repository._pack_collection, packs, "testing", revision_ids=[b"B", b"C"]
        )
        # Now, when we are copying the B & C revisions, their pack files should
        # be moved to the front of the stack
        # The new ordering moves B & C to the front of the .packs attribute,
        # and leaves the others in the original order.
        new_packs = [packs[1], packs[2], packs[0], packs[3]]
        packer.pack()
        self.assertEqual(new_packs, packer.packs)


class TestOptimisingPacker(TestCaseWithTransport):
    """Tests for the OptimisingPacker class."""

    def get_pack_collection(self):
        repo = self.make_repository(".")
        return repo._pack_collection

    def test_open_pack_will_optimise(self):
        packer = knitpack_repo.OptimisingKnitPacker(
            self.get_pack_collection(), [], ".test"
        )
        new_pack = packer.open_pack()
        self.addCleanup(new_pack.abort)  # ensure cleanup
        self.assertIsInstance(new_pack, pack_repo.NewPack)
        self.assertTrue(new_pack.revision_index._optimize_for_size)
        self.assertTrue(new_pack.inventory_index._optimize_for_size)
        self.assertTrue(new_pack.text_index._optimize_for_size)
        self.assertTrue(new_pack.signature_index._optimize_for_size)


class TestGCCHKPacker(TestCaseWithTransport):
    def make_abc_branch(self):
        builder = self.make_branch_builder("source")
        builder.start_series()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"root-id", "directory", None)),
                ("add", ("file", b"file-id", "file", b"content\n")),
            ],
            revision_id=b"A",
        )
        builder.build_snapshot(
            [b"A"], [("add", ("dir", b"dir-id", "directory", None))], revision_id=b"B"
        )
        builder.build_snapshot(
            [b"B"], [("modify", ("file", b"new content\n"))], revision_id=b"C"
        )
        builder.finish_series()
        return builder.get_branch()

    def make_branch_with_disjoint_inventory_and_revision(self):
        """A repo with separate packs for a revisions Revision and Inventory.

        There will be one pack file that holds the Revision content, and one
        for the Inventory content.

        :return: (repository,
                  pack_name_with_rev_A_Revision,
                  pack_name_with_rev_A_Inventory,
                  pack_name_with_rev_C_content)
        """
        b_source = self.make_abc_branch()
        b_base = b_source.controldir.sprout("base", revision_id=b"A").open_branch()
        b_stacked = b_base.controldir.sprout("stacked", stacked=True).open_branch()
        b_stacked.lock_write()
        self.addCleanup(b_stacked.unlock)
        b_stacked.fetch(b_source, b"B")
        # Now re-open the stacked repo directly (no fallbacks) so that we can
        # fill in the A rev.
        repo_not_stacked = b_stacked.controldir.open_repository()
        repo_not_stacked.lock_write()
        self.addCleanup(repo_not_stacked.unlock)
        # Now we should have a pack file with A's inventory, but not its
        # Revision
        self.assertEqual(
            [(b"A",), (b"B",)], sorted(repo_not_stacked.inventories.keys())
        )
        self.assertEqual([(b"B",)], sorted(repo_not_stacked.revisions.keys()))
        stacked_pack_names = repo_not_stacked._pack_collection.names()
        # We have a couple names here, figure out which has A's inventory
        for name in stacked_pack_names:
            pack = repo_not_stacked._pack_collection.get_pack_by_name(name)
            keys = [n[1] for n in pack.inventory_index.iter_all_entries()]
            if (b"A",) in keys:
                inv_a_pack_name = name
                break
        else:
            self.fail("Could not find pack containing A's inventory")
        repo_not_stacked.fetch(b_source.repository, b"A")
        self.assertEqual([(b"A",), (b"B",)], sorted(repo_not_stacked.revisions.keys()))
        new_pack_names = set(repo_not_stacked._pack_collection.names())
        rev_a_pack_names = new_pack_names.difference(stacked_pack_names)
        self.assertEqual(1, len(rev_a_pack_names))
        rev_a_pack_name = list(rev_a_pack_names)[0]
        # Now fetch 'C', so we have a couple pack files to join
        repo_not_stacked.fetch(b_source.repository, b"C")
        rev_c_pack_names = set(repo_not_stacked._pack_collection.names())
        rev_c_pack_names = rev_c_pack_names.difference(new_pack_names)
        self.assertEqual(1, len(rev_c_pack_names))
        rev_c_pack_name = list(rev_c_pack_names)[0]
        return (repo_not_stacked, rev_a_pack_name, inv_a_pack_name, rev_c_pack_name)

    def test_pack_with_distant_inventories(self):
        # See https://bugs.launchpad.net/bzr/+bug/437003
        # When repacking, it is possible to have an inventory in a different
        # pack file than the associated revision. An autopack can then come
        # along, and miss that inventory, and complain.
        (repo, rev_a_pack_name, inv_a_pack_name, rev_c_pack_name) = (
            self.make_branch_with_disjoint_inventory_and_revision()
        )
        a_pack = repo._pack_collection.get_pack_by_name(rev_a_pack_name)
        c_pack = repo._pack_collection.get_pack_by_name(rev_c_pack_name)
        packer = groupcompress_repo.GCCHKPacker(
            repo._pack_collection, [a_pack, c_pack], ".test-pack"
        )
        # This would raise ValueError in bug #437003, but should not raise an
        # error once fixed.
        packer.pack()

    def test_pack_with_missing_inventory(self):
        # Similar to test_pack_with_missing_inventory, but this time, we force
        # the A inventory to actually be gone from the repository.
        (repo, rev_a_pack_name, inv_a_pack_name, rev_c_pack_name) = (
            self.make_branch_with_disjoint_inventory_and_revision()
        )
        inv_a_pack = repo._pack_collection.get_pack_by_name(inv_a_pack_name)
        repo._pack_collection._remove_pack_from_memory(inv_a_pack)
        packer = groupcompress_repo.GCCHKPacker(
            repo._pack_collection, repo._pack_collection.all_packs(), ".test-pack"
        )
        e = self.assertRaises(ValueError, packer.pack)
        packer.new_pack.abort()
        self.assertContainsRe(
            str(e), r"We are missing inventories for revisions: .*'A'"
        )


class TestCrossFormatPacks(TestCaseWithTransport):
    def log_pack(self, hint=None):
        self.calls.append(("pack", hint))
        self.orig_pack(hint=hint)
        if self.expect_hint:
            self.assertTrue(hint)

    def run_stream(self, src_fmt, target_fmt, expect_pack_called):
        self.expect_hint = expect_pack_called
        self.calls = []
        source_tree = self.make_branch_and_tree("src", format=src_fmt)
        source_tree.lock_write()
        self.addCleanup(source_tree.unlock)
        tip = source_tree.commit("foo")
        target = self.make_repository("target", format=target_fmt)
        target.lock_write()
        self.addCleanup(target.unlock)
        source = source_tree.branch.repository._get_source(target._format)
        self.orig_pack = target.pack
        self.overrideAttr(target, "pack", self.log_pack)
        search = target.search_missing_revision_ids(
            source_tree.branch.repository, revision_ids=[tip]
        )
        stream = source.get_stream(search)
        from_format = source_tree.branch.repository._format
        sink = target._get_sink()
        sink.insert_stream(stream, from_format, [])
        if expect_pack_called:
            self.assertLength(1, self.calls)
        else:
            self.assertLength(0, self.calls)

    def run_fetch(self, src_fmt, target_fmt, expect_pack_called):
        self.expect_hint = expect_pack_called
        self.calls = []
        source_tree = self.make_branch_and_tree("src", format=src_fmt)
        source_tree.lock_write()
        self.addCleanup(source_tree.unlock)
        source_tree.commit("foo")
        target = self.make_repository("target", format=target_fmt)
        target.lock_write()
        self.addCleanup(target.unlock)
        source = source_tree.branch.repository
        self.orig_pack = target.pack
        self.overrideAttr(target, "pack", self.log_pack)
        target.fetch(source)
        if expect_pack_called:
            self.assertLength(1, self.calls)
        else:
            self.assertLength(0, self.calls)

    def test_sink_format_hint_no(self):
        # When the target format says packing makes no difference, pack is not
        # called.
        self.run_stream("1.9", "rich-root-pack", False)

    def test_sink_format_hint_yes(self):
        # When the target format says packing makes a difference, pack is
        # called.
        self.run_stream("1.9", "2a", True)

    def test_sink_format_same_no(self):
        # When the formats are the same, pack is not called.
        self.run_stream("2a", "2a", False)

    def test_IDS_format_hint_no(self):
        # When the target format says packing makes no difference, pack is not
        # called.
        self.run_fetch("1.9", "rich-root-pack", False)

    def test_IDS_format_hint_yes(self):
        # When the target format says packing makes a difference, pack is
        # called.
        self.run_fetch("1.9", "2a", True)

    def test_IDS_format_same_no(self):
        # When the formats are the same, pack is not called.
        self.run_fetch("2a", "2a", False)


class Test_LazyListJoin(tests.TestCase):
    def test__repr__(self):
        lazy = repository._LazyListJoin(["a"], ["b"])
        self.assertEqual("breezy.repository._LazyListJoin((['a'], ['b']))", repr(lazy))


class TestFeatures(tests.TestCaseWithTransport):
    def test_open_with_present_feature(self):
        self.addCleanup(
            bzrrepository.RepositoryFormatMetaDir.unregister_feature,
            b"makes-cheese-sandwich",
        )
        bzrrepository.RepositoryFormatMetaDir.register_feature(b"makes-cheese-sandwich")
        repo = self.make_repository(".")
        repo.lock_write()
        repo._format.features[b"makes-cheese-sandwich"] = b"required"
        repo._format.check_support_status(False)
        repo.unlock()

    def test_open_with_missing_required_feature(self):
        repo = self.make_repository(".")
        repo.lock_write()
        repo._format.features[b"makes-cheese-sandwich"] = b"required"
        self.assertRaises(
            bzrdir.MissingFeature, repo._format.check_support_status, False
        )
