# Copyright (C) 2008-2012, 2016 Canonical Ltd
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

from .. import (
    branch,
    controldir,
    errors,
    foreign,
    lockdir,
    repository,
    revision,
    tests,
    trace,
)
from .. import transport as _mod_transport
from ..bzr import branch as bzrbranch
from ..bzr import bzrdir, groupcompress_repo, lockable_files
from ..bzr.pack_repo import PackCommitBuilder

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
        return isinstance(self, type(other))

    def revision_id_bzr_to_foreign(self, bzr_revid):
        return tuple(bzr_revid[len(b"dummy-v1:") :].split(b"-")), self

    def revision_id_foreign_to_bzr(self, foreign_revid):
        return b"dummy-v1:%s-%s-%s" % foreign_revid


class DummyForeignVcsMappingRegistry(foreign.VcsMappingRegistry):
    def revision_id_bzr_to_foreign(self, revid):
        if not revid.startswith(b"dummy-"):
            raise errors.InvalidRevisionId(revid, None)
        mapping_version = revid[len(b"dummy-") : len(b"dummy-vx")]
        mapping = self.get(mapping_version)
        return mapping.revision_id_bzr_to_foreign(revid)


class DummyForeignVcs(foreign.ForeignVcs):
    """A dummy Foreign VCS, for use with testing.

    It has revision ids that are a tuple with three strings.
    """

    def __init__(self):
        self.mapping_registry = DummyForeignVcsMappingRegistry()
        self.mapping_registry.register(b"v1", DummyForeignVcsMapping(self), "Version 1")
        self.abbreviation = "dummy"

    def show_foreign_revid(self, foreign_revid):
        return {"dummy ding": "{}/{}\\{}".format(*foreign_revid)}

    def serialize_foreign_revid(self, foreign_revid):
        return "{}|{}|{}".format(*foreign_revid)


class DummyForeignVcsBranch(bzrbranch.BzrBranch6, foreign.ForeignBranch):
    """A Dummy VCS Branch."""

    @property
    def user_transport(self):
        return self.controldir.user_transport

    def __init__(self, _format, _control_files, a_controldir, *args, **kwargs):
        self._format = _format
        self._base = a_controldir.transport.base
        self._ignore_fallbacks = False
        self.controldir = a_controldir
        foreign.ForeignBranch.__init__(self, DummyForeignVcsMapping(DummyForeignVcs()))
        bzrbranch.BzrBranch6.__init__(
            self,
            _format=_format,
            _control_files=_control_files,
            a_controldir=a_controldir,
            **kwargs,
        )

    def _get_checkout_format(self, lightweight=False):
        """Return the most suitable metadir for a checkout of this branch.
        Weaves are used if this branch's repository uses weaves.
        """
        return self.controldir.checkout_metadir()

    def import_last_revision_info_and_tags(self, source, revno, revid, lossy=False):
        interbranch = InterToDummyVcsBranch(source, self)
        result = interbranch.push(stop_revision=revid, lossy=True)
        if lossy:
            revid = result.revidmap[revid]
        return (revno, revid)


class DummyForeignCommitBuilder(PackCommitBuilder):
    def _generate_revision_if_needed(self, revid):
        mapping = DummyForeignVcsMapping(DummyForeignVcs())
        if self._lossy:
            self._new_revision_id = mapping.revision_id_foreign_to_bzr(
                (
                    b"%d" % self._timestamp,
                    str(self._timezone).encode("ascii"),
                    b"UNKNOWN",
                )
            )
            self.random_revid = False
        elif revid is not None:
            self._new_revision_id = revid
            self.random_revid = False
        else:
            self._new_revision_id = self._gen_revision_id()
            self.random_revid = True


class DummyForeignVcsRepository(
    groupcompress_repo.CHKInventoryRepository, foreign.ForeignRepository
):
    """Dummy foreign vcs repository."""


class DummyForeignVcsRepositoryFormat(groupcompress_repo.RepositoryFormat2a):
    repository_class = DummyForeignVcsRepository
    _commit_builder_class = DummyForeignCommitBuilder

    @classmethod
    def get_format_string(cls):
        return b"Dummy Foreign Vcs Repository"

    def get_format_description(self):
        return "Dummy Foreign Vcs Repository"


