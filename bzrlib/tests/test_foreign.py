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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA


"""Tests for foreign VCS utility code."""

from bzrlib import (
    branch,
    errors,
    foreign,
    lockable_files,
    lockdir,
    )
from bzrlib.bzrdir import (
    BzrDir,
    BzrDirFormat,
    BzrDirMeta1,
    BzrDirMetaFormat1,
    format_registry,
    )
from bzrlib.inventory import Inventory
from bzrlib.revision import Revision
from bzrlib.tests import TestCase, TestCaseWithTransport

# This is the dummy foreign revision control system, used 
# mainly here in the testsuite to test the foreign VCS infrastructure.
# It is basically standard Bazaar with some minor modifications to 
# make it "foreign". 
# 
# It has the following differences to "regular" Bazaar:
# - The control directory is named ".dummy", not ".bzr".
# - The revision ids are tuples, not strings.
# - Doesn't support more than one parent natively


class DummyForeignVcsMapping(foreign.VcsMapping):
    """A simple mapping for the dummy Foreign VCS, for use with testing."""

    def __eq__(self, other):
        return type(self) == type(other)

    def revision_id_bzr_to_foreign(self, bzr_revid):
        return tuple(bzr_revid[len("dummy-v1:"):].split("-")), self

    def revision_id_foreign_to_bzr(self, foreign_revid):
        return "dummy-v1:%s-%s-%s" % foreign_revid


class DummyForeignVcsMappingRegistry(foreign.VcsMappingRegistry):

    def revision_id_bzr_to_foreign(self, revid):
        if not revid.startswith("dummy-"):
            raise errors.InvalidRevisionId(revid, None)
        mapping_version = revid[len("dummy-"):len("dummy-vx")]
        mapping = self.get(mapping_version)
        return mapping.revision_id_bzr_to_foreign(revid)


class DummyForeignVcs(foreign.ForeignVcs):
    """A dummy Foreign VCS, for use with testing.

    It has revision ids that are a tuple with three strings.
    """

    def __init__(self):
        self.mapping_registry = DummyForeignVcsMappingRegistry()
        self.mapping_registry.register("v1", DummyForeignVcsMapping(self),
                                       "Version 1")

    def show_foreign_revid(self, foreign_revid):
        return { "dummy ding": "%s/%s\\%s" % foreign_revid }


class DummyForeignVcsBranch(branch.BzrBranch6,foreign.ForeignBranch):
    """A Dummy VCS Branch."""

    def __init__(self, _format, _control_files, a_bzrdir, *args, **kwargs):
        self._format = _format
        self._base = a_bzrdir.transport.base
        self._ignore_fallbacks = False
        foreign.ForeignBranch.__init__(self, DummyForeignVcsMapping(DummyForeignVcs()))
        branch.BzrBranch6.__init__(self, _format, _control_files, a_bzrdir, *args, **kwargs)

    def dpull(self, source, stop_revision=None):
        # This just handles simple cases, but that's good enough for tests
        my_history = self.revision_history()
        their_history = source.revision_history()
        if their_history[:min(len(my_history), len(their_history))] != my_history:
            raise errors.DivergedBranches(self, source)
        todo = their_history[len(my_history):]
        revidmap = {}
        for revid in todo:
            rev = source.repository.get_revision(revid)
            tree = source.repository.revision_tree(revid)
            builder = self.get_commit_builder([self.last_revision()], 
                    self.get_config(), rev.timestamp,
                    rev.timezone, rev.committer, rev.properties)
            for path, ie in tree.inventory.iter_entries():
                builder.record_entry_contents(ie.copy(), 
                    [self.repository.get_inventory(self.last_revision())],
                    path, tree, None)
            builder.finish_inventory()
            revidmap[revid] = builder.commit(rev.message)
        return revidmap


class DummyForeignVcsBranchFormat(branch.BzrBranchFormat6):

    def get_format_string(self):
        return "Branch for Testing"

    def __init__(self):
        super(DummyForeignVcsBranchFormat, self).__init__()
        self._matchingbzrdir = DummyForeignVcsDirFormat()

    def open(self, a_bzrdir, _found=False):
        if not _found:
            raise NotImplementedError
        try:
            transport = a_bzrdir.get_branch_transport(None)
            control_files = lockable_files.LockableFiles(transport, 'lock',
                                                         lockdir.LockDir)
            return DummyForeignVcsBranch(_format=self,
                              _control_files=control_files,
                              a_bzrdir=a_bzrdir,
                              _repository=a_bzrdir.find_repository())
        except errors.NoSuchFile:
            raise errors.NotBranchError(path=transport.base)


