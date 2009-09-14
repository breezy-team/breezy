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
    trace,
    )
from bzrlib.bzrdir import (
    BzrDir,
    BzrDirFormat,
    BzrDirMeta1,
    BzrDirMetaFormat1,
    format_registry,
    )
from bzrlib.inventory import Inventory
from bzrlib.revision import (
    NULL_REVISION,
    Revision,
    )
from bzrlib.tests import (
    TestCase,
    TestCaseWithTransport,
    )

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
        foreign.ForeignBranch.__init__(self, 
            DummyForeignVcsMapping(DummyForeignVcs()))
        branch.BzrBranch6.__init__(self, _format, _control_files, a_bzrdir, 
            *args, **kwargs)


class InterToDummyVcsBranch(branch.GenericInterBranch,
                            foreign.InterToForeignBranch):

    @staticmethod
    def is_compatible(source, target):
        return isinstance(target, DummyForeignVcsBranch)

    def lossy_push(self, stop_revision=None):
        result = branch.BranchPushResult()
        result.source_branch = self.source
        result.target_branch = self.target
        result.old_revno, result.old_revid = self.target.last_revision_info()
        self.source.lock_read()
        try:
            # This just handles simple cases, but that's good enough for tests
            my_history = self.target.revision_history()
            their_history = self.source.revision_history()
            if their_history[:min(len(my_history), len(their_history))] != my_history:
                raise errors.DivergedBranches(self.target, self.source)
            todo = their_history[len(my_history):]
            revidmap = {}
            for revid in todo:
                rev = self.source.repository.get_revision(revid)
                tree = self.source.repository.revision_tree(revid)
                def get_file_with_stat(file_id, path=None):
                    return (tree.get_file(file_id), None)
                tree.get_file_with_stat = get_file_with_stat
                new_revid = self.target.mapping.revision_id_foreign_to_bzr(
                    (str(rev.timestamp), str(rev.timezone), 
                        str(self.target.revno())))
                parent_revno, parent_revid= self.target.last_revision_info()
                if parent_revid == NULL_REVISION:
                    parent_revids = []
                else:
                    parent_revids = [parent_revid]
                builder = self.target.get_commit_builder(parent_revids, 
                        self.target.get_config(), rev.timestamp,
                        rev.timezone, rev.committer, rev.properties,
                        new_revid)
                try:
                    for path, ie in tree.inventory.iter_entries():
                        new_ie = ie.copy()
                        new_ie.revision = None
                        builder.record_entry_contents(new_ie, 
                            [self.target.repository.revision_tree(parent_revid).inventory],
                            path, tree, 
                            (ie.kind, ie.text_size, ie.executable, ie.text_sha1))
                    builder.finish_inventory()
                except:
                    builder.abort()
                    raise
                revidmap[revid] = builder.commit(rev.message)
                self.target.set_last_revision_info(parent_revno+1, 
                    revidmap[revid])
                trace.mutter('lossily pushed revision %s -> %s', 
                    revid, revidmap[revid])
        finally:
            self.source.unlock()
        result.new_revno, result.new_revid = self.target.last_revision_info()
        result.revidmap = revidmap
        return result


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

    def open_branch(self, ignore_fallbacks=True):
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


class WorkingTreeFileUpdateTests(TestCaseWithTransport):
    """Tests for update_workingtree_fileids()."""

    def test_update_workingtree(self):
        wt = self.make_branch_and_tree('br1')
        self.build_tree_contents([('br1/bla', 'original contents\n')])
        wt.add('bla', 'bla-a')
        wt.commit('bla-a')
        root_id = wt.get_root_id()
        target = wt.bzrdir.sprout('br2').open_workingtree()
        target.unversion(['bla-a'])
        target.add('bla', 'bla-b')
        target.commit('bla-b')
        target_basis = target.basis_tree()
        target_basis.lock_read()
        self.addCleanup(target_basis.unlock)
        foreign.update_workingtree_fileids(wt, target_basis)
        wt.lock_read()
        try:
            self.assertEquals(set([root_id, "bla-b"]), set(wt.inventory))
        finally:
            wt.unlock()


class DummyForeignVcsTests(TestCaseWithTransport):
    """Very basic test for DummyForeignVcs."""

    def setUp(self):
        BzrDirFormat.register_control_format(DummyForeignVcsDirFormat)
        branch.InterBranch.register_optimiser(InterToDummyVcsBranch)
        self.addCleanup(self.unregister)
        super(DummyForeignVcsTests, self).setUp()

    def unregister(self):
        try:
            BzrDirFormat.unregister_control_format(DummyForeignVcsDirFormat)
        except ValueError:
            pass
        branch.InterBranch.unregister_optimiser(InterToDummyVcsBranch)

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

    def test_lossy_push_empty(self):
        source_tree = self.make_branch_and_tree("source")
        target_tree = self.make_branch_and_tree("target", 
            format=DummyForeignVcsDirFormat())
        pushresult = source_tree.branch.lossy_push(target_tree.branch)
        self.assertEquals(NULL_REVISION, pushresult.old_revid)
        self.assertEquals(NULL_REVISION, pushresult.new_revid)
        self.assertEquals({}, pushresult.revidmap)

    def test_lossy_push_simple(self):
        source_tree = self.make_branch_and_tree("source")
        self.build_tree(['source/a', 'source/b'])
        source_tree.add(['a', 'b'])
        revid1 = source_tree.commit("msg")
        target_tree = self.make_branch_and_tree("target", 
            format=DummyForeignVcsDirFormat())
        target_tree.branch.lock_write()
        try:
            pushresult = source_tree.branch.lossy_push(target_tree.branch)
        finally:
            target_tree.branch.unlock()
        self.assertEquals(NULL_REVISION, pushresult.old_revid)
        self.assertEquals({revid1:target_tree.branch.last_revision()}, 
                           pushresult.revidmap)
        self.assertEquals(pushresult.revidmap[revid1], pushresult.new_revid)