def branch_history(graph, revid):
    ret = list(graph.iter_lefthand_ancestry(revid, (revision.NULL_REVISION,)))
    ret.reverse()
    return ret


class InterToDummyVcsBranch(branch.GenericInterBranch):
    @staticmethod
    def is_compatible(source, target):
        return isinstance(target, DummyForeignVcsBranch)

    def push(self, overwrite=False, stop_revision=None, lossy=False, tag_selector=None):
        if not lossy:
            raise errors.NoRoundtrippingSupport(self.source, self.target)
        result = branch.BranchPushResult()
        result.source_branch = self.source
        result.target_branch = self.target
        result.old_revno, result.old_revid = self.target.last_revision_info()
        self.source.lock_read()
        try:
            graph = self.source.repository.get_graph()
            # This just handles simple cases, but that's good enough for tests
            my_history = branch_history(
                self.target.repository.get_graph(), result.old_revid
            )
            if stop_revision is None:
                stop_revision = self.source.last_revision()
            their_history = branch_history(graph, stop_revision)
            if their_history[: min(len(my_history), len(their_history))] != my_history:
                raise errors.DivergedBranches(self.target, self.source)
            todo = their_history[len(my_history) :]
            revidmap = {}
            for revid in todo:
                rev = self.source.repository.get_revision(revid)
                tree = self.source.repository.revision_tree(revid)

                def get_file_with_stat(path):
                    return (tree.get_file(path), None)  # noqa: B023

                tree.get_file_with_stat = get_file_with_stat
                new_revid = self.target.mapping.revision_id_foreign_to_bzr(
                    (
                        b"%d" % rev.timestamp,
                        str(rev.timezone).encode("ascii"),
                        str(self.target.revno()).encode("ascii"),
                    )
                )
                parent_revno, parent_revid = self.target.last_revision_info()
                if parent_revid == revision.NULL_REVISION:
                    parent_revids = []
                else:
                    parent_revids = [parent_revid]
                builder = self.target.get_commit_builder(
                    parent_revids,
                    self.target.get_config_stack(),
                    rev.timestamp,
                    rev.timezone,
                    rev.committer,
                    rev.properties,
                    new_revid,
                )
                try:
                    parent_tree = self.target.repository.revision_tree(parent_revid)
                    iter_changes = tree.iter_changes(parent_tree)
                    list(builder.record_iter_changes(tree, parent_revid, iter_changes))
                    builder.finish_inventory()
                except:
                    builder.abort()
                    raise
                revidmap[revid] = builder.commit(rev.message)
                self.target.set_last_revision_info(parent_revno + 1, revidmap[revid])
                trace.mutter("lossily pushed revision %s -> %s", revid, revidmap[revid])
        finally:
            self.source.unlock()
        result.new_revno, result.new_revid = self.target.last_revision_info()
        result.revidmap = revidmap
        return result


class DummyForeignVcsBranchFormat(bzrbranch.BzrBranchFormat6):
    @classmethod
    def get_format_string(cls):
        return b"Branch for Testing"

    @property
    def _matchingcontroldir(self):
        return DummyForeignVcsDirFormat()

    def open(
        self,
        a_controldir,
        name=None,
        _found=False,
        ignore_fallbacks=False,
        found_repository=None,
    ):
        if name is None:
            name = a_controldir._get_selected_branch()
        if not _found:
            raise NotImplementedError
        try:
            transport = a_controldir.get_branch_transport(None, name=name)
            control_files = lockable_files.LockableFiles(
                transport, "lock", lockdir.LockDir
            )
            if found_repository is None:
                found_repository = a_controldir.find_repository()
            return DummyForeignVcsBranch(
                _format=self,
                _control_files=control_files,
                a_controldir=a_controldir,
                _repository=found_repository,
                name=name,
            )
        except _mod_transport.NoSuchFile as err:
            raise errors.NotBranchError(path=transport.base) from err