class DummyForeignVcsDirFormat(BzrDirMetaFormat1):
    """BzrDirFormat for the dummy foreign VCS."""

    @classmethod
    def get_format_string(cls):
        return "A Dummy VCS Dir"

    @classmethod
    def get_format_description(cls):
        return "A Dummy VCS Dir"

    @classmethod
    def is_supported(cls):
        return True

    def get_branch_format(self):
        return DummyForeignVcsBranchFormat()

    @classmethod
    def probe_transport(klass, transport):
        """Return the .bzrdir style format present in a directory."""
        if not transport.has('.dummy'):
            raise errors.NotBranchError(path=transport.base)
        return klass()

    def initialize_on_transport(self, transport):
        """Initialize a new bzrdir in the base directory of a Transport."""
        # Since we don't have a .bzr directory, inherit the
        # mode from the root directory
        temp_control = lockable_files.LockableFiles(transport,
                            '', lockable_files.TransportLock)
        temp_control._transport.mkdir('.dummy',
                                      # FIXME: RBC 20060121 don't peek under
                                      # the covers
                                      mode=temp_control._dir_mode)
        del temp_control
        bzrdir_transport = transport.clone('.dummy')
        # NB: no need to escape relative paths that are url safe.
        control_files = lockable_files.LockableFiles(bzrdir_transport,
            self._lock_file_name, self._lock_class)
        control_files.create_lock()
        return self.open(transport, _found=True)

    def _open(self, transport):
        return DummyForeignVcsDir(transport, self)


class DummyForeignVcsDir(BzrDirMeta1):

    def __init__(self, _transport, _format):
        self._format = _format
        self.transport = _transport.clone('.dummy')
        self.root_transport = _transport
        self._mode_check_done = False
        self._control_files = lockable_files.LockableFiles(self.transport,
            "lock", lockable_files.TransportLock)

    def open_branch(self):
        return self._format.get_branch_format().open(self, _found=True)

    def cloning_metadir(self, stacked=False):
        """Produce a metadir suitable for cloning with."""
        return format_registry.make_bzrdir("default")

    def sprout(self, url, revision_id=None, force_new_repo=False,
               recurse='down', possible_transports=None,
               accelerator_tree=None, hardlink=False, stacked=False,
               source_branch=None):
        # dirstate doesn't cope with accelerator_trees well 
        # that have a different control dir
        return super(DummyForeignVcsDir, self).sprout(url=url, 
                revision_id=revision_id, force_new_repo=force_new_repo, 
                recurse=recurse, possible_transports=possible_transports, 
                hardlink=hardlink, stacked=stacked, source_branch=source_branch)


class ForeignVcsRegistryTests(TestCase):
    """Tests for the ForeignVcsRegistry class."""

    def test_parse_revision_id_no_dash(self):
        reg = foreign.ForeignVcsRegistry()
        self.assertRaises(errors.InvalidRevisionId,
                          reg.parse_revision_id, "invalid")

    def test_parse_revision_id_unknown_mapping(self):
        reg = foreign.ForeignVcsRegistry()
        self.assertRaises(errors.InvalidRevisionId,
                          reg.parse_revision_id, "unknown-foreignrevid")

    def test_parse_revision_id(self):
        reg = foreign.ForeignVcsRegistry()
        vcs = DummyForeignVcs()
        reg.register("dummy", vcs, "Dummy VCS")
        self.assertEquals((("some", "foreign", "revid"), DummyForeignVcsMapping(vcs)),
                          reg.parse_revision_id("dummy-v1:some-foreign-revid"))


class ForeignRevisionTests(TestCase):
    """Tests for the ForeignRevision class."""

    def test_create(self):
        mapp = DummyForeignVcsMapping(DummyForeignVcs())
        rev = foreign.ForeignRevision(("a", "foreign", "revid"),
                                      mapp, "roundtripped-revid")
        self.assertEquals("", rev.inventory_sha1)
        self.assertEquals(("a", "foreign", "revid"), rev.foreign_revid)
        self.assertEquals(mapp, rev.mapping)