class DummyForeignVcsDirFormat(bzrdir.BzrDirMetaFormat1):
    """BzrDirFormat for the dummy foreign VCS."""

    @classmethod
    def get_format_string(cls):
        return b"A Dummy VCS Dir"

    @classmethod
    def get_format_description(cls):
        return "A Dummy VCS Dir"

    @classmethod
    def is_supported(cls):
        return True

    def get_branch_format(self):
        return DummyForeignVcsBranchFormat()

    @property
    def repository_format(self):
        return DummyForeignVcsRepositoryFormat()

    def initialize_on_transport(self, transport):
        """Initialize a new bzrdir in the base directory of a Transport."""
        # Since we don't have a .bzr directory, inherit the
        # mode from the root directory
        temp_control = lockable_files.LockableFiles(
            transport, "", lockable_files.TransportLock
        )
        temp_control._transport.mkdir(
            ".dummy",
            # FIXME: RBC 20060121 don't peek under
            # the covers
            mode=temp_control._dir_mode,
        )
        del temp_control
        bzrdir_transport = transport.clone(".dummy")
        # NB: no need to escape relative paths that are url safe.
        control_files = lockable_files.LockableFiles(
            bzrdir_transport, self._lock_file_name, self._lock_class
        )
        control_files.create_lock()
        return self.open(transport, _found=True)

    def _open(self, transport):
        return DummyForeignVcsDir(transport, self)


class DummyForeignVcsDir(bzrdir.BzrDirMeta1):
    def __init__(self, _transport, _format):
        self._format = _format
        self.transport = _transport.clone(".dummy")
        self.root_transport = _transport
        self._mode_check_done = False
        self._control_files = lockable_files.LockableFiles(
            self.transport, "lock", lockable_files.TransportLock
        )

    def create_workingtree(self):
        # dirstate requires a ".bzr" entry to exist
        self.root_transport.put_bytes(".bzr", b"foo")
        return super().create_workingtree()

    def open_branch(
        self,
        name=None,
        unsupported=False,
        ignore_fallbacks=True,
        possible_transports=None,
    ):
        if name is None:
            name = self._get_selected_branch()
        if name != "":
            raise controldir.NoColocatedBranchSupport(self)
        return self._format.get_branch_format().open(self, _found=True)

    def cloning_metadir(self, stacked=False):
        """Produce a metadir suitable for cloning with."""
        return controldir.format_registry.make_controldir("default")

    def checkout_metadir(self):
        return self.cloning_metadir()

    def sprout(
        self,
        url,
        revision_id=None,
        force_new_repo=False,
        recurse="down",
        possible_transports=None,
        accelerator_tree=None,
        hardlink=False,
        stacked=False,
        source_branch=None,
    ):
        # dirstate doesn't cope with accelerator_trees well
        # that have a different control dir
        return super().sprout(
            url=url,
            revision_id=revision_id,
            force_new_repo=force_new_repo,
            recurse=recurse,
            possible_transports=possible_transports,
            hardlink=hardlink,
            stacked=stacked,
            source_branch=source_branch,
        )


def register_dummy_foreign_for_test(testcase):
    controldir.ControlDirFormat.register_prober(DummyForeignProber)
    testcase.addCleanup(
        controldir.ControlDirFormat.unregister_prober, DummyForeignProber
    )
    repository.format_registry.register(DummyForeignVcsRepositoryFormat())
    testcase.addCleanup(
        repository.format_registry.remove, DummyForeignVcsRepositoryFormat()
    )
    branch.format_registry.register(DummyForeignVcsBranchFormat())
    testcase.addCleanup(branch.format_registry.remove, DummyForeignVcsBranchFormat())
    # We need to register the optimiser to make the dummy appears really
    # different from a regular bzr repository.
    branch.InterBranch.register_optimiser(InterToDummyVcsBranch)
    testcase.addCleanup(branch.InterBranch.unregister_optimiser, InterToDummyVcsBranch)


class DummyForeignProber(controldir.Prober):
    @classmethod
    def probe_transport(klass, transport):
        """Return the .bzrdir style format present in a directory."""
        if not transport.has(".dummy"):
            raise errors.NotBranchError(path=transport.base)
        return DummyForeignVcsDirFormat()

    @classmethod
    def known_formats(cls):
        return [DummyForeignVcsDirFormat()]


class ForeignVcsRegistryTests(tests.TestCase):
    """Tests for the ForeignVcsRegistry class."""

    def test_parse_revision_id_no_dash(self):
        reg = foreign.ForeignVcsRegistry()
        self.assertRaises(errors.InvalidRevisionId, reg.parse_revision_id, b"invalid")

    def test_parse_revision_id_unknown_mapping(self):
        reg = foreign.ForeignVcsRegistry()
        self.assertRaises(
            errors.InvalidRevisionId, reg.parse_revision_id, b"unknown-foreignrevid"
        )

    def test_parse_revision_id(self):
        reg = foreign.ForeignVcsRegistry()
        vcs = DummyForeignVcs()
        reg.register("dummy", vcs, "Dummy VCS")
        self.assertEqual(
            ((b"some", b"foreign", b"revid"), DummyForeignVcsMapping(vcs)),
            reg.parse_revision_id(b"dummy-v1:some-foreign-revid"),
        )


class ForeignRevisionTests(tests.TestCase):
    """Tests for the ForeignRevision class."""

    def test_create(self):
        mapp = DummyForeignVcsMapping(DummyForeignVcs())
        rev = foreign.ForeignRevision(
            (b"a", b"foreign", b"revid"),
            mapp,
            b"roundtripped-revid",
            parent_ids=[],
            message="",
            committer="",
            properties={},
            timestamp=0,
            timezone=0,
        )
        self.assertIs(None, rev.inventory_sha1)
        self.assertEqual((b"a", b"foreign", b"revid"), rev.foreign_revid)
        self.assertEqual(mapp, rev.mapping)


class DummyForeignVcsTests(tests.TestCaseWithTransport):
    """Very basic test for DummyForeignVcs."""

    def setUp(self):
        super().setUp()
        register_dummy_foreign_for_test(self)

    def test_create(self):
        """Test we can create dummies."""
        self.make_branch_and_tree("d", format=DummyForeignVcsDirFormat())
        dir = controldir.ControlDir.open("d")
        self.assertEqual(b"A Dummy VCS Dir", dir._format.get_format_string())
        dir.open_repository()
        dir.open_branch()
        dir.open_workingtree()

    def test_sprout(self):
        """Test we can clone dummies and that the format is not preserved."""
        self.make_branch_and_tree("d", format=DummyForeignVcsDirFormat())
        dir = controldir.ControlDir.open("d")
        newdir = dir.sprout("e")
        self.assertNotEqual(b"A Dummy VCS Dir", newdir._format.get_format_string())

    def test_push_not_supported(self):
        source_tree = self.make_branch_and_tree("source")
        target_tree = self.make_branch_and_tree(
            "target", format=DummyForeignVcsDirFormat()
        )
        self.assertRaises(
            errors.NoRoundtrippingSupport, source_tree.branch.push, target_tree.branch
        )

    def test_lossy_push_empty(self):
        source_tree = self.make_branch_and_tree("source")
        target_tree = self.make_branch_and_tree(
            "target", format=DummyForeignVcsDirFormat()
        )
        pushresult = source_tree.branch.push(target_tree.branch, lossy=True)
        self.assertEqual(revision.NULL_REVISION, pushresult.old_revid)
        self.assertEqual(revision.NULL_REVISION, pushresult.new_revid)
        self.assertEqual({}, pushresult.revidmap)

    def test_lossy_push_simple(self):
        source_tree = self.make_branch_and_tree("source")
        self.build_tree(["source/a", "source/b"])
        source_tree.add(["a", "b"])
        revid1 = source_tree.commit("msg")
        target_tree = self.make_branch_and_tree(
            "target", format=DummyForeignVcsDirFormat()
        )
        target_tree.branch.lock_write()
        try:
            pushresult = source_tree.branch.push(target_tree.branch, lossy=True)
        finally:
            target_tree.branch.unlock()
        self.assertEqual(revision.NULL_REVISION, pushresult.old_revid)
        self.assertEqual(
            {revid1: target_tree.branch.last_revision()}, pushresult.revidmap
        )
        self.assertEqual(pushresult.revidmap[revid1], pushresult.new_revid)