class ShowForeignPropertiesTests(TestCase):
    """Tests for the show_foreign_properties() function."""

    def setUp(self):
        super(ShowForeignPropertiesTests, self).setUp()
        self.vcs = DummyForeignVcs()
        foreign.foreign_vcs_registry.register("dummy",
            self.vcs, "Dummy VCS")

    def tearDown(self):
        super(ShowForeignPropertiesTests, self).tearDown()
        foreign.foreign_vcs_registry.remove("dummy")

    def test_show_non_foreign(self):
        """Test use with a native (non-foreign) bzr revision."""
        self.assertEquals({}, foreign.show_foreign_properties(Revision("arevid")))

    def test_show_imported(self):
        rev = Revision("dummy-v1:my-foreign-revid")
        self.assertEquals({ "dummy ding": "my/foreign\\revid" },
                          foreign.show_foreign_properties(rev))

    def test_show_direct(self):
        rev = foreign.ForeignRevision(("some", "foreign", "revid"),
                                      DummyForeignVcsMapping(self.vcs),
                                      "roundtrip-revid")
        self.assertEquals({ "dummy ding": "some/foreign\\revid" },
                          foreign.show_foreign_properties(rev))


class WorkingTreeFileUpdateTests(TestCaseWithTransport):
    """Tests for _determine_fileid_renames()."""

    def test_det_renames_same(self):
        a = Inventory()
        a.add_path("bla", "directory", "bla-a")
        b = Inventory()
        b.add_path("bla", "directory", "bla-a")
        self.assertEquals({
            '': ('TREE_ROOT', 'TREE_ROOT'), 
            'bla': ('bla-a', 'bla-a')},
            foreign._determine_fileid_renames(a, b))

    def test_det_renames_simple(self):
        a = Inventory()
        a.add_path("bla", "directory", "bla-a")
        b = Inventory()
        b.add_path("bla", "directory", "bla-b")
        self.assertEquals({
            '': ('TREE_ROOT', 'TREE_ROOT'), 
            'bla': ('bla-a', 'bla-b'),
            }, foreign._determine_fileid_renames(a, b))

    def test_det_renames_root(self):
        a = Inventory()
        a.add_path("", "directory", "bla-a")
        b = Inventory()
        b.add_path("", "directory", "bla-b")
        self.assertEquals(
                {"": ("bla-a", "bla-b")},
                foreign._determine_fileid_renames(a, b))

    def test_update_workinginv(self):
        a = Inventory()
        a.add_path("bla", "directory", "bla-a")
        b = Inventory()
        b.add_path("bla", "directory", "bla-b")
        wt = self.make_branch_and_tree('br1')
        self.build_tree_contents([('br1/bla', 'original contents\n')])
        wt.add('bla', 'bla-a')
        foreign.update_workinginv_fileids(wt, a, b)
        wt.lock_read()
        try:
            self.assertEquals(["TREE_ROOT", "bla-b"], list(wt.inventory))
        finally:
            wt.unlock()


class DummyForeignVcsTests(TestCaseWithTransport):
    """Very basic test for DummyForeignVcs."""

    def setUp(self):
        BzrDirFormat.register_control_format(DummyForeignVcsDirFormat)
        self.addCleanup(self.unregister)
        super(DummyForeignVcsTests, self).setUp()

    def unregister(self):
        try:
            BzrDirFormat.unregister_control_format(DummyForeignVcsDirFormat)
        except ValueError:
            pass

    def test_create(self):
        """Test we can create dummies."""
        self.make_branch_and_tree("d", format=DummyForeignVcsDirFormat())
        dir = BzrDir.open("d")
        self.assertEquals("A Dummy VCS Dir", dir._format.get_format_string())
        dir.open_repository()
        dir.open_branch()
        dir.open_workingtree()

    def test_sprout(self):
        """Test we can clone dummies and that the format is not preserved."""
        self.make_branch_and_tree("d", format=DummyForeignVcsDirFormat())
        dir = BzrDir.open("d")
        newdir = dir.sprout("e")
        self.assertNotEquals("A Dummy VCS Dir", newdir._format.get_format_string())
