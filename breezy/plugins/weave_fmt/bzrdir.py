# Copyright (C) 2006-2010 Canonical Ltd
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

"""Weave-era BzrDir formats."""

import contextlib
import os
from io import BytesIO

from ... import errors, osutils, trace
from ...bzr import lockable_files
from ...bzr.bzrdir import BzrDir, BzrDirFormat, BzrDirMetaFormat1
from ...controldir import (
    ControlDir,
    Converter,
    MustHaveWorkingTree,
    NoColocatedBranchSupport,
    format_registry,
)
from ...i18n import gettext
from ...lazy_import import lazy_import
from ...transport import NoSuchFile, get_transport, local

lazy_import(
    globals(),
    """
from breezy import (
    branch as _mod_branch,,
    graph,
    lockdir,
    revision as _mod_revision,
    ui,
    urlutils,
    )
from breezy.bzr import (
    versionedfile,
    weave,
    )
from breezy.plugins.weave_fmt.store.versioned import VersionedFileStore
from breezy.transactions import WriteTransaction
""",
)


class BzrDirFormatAllInOne(BzrDirFormat):
    """Common class for formats before meta-dirs."""

    fixed_components = True

    def initialize_on_transport_ex(
        self,
        transport,
        use_existing_dir=False,
        create_prefix=False,
        force_new_repo=False,
        stacked_on=None,
        stack_on_pwd=None,
        repo_format_name=None,
        make_working_trees=None,
        shared_repo=False,
    ):
        """See ControlDir.initialize_on_transport_ex."""
        require_stacking = stacked_on is not None
        # Format 5 cannot stack, but we've been asked to - actually init
        # a Meta1Dir
        if require_stacking:
            format = BzrDirMetaFormat1()
            return format.initialize_on_transport_ex(
                transport,
                use_existing_dir=use_existing_dir,
                create_prefix=create_prefix,
                force_new_repo=force_new_repo,
                stacked_on=stacked_on,
                stack_on_pwd=stack_on_pwd,
                repo_format_name=repo_format_name,
                make_working_trees=make_working_trees,
                shared_repo=shared_repo,
            )
        return BzrDirFormat.initialize_on_transport_ex(
            self,
            transport,
            use_existing_dir=use_existing_dir,
            create_prefix=create_prefix,
            force_new_repo=force_new_repo,
            stacked_on=stacked_on,
            stack_on_pwd=stack_on_pwd,
            repo_format_name=repo_format_name,
            make_working_trees=make_working_trees,
            shared_repo=shared_repo,
        )

    @classmethod
    def from_string(cls, format_string):
        """Create a format object from a format string.

        Args:
            format_string: The format string to parse.

        Returns:
            An instance of this format class.

        Raises:
            AssertionError: If the format string doesn't match this format.
        """
        if format_string != cls.get_format_string():
            raise AssertionError(f"unexpected format string {format_string!r}")
        return cls()


class BzrDirFormat5(BzrDirFormatAllInOne):
    """Bzr control format 5.

    This format is a combined format for working tree, branch and repository.
    It has:
     - Format 2 working trees [always]
     - Format 4 branches [always]
     - Format 5 repositories [always]
       Unhashed stores in the repository.
    """

    _lock_class = lockable_files.TransportLock

    def __eq__(self, other):
        """Check equality with another format.

        Args:
            other: The format to compare with.

        Returns:
            bool: True if other is the same type as self.
        """
        return isinstance(self, type(other))

    @classmethod
    def get_format_string(cls):
        """See BzrDirFormat.get_format_string()."""
        return b"Bazaar-NG branch, format 5\n"

    def get_branch_format(self):
        """Get the branch format for this BzrDir format.

        Returns:
            BzrBranchFormat4 instance.
        """
        from .branch import BzrBranchFormat4

        return BzrBranchFormat4()

    def get_format_description(self):
        """See ControlDirFormat.get_format_description()."""
        return "All-in-one format 5"

    def get_converter(self, format=None):
        """See ControlDirFormat.get_converter()."""
        # there is one and only one upgrade path here.
        return ConvertBzrDir5To6()

    def _initialize_for_clone(self, url):
        """Initialize a directory for cloning.

        Args:
            url: The URL to initialize at.

        Returns:
            The initialized control directory.
        """
        return self.initialize_on_transport(get_transport(url), _cloning=True)

    def initialize_on_transport(self, transport, _cloning=False):
        """Format 5 dirs always have working tree, branch and repository.

        Except when they are being cloned.
        """
        from .branch import BzrBranchFormat4
        from .repository import RepositoryFormat5

        result = super().initialize_on_transport(transport)
        RepositoryFormat5().initialize(result, _internal=True)
        if not _cloning:
            BzrBranchFormat4().initialize(result)
            result._init_workingtree()
        return result

    def network_name(self):
        """Get the network name for this format.

        Returns:
            The format string used for network identification.
        """
        return self.get_format_string()

    def _open(self, transport):
        """Open an existing BzrDir5 at the given transport.

        Args:
            transport: The transport to open from.

        Returns:
            A BzrDir5 instance.
        """
        return BzrDir5(transport, self)

    def __return_repository_format(self):
        """Get the repository format for this BzrDir format.

        This method exists to avoid circular imports.

        Returns:
            RepositoryFormat5 instance.
        """
        from .repository import RepositoryFormat5

        return RepositoryFormat5()

    repository_format = property(__return_repository_format)


class BzrDirFormat6(BzrDirFormatAllInOne):
    """Bzr control format 6.

    This format is a combined format for working tree, branch and repository.
    It has:
     - Format 2 working trees [always]
     - Format 4 branches [always]
     - Format 6 repositories [always]
    """

    _lock_class = lockable_files.TransportLock

    def __eq__(self, other):
        """Check equality with another format.

        Args:
            other: The format to compare with.

        Returns:
            bool: True if other is the same type as self.
        """
        return isinstance(self, type(other))

    @classmethod
    def get_format_string(cls):
        """See BzrDirFormat.get_format_string()."""
        return b"Bazaar-NG branch, format 6\n"

    def get_format_description(self):
        """See ControlDirFormat.get_format_description()."""
        return "All-in-one format 6"

    def get_branch_format(self):
        """Get the branch format for this BzrDir format.

        Returns:
            BzrBranchFormat4 instance.
        """
        from .branch import BzrBranchFormat4

        return BzrBranchFormat4()

    def get_converter(self, format=None):
        """See ControlDirFormat.get_converter()."""
        # there is one and only one upgrade path here.
        return ConvertBzrDir6ToMeta()

    def _initialize_for_clone(self, url):
        """Initialize a directory for cloning.

        Args:
            url: The URL to initialize at.

        Returns:
            The initialized control directory.
        """
        return self.initialize_on_transport(get_transport(url), _cloning=True)

    def initialize_on_transport(self, transport, _cloning=False):
        """Format 6 dirs always have working tree, branch and repository.

        Except when they are being cloned.
        """
        from .branch import BzrBranchFormat4
        from .repository import RepositoryFormat6

        result = super().initialize_on_transport(transport)
        RepositoryFormat6().initialize(result, _internal=True)
        if not _cloning:
            BzrBranchFormat4().initialize(result)
            result._init_workingtree()
        return result

    def network_name(self):
        """Get the network name for this format.

        Returns:
            The format string used for network identification.
        """
        return self.get_format_string()

    def _open(self, transport):
        """Open an existing BzrDir6 at the given transport.

        Args:
            transport: The transport to open from.

        Returns:
            A BzrDir6 instance.
        """
        return BzrDir6(transport, self)

    def __return_repository_format(self):
        """Get the repository format for this BzrDir format.

        This method exists to avoid circular imports.

        Returns:
            RepositoryFormat6 instance.
        """
        from .repository import RepositoryFormat6

        return RepositoryFormat6()

    repository_format = property(__return_repository_format)


class ConvertBzrDir4To5(Converter):
    """Converts format 4 bzr dirs to format 5."""

    def __init__(self):
        """Initialize the converter.

        Sets up tracking for converted revisions, absent revisions,
        text count, and revision mapping.
        """
        super().__init__()
        self.converted_revs = set()
        self.absent_revisions = set()
        self.text_count = 0
        self.revisions = {}

    def convert(self, to_convert, pb):
        """Convert a format 4 bzrdir to format 5.

        Args:
            to_convert: The control directory to convert.
            pb: Progress bar for reporting progress.

        Returns:
            The converted control directory.
        """
        self.controldir = to_convert
        with ui.ui_factory.nested_progress_bar() as self.pb:
            ui.ui_factory.note(gettext("starting upgrade from format 4 to 5"))
            if isinstance(self.controldir.transport, local.LocalTransport):
                self.controldir.get_workingtree_transport(None).delete("stat-cache")
            self._convert_to_weaves()
            return ControlDir.open(self.controldir.user_url)

    def _convert_to_weaves(self):
        """Convert the repository storage from text stores to weaves.

        This performs the main conversion work, reading all revisions and
        texts from the old format and writing them as weaves.
        """
        ui.ui_factory.note(
            gettext(
                "note: upgrade may be faster if all store files are ungzipped first"
            )
        )
        try:
            # TODO permissions
            stat = self.controldir.transport.stat("weaves")
            if not S_ISDIR(stat.st_mode):
                self.controldir.transport.delete("weaves")
                self.controldir.transport.mkdir("weaves")
        except NoSuchFile:
            self.controldir.transport.mkdir("weaves")
        # deliberately not a WeaveFile as we want to build it up slowly.
        self.inv_weave = weave.Weave("inventory")
        # holds in-memory weaves for all files
        self.text_weaves = {}
        self.controldir.transport.delete("branch-format")
        self.branch = self.controldir.open_branch()
        self._convert_working_inv()
        rev_history = self.branch._revision_history()
        # to_read is a stack holding the revisions we still need to process;
        # appending to it adds new highest-priority revisions
        self.known_revisions = set(rev_history)
        self.to_read = rev_history[-1:]
        while self.to_read:
            rev_id = self.to_read.pop()
            if rev_id not in self.revisions and rev_id not in self.absent_revisions:
                self._load_one_rev(rev_id)
        self.pb.clear()
        to_import = self._make_order()
        for i, rev_id in enumerate(to_import):
            self.pb.update(gettext("converting revision"), i, len(to_import))
            self._convert_one_rev(rev_id)
        self.pb.clear()
        self._write_all_weaves()
        self._write_all_revs()
        ui.ui_factory.note(gettext("upgraded to weaves:"))
        ui.ui_factory.note(
            "  " + gettext("%6d revisions and inventories") % len(self.revisions)
        )
        ui.ui_factory.note(
            "  " + gettext("%6d revisions not present") % len(self.absent_revisions)
        )
        ui.ui_factory.note("  " + gettext("%6d texts") % self.text_count)
        self._cleanup_spare_files_after_format4()
        self.branch._transport.put_bytes(
            "branch-format",
            BzrDirFormat5().get_format_string(),
            mode=self.controldir._get_file_mode(),
        )

    def _cleanup_spare_files_after_format4(self):
        """Remove obsolete files after format 4 conversion.

        Deletes old format 4 specific files that are no longer needed
        in format 5.
        """
        # FIXME working tree upgrade foo.
        for n in "merged-patches", "pending-merged-patches":
            try:
                ## assert os.path.getsize(p) == 0
                self.controldir.transport.delete(n)
            except NoSuchFile:
                pass
        self.controldir.transport.delete_tree("inventory-store")
        self.controldir.transport.delete_tree("text-store")

    def _convert_working_inv(self):
        """Convert the working inventory from format 4 to format 5.

        Reads the inventory using the format 4 serializer and writes it
        back using the format 5 serializer.
        """
        from .xml4 import inventory_serializer_v4

        inv = inventory_serializer_v4.read_inventory(
            self.branch._transport.get("inventory")
        )
        f = BytesIO()
        from ...bzr.xml5 import inventory_serializer_v5

        inventory_serializer_v5.write_inventory(inv, f, working=True)
        self.branch._transport.put_bytes(
            "inventory", f.getvalue(), mode=self.controldir._get_file_mode()
        )

    def _write_all_weaves(self):
        """Write all accumulated weaves to disk.

        Writes both the text weaves and the inventory weave that have been
        built up in memory during conversion.
        """
        controlweaves = VersionedFileStore(
            self.controldir.transport,
            prefixed=False,
            versionedfile_class=weave.WeaveFile,
        )
        weave_transport = self.controldir.transport.clone("weaves")
        weaves = VersionedFileStore(
            weave_transport, prefixed=False, versionedfile_class=weave.WeaveFile
        )
        transaction = WriteTransaction()

        try:
            for i, (file_id, file_weave) in enumerate(self.text_weaves.items()):
                self.pb.update(gettext("writing weave"), i, len(self.text_weaves))
                weaves._put_weave(file_id, file_weave, transaction)
            self.pb.update(gettext("inventory"), 0, 1)
            controlweaves._put_weave(b"inventory", self.inv_weave, transaction)
            self.pb.update(gettext("inventory"), 1, 1)
        finally:
            self.pb.clear()

    def _write_all_revs(self):
        """Write all revisions out in new form.

        Recreates the revision store using the format 5 serializer for all
        converted revisions.
        """
        self.controldir.transport.delete_tree("revision-store")
        self.controldir.transport.mkdir("revision-store")
        revision_transport = self.controldir.transport.clone("revision-store")
        # TODO permissions
        from ...bzr.xml5 import revision_serializer_v5
        from .repository import RevisionTextStore

        revision_store = RevisionTextStore(
            revision_transport,
            revision_serializer_v5,
            False,
            versionedfile.PrefixMapper(),
            lambda: True,
            lambda: True,
        )
        try:
            for i, rev_id in enumerate(self.converted_revs):
                self.pb.update(gettext("write revision"), i, len(self.converted_revs))
                lines = revision_serializer_v5.write_revision_to_lines(
                    self.revisions[rev_id]
                )
                key = (rev_id,)
                revision_store.add_lines(key, None, lines)
        finally:
            self.pb.clear()

    def _load_one_rev(self, rev_id):
        """Load a revision object into memory.

        Any parents not either loaded or abandoned get queued to be
        loaded.

        Args:
            rev_id: The revision ID to load.
        """
        self.pb.update(
            gettext("loading revision"), len(self.revisions), len(self.known_revisions)
        )
        if not self.branch.repository.has_revision(rev_id):
            self.pb.clear()
            ui.ui_factory.note(
                gettext(
                    "revision {%s} not present in branch; will be converted as a ghost"
                )
                % rev_id
            )
            self.absent_revisions.add(rev_id)
        else:
            rev = self.branch.repository.get_revision(rev_id)
            for parent_id in rev.parent_ids:
                self.known_revisions.add(parent_id)
                self.to_read.append(parent_id)
            self.revisions[rev_id] = rev

    def _load_old_inventory(self, rev_id):
        """Load an inventory in the old format.

        Args:
            rev_id: The revision ID to load the inventory for.

        Returns:
            The loaded inventory object.
        """
        from .xml4 import inventory_serializer_v4

        with self.branch.repository.inventory_store.get(rev_id) as f:
            inv = inventory_serializer_v4.read_inventory(f)
        inv.revision_id = rev_id
        self.revisions[rev_id]
        return inv

    def _load_updated_inventory(self, rev_id):
        """Load an inventory that has been converted to the new format.

        Args:
            rev_id: The revision ID to load the inventory for.

        Returns:
            The loaded inventory object.
        """
        from ...bzr.xml5 import inventory_serializer_v5

        inv_xml = self.inv_weave.get_lines(rev_id)
        inv = inventory_serializer_v5.read_inventory_from_lines(inv_xml, rev_id)
        return inv

    def _convert_one_rev(self, rev_id):
        """Convert revision and all referenced objects to new format.

        Args:
            rev_id: The revision ID to convert.
        """
        rev = self.revisions[rev_id]
        inv = self._load_old_inventory(rev_id)
        present_parents = [p for p in rev.parent_ids if p not in self.absent_revisions]
        self._convert_revision_contents(rev, inv, present_parents)
        self._store_new_inv(rev, inv, present_parents)
        self.converted_revs.add(rev_id)

    def _store_new_inv(self, rev, inv, present_parents):
        """Store the inventory in the new weave format.

        Args:
            rev: The revision object.
            inv: The inventory to store.
            present_parents: List of parent revision IDs that are present.
        """
        from ...bzr.xml5 import inventory_serializer_v5

        new_inv_xml = inventory_serializer_v5.write_inventory_to_lines(inv)
        new_inv_sha1 = osutils.sha_strings(new_inv_xml)
        self.inv_weave.add_lines(rev.revision_id, present_parents, new_inv_xml)
        rev.inventory_sha1 = new_inv_sha1

    def _convert_revision_contents(self, rev, inv, present_parents):
        """Convert all the files within a revision.

        Also upgrade the inventory to refer to the text revision ids.

        Args:
            rev: The revision object.
            inv: The inventory for this revision.
            present_parents: List of parent revision IDs that are present.
        """
        rev_id = rev.revision_id
        trace.mutter("converting texts of revision {%s}", rev_id)
        parent_invs = list(map(self._load_updated_inventory, present_parents))
        entries = inv.iter_entries()
        next(entries)
        for _path, ie in entries:
            inv.delete(ie.file_id)
            inv.add(self._convert_file_version(rev, ie, parent_invs))

    def _convert_file_version(self, rev, ie, parent_invs):
        """Convert one version of one file.

        The file needs to be added into the weave if it is a merge
        of >=2 parents or if it's changed from its parent.

        Args:
            rev: The revision object.
            ie: The inventory entry for the file.
            parent_invs: List of parent inventories.

        Returns:
            The updated inventory entry.
        """
        file_id = ie.file_id
        rev_id = rev.revision_id
        w = self.text_weaves.get(file_id)
        if w is None:
            w = weave.Weave(file_id)
            self.text_weaves[file_id] = w
        parent_candiate_entries = ie.parent_candidates(parent_invs)
        heads = graph.Graph(self).heads(parent_candiate_entries)
        # XXX: Note that this is unordered - and this is tolerable because
        # the previous code was also unordered.
        previous_entries = {head: parent_candiate_entries[head] for head in heads}
        return self.snapshot_ie(previous_entries, ie, w, rev_id)

    def get_parent_map(self, revision_ids):
        """Get a map of revision IDs to their parents.

        Args:
            revision_ids: Revision IDs to get parents for.

        Returns:
            Dict mapping revision IDs to their parent revision objects.
        """
        return {
            revision_id: self.revisions[revision_id]
            for revision_id in revision_ids
            if revision_id in self.revisions
        }

    def snapshot_ie(self, previous_revisions, ie, w, rev_id):
        """Snapshot an inventory entry into a weave.

        Args:
            previous_revisions: Dict of previous revisions for this entry.
            ie: The inventory entry to snapshot.
            w: The weave to add the snapshot to.
            rev_id: The revision ID for this snapshot.

        Returns:
            The updated inventory entry.
        """
        # TODO: convert this logic, which is ~= snapshot to
        # a call to:. This needs the path figured out. rather than a work_tree
        # a v4 revision_tree can be given, or something that looks enough like
        # one to give the file content to the entry if it needs it.
        # and we need something that looks like a weave store for snapshot to
        # save against.
        # ie.snapshot(rev, PATH, previous_revisions, REVISION_TREE, InMemoryWeaveStore(self.text_weaves))
        if len(previous_revisions) == 1:
            previous_ie = next(iter(previous_revisions.values()))
            if ie._unchanged(previous_ie):
                return ie.derive(revision=previous_ie.revision)
        if ie.has_text():
            with self.branch.repository._text_store.get(ie.text_id) as f:
                file_lines = f.readlines()
            w.add_lines(rev_id, previous_revisions, file_lines)
            self.text_count += 1
        else:
            w.add_lines(rev_id, previous_revisions, [])
        return ie.derive(revision=rev_id)

    def _make_order(self):
        """Return a suitable order for importing revisions.

        The order must be such that an revision is imported after all
        its (present) parents.

        Returns:
            List of revision IDs in topological order.
        """
        todo = set(self.revisions)
        done = self.absent_revisions.copy()
        order = []
        while todo:
            # scan through looking for a revision whose parents
            # are all done
            for rev_id in sorted(todo):
                rev = self.revisions[rev_id]
                parent_ids = set(rev.parent_ids)
                if parent_ids.issubset(done):
                    # can take this one now
                    order.append(rev_id)
                    todo.remove(rev_id)
                    done.add(rev_id)
        return order


class ConvertBzrDir5To6(Converter):
    """Converts format 5 bzr dirs to format 6."""

    def convert(self, to_convert, pb):
        """Convert a format 5 bzrdir to format 6.

        Args:
            to_convert: The control directory to convert.
            pb: Progress bar for reporting progress.

        Returns:
            The converted control directory.
        """
        self.controldir = to_convert
        with ui.ui_factory.nested_progress_bar():
            ui.ui_factory.note(gettext("starting upgrade from format 5 to 6"))
            self._convert_to_prefixed()
            return ControlDir.open(self.controldir.user_url)

    def _convert_to_prefixed(self):
        """Convert stores to use hash-prefixed directories.

        This reorganizes the storage layout to use subdirectories based on
        file hashes for better scalability.
        """
        from .store import TransportStore

        self.controldir.transport.delete("branch-format")
        for store_name in ["weaves", "revision-store"]:
            ui.ui_factory.note(gettext("adding prefixes to %s") % store_name)
            store_transport = self.controldir.transport.clone(store_name)
            store = TransportStore(store_transport, prefixed=True)
            for urlfilename in store_transport.list_dir("."):
                filename = urlutils.unescape(urlfilename)
                if (
                    filename.endswith(".weave")
                    or filename.endswith(".gz")
                    or filename.endswith(".sig")
                ):
                    file_id, suffix = os.path.splitext(filename)
                else:
                    file_id = filename
                    suffix = ""
                new_name = store._mapper.map((file_id.encode("utf-8"),)) + suffix
                # FIXME keep track of the dirs made RBC 20060121
                try:
                    store_transport.move(filename, new_name)
                except NoSuchFile:  # catches missing dirs strangely enough
                    store_transport.mkdir(osutils.dirname(new_name))
                    store_transport.move(filename, new_name)
        self.controldir.transport.put_bytes(
            "branch-format",
            BzrDirFormat6().get_format_string(),
            mode=self.controldir._get_file_mode(),
        )


class ConvertBzrDir6ToMeta(Converter):
    """Converts format 6 bzr dirs to metadirs."""

    def convert(self, to_convert, pb):
        """Convert a format 6 bzrdir to metadir format.

        Args:
            to_convert: The control directory to convert.
            pb: Progress bar for reporting progress.

        Returns:
            The converted control directory.
        """
        from ...bzr.fullhistory import BzrBranchFormat5
        from .repository import RepositoryFormat7

        self.controldir = to_convert
        self.pb = ui.ui_factory.nested_progress_bar()
        self.count = 0
        self.total = 20  # the steps we know about
        self.garbage_inventories = []
        self.dir_mode = self.controldir._get_dir_mode()
        self.file_mode = self.controldir._get_file_mode()

        ui.ui_factory.note(gettext("starting upgrade from format 6 to metadir"))
        self.controldir.transport.put_bytes(
            "branch-format", b"Converting to format 6", mode=self.file_mode
        )
        # its faster to move specific files around than to open and use the apis...
        # first off, nuke ancestry.weave, it was never used.
        try:
            self.step(gettext("Removing ancestry.weave"))
            self.controldir.transport.delete("ancestry.weave")
        except NoSuchFile:
            pass
        # find out whats there
        self.step(gettext("Finding branch files"))
        last_revision = self.controldir.open_branch().last_revision()
        bzrcontents = self.controldir.transport.list_dir(".")
        for name in bzrcontents:
            if name.startswith("basis-inventory."):
                self.garbage_inventories.append(name)
        # create new directories for repository, working tree and branch
        repository_names = [
            ("inventory.weave", True),
            ("revision-store", True),
            ("weaves", True),
        ]
        self.step(gettext("Upgrading repository") + "  ")
        self.controldir.transport.mkdir("repository", mode=self.dir_mode)
        self.make_lock("repository")
        # we hard code the formats here because we are converting into
        # the meta format. The meta format upgrader can take this to a
        # future format within each component.
        self.put_format("repository", RepositoryFormat7())
        for entry in repository_names:
            self.move_entry("repository", entry)

        self.step(gettext("Upgrading branch") + "      ")
        self.controldir.transport.mkdir("branch", mode=self.dir_mode)
        self.make_lock("branch")
        self.put_format("branch", BzrBranchFormat5())
        branch_files = [
            ("revision-history", True),
            ("branch-name", True),
            ("parent", False),
        ]
        for entry in branch_files:
            self.move_entry("branch", entry)

        checkout_files = [
            ("pending-merges", True),
            ("inventory", True),
            ("stat-cache", False),
        ]
        # If a mandatory checkout file is not present, the branch does not have
        # a functional checkout. Do not create a checkout in the converted
        # branch.
        for name, mandatory in checkout_files:
            if mandatory and name not in bzrcontents:
                has_checkout = False
                break
        else:
            has_checkout = True
        if not has_checkout:
            ui.ui_factory.note(gettext("No working tree."))
            # If some checkout files are there, we may as well get rid of them.
            for name, _mandatory in checkout_files:
                if name in bzrcontents:
                    self.controldir.transport.delete(name)
        else:
            from ...bzr.workingtree_3 import WorkingTreeFormat3

            self.step(gettext("Upgrading working tree"))
            self.controldir.transport.mkdir("checkout", mode=self.dir_mode)
            self.make_lock("checkout")
            self.put_format("checkout", WorkingTreeFormat3())
            for path in self.garbage_inventories:
                self.controldir.transport.delete(path)
            for entry in checkout_files:
                self.move_entry("checkout", entry)
            if last_revision is not None:
                self.controldir.transport.put_bytes(
                    "checkout/last-revision", last_revision
                )
        self.controldir.transport.put_bytes(
            "branch-format",
            BzrDirMetaFormat1().get_format_string(),
            mode=self.file_mode,
        )
        self.pb.finished()
        return ControlDir.open(self.controldir.user_url)

    def make_lock(self, name):
        """Make a lock for the new control dir name.

        Args:
            name: The name of the subdirectory to create a lock for.
        """
        self.step(gettext("Make %s lock") % name)
        ld = lockdir.LockDir(
            self.controldir.transport,
            f"{name}/lock",
            file_modebits=self.file_mode,
            dir_modebits=self.dir_mode,
        )
        ld.create()

    def move_entry(self, new_dir, entry):
        """Move then entry name into new_dir.

        Args:
            new_dir: The target directory name.
            entry: Tuple of (name, mandatory) for the entry to move.

        Raises:
            NoSuchFile: If a mandatory entry is not found.
        """
        name = entry[0]
        mandatory = entry[1]
        self.step(gettext("Moving %s") % name)
        try:
            self.controldir.transport.move(name, f"{new_dir}/{name}")
        except NoSuchFile:
            if mandatory:
                raise

    def put_format(self, dirname, format):
        """Write a format marker file.

        Args:
            dirname: The directory to write the format file in.
            format: The format object whose format string to write.
        """
        self.controldir.transport.put_bytes(
            f"{dirname}/format", format.get_format_string(), self.file_mode
        )


class BzrDirFormat4(BzrDirFormat):
    """Bzr dir format 4.

    This format is a combined format for working tree, branch and repository.
    It has:
     - Format 1 working trees [always]
     - Format 4 branches [always]
     - Format 4 repositories [always]

    This format is deprecated: it indexes texts using a text it which is
    removed in format 5; write support for this format has been removed.
    """

    _lock_class = lockable_files.TransportLock

    def __eq__(self, other):
        """Check equality with another format.

        Args:
            other: The format to compare with.

        Returns:
            bool: True if other is the same type as self.
        """
        return isinstance(self, type(other))

    @classmethod
    def get_format_string(cls):
        """See BzrDirFormat.get_format_string()."""
        return b"Bazaar-NG branch, format 0.0.4\n"

    def get_format_description(self):
        """See ControlDirFormat.get_format_description()."""
        return "All-in-one format 4"

    def get_converter(self, format=None):
        """See ControlDirFormat.get_converter()."""
        # there is one and only one upgrade path here.
        return ConvertBzrDir4To5()

    def initialize_on_transport(self, transport):
        """Format 4 branches cannot be created.

        Args:
            transport: The transport to initialize on.

        Raises:
            UninitializableFormat: Always raised as format 4 is deprecated.
        """
        raise errors.UninitializableFormat(self)

    def is_supported(self):
        """Format 4 is not supported.

        It is not supported because the model changed from 4 to 5 and the
        conversion logic is expensive - so doing it on the fly was not
        feasible.
        """
        return False

    def network_name(self):
        """Get the network name for this format.

        Returns:
            The format string used for network identification.
        """
        return self.get_format_string()

    def _open(self, transport):
        """Open an existing BzrDir4 at the given transport.

        Args:
            transport: The transport to open from.

        Returns:
            A BzrDir4 instance.
        """
        return BzrDir4(transport, self)

    def __return_repository_format(self):
        """Get the repository format for this BzrDir format.

        This method exists to avoid circular imports.

        Returns:
            RepositoryFormat4 instance.
        """
        from .repository import RepositoryFormat4

        return RepositoryFormat4()

    repository_format = property(__return_repository_format)

    @classmethod
    def from_string(cls, format_string):
        """Create a format object from a format string.

        Args:
            format_string: The format string to parse.

        Returns:
            An instance of this format class.

        Raises:
            AssertionError: If the format string doesn't match this format.
        """
        if format_string != cls.get_format_string():
            raise AssertionError(f"unexpected format string {format_string!r}")
        return cls()


class BzrDirPreSplitOut(BzrDir):
    """A common class for the all-in-one formats."""

    def __init__(self, _transport, _format):
        """Initialize a pre-split-out bzrdir.

        Args:
            _transport: The transport for accessing this bzrdir.
            _format: The format of this bzrdir.
        """
        super().__init__(_transport, _format)
        self._control_files = lockable_files.LockableFiles(
            self.get_branch_transport(None),
            self._format._lock_file_name,
            self._format._lock_class,
        )

    def break_lock(self):
        """Break any locks on this bzrdir.

        Raises:
            NotImplementedError: Pre-splitout bzrdirs do not suffer from stale locks.
        """
        raise NotImplementedError(self.break_lock)

    def cloning_metadir(self, require_stacking=False):
        """Produce a metadir suitable for cloning with.

        Args:
            require_stacking: If True, return a format that supports stacking.

        Returns:
            A BzrDirFormat suitable for cloning.
        """
        if require_stacking:
            return format_registry.make_controldir("1.6")
        return self._format.__class__()

    def clone(
        self,
        url,
        revision_id=None,
        force_new_repo=False,
        preserve_stacking=False,
        tag_selector=None,
    ):
        """See ControlDir.clone().

        force_new_repo has no effect, since this family of formats always
        require a new repository.
        preserve_stacking has no effect, since no source branch using this
        family of formats can be stacked, so there is no stacking to preserve.
        """
        self._make_tail(url)
        result = self._format._initialize_for_clone(url)
        self.open_repository().clone(result, revision_id=revision_id)
        from_branch = self.open_branch()
        from_branch.clone(result, revision_id=revision_id, tag_selector=tag_selector)
        try:
            tree = self.open_workingtree()
        except errors.NotLocalUrl:
            # make a new one, this format always has to have one.
            result._init_workingtree()
        else:
            tree.clone(result)
        return result

    def create_branch(self, name=None, repository=None, append_revisions_only=None):
        """See ControlDir.create_branch."""
        if repository is not None:
            raise NotImplementedError(
                f"create_branch(repository=<not None>) on {self!r}"
            )
        return self._format.get_branch_format().initialize(
            self, name=name, append_revisions_only=append_revisions_only
        )

    def destroy_branch(self, name=None):
        """Destroy the branch in this bzrdir.

        Args:
            name: The name of the branch (must be None for this format).

        Raises:
            UnsupportedOperation: This format doesn't support destroying branches.
        """
        raise errors.UnsupportedOperation(self.destroy_branch, self)

    def create_repository(self, shared=False):
        """See ControlDir.create_repository."""
        if shared:
            raise errors.IncompatibleFormat("shared repository", self._format)
        return self.open_repository()

    def destroy_repository(self):
        """Destroy the repository in this bzrdir.

        Raises:
            UnsupportedOperation: This format doesn't support destroying repositories.
        """
        raise errors.UnsupportedOperation(self.destroy_repository, self)

    def create_workingtree(
        self, revision_id=None, from_branch=None, accelerator_tree=None, hardlink=False
    ):
        """See ControlDir.create_workingtree."""
        # The workingtree is sometimes created when the bzrdir is created,
        # but not when cloning.

        # this looks buggy but is not -really-
        # because this format creates the workingtree when the bzrdir is
        # created
        # clone and sprout will have set the revision_id
        # and that will have set it for us, its only
        # specific uses of create_workingtree in isolation
        # that can do wonky stuff here, and that only
        # happens for creating checkouts, which cannot be
        # done on this format anyway. So - acceptable wart.
        if hardlink:
            warning(f"can't support hardlinked working trees in {self!r}")
        try:
            result = self.open_workingtree(recommend_upgrade=False)
        except NoSuchFile:
            result = self._init_workingtree()
        if revision_id is not None:
            if revision_id == _mod_revision.NULL_REVISION:
                result.set_parent_ids([])
            else:
                result.set_parent_ids([revision_id])
        return result

    def _init_workingtree(self):
        """Initialize a working tree in this bzrdir.

        Returns:
            The initialized WorkingTree object.
        """
        from .workingtree import WorkingTreeFormat2

        try:
            return WorkingTreeFormat2().initialize(self)
        except errors.NotLocalUrl:
            # Even though we can't access the working tree, we need to
            # create its control files.
            return WorkingTreeFormat2()._stub_initialize_on_transport(
                self.transport, self._control_files._file_mode
            )

    def destroy_workingtree(self):
        """Destroy the working tree in this bzrdir.

        Raises:
            UnsupportedOperation: This format doesn't support destroying working trees.
        """
        raise errors.UnsupportedOperation(self.destroy_workingtree, self)

    def destroy_workingtree_metadata(self):
        """Destroy the working tree metadata in this bzrdir.

        Raises:
            UnsupportedOperation: This format doesn't support destroying working tree metadata.
        """
        raise errors.UnsupportedOperation(self.destroy_workingtree_metadata, self)

    def get_branch_transport(self, branch_format, name=None):
        """See BzrDir.get_branch_transport()."""
        if name:
            raise NoColocatedBranchSupport(self)
        if branch_format is None:
            return self.transport
        try:
            branch_format.get_format_string()
        except NotImplementedError:
            return self.transport
        raise errors.IncompatibleFormat(branch_format, self._format)

    def get_repository_transport(self, repository_format):
        """See BzrDir.get_repository_transport()."""
        if repository_format is None:
            return self.transport
        try:
            repository_format.get_format_string()
        except NotImplementedError:
            return self.transport
        raise errors.IncompatibleFormat(repository_format, self._format)

    def get_workingtree_transport(self, workingtree_format):
        """See BzrDir.get_workingtree_transport()."""
        if workingtree_format is None:
            return self.transport
        try:
            workingtree_format.get_format_string()
        except NotImplementedError:
            return self.transport
        raise errors.IncompatibleFormat(workingtree_format, self._format)

    def needs_format_conversion(self, format):
        """Check if this bzrdir needs conversion to a given format.

        Args:
            format: The target format to check against.

        Returns:
            bool: True if conversion is needed.
        """
        # if the format is not the same as the system default,
        # an upgrade is needed.
        return not isinstance(self._format, format.__class__)

    def open_branch(
        self,
        name=None,
        unsupported=False,
        ignore_fallbacks=False,
        possible_transports=None,
    ):
        """See ControlDir.open_branch."""
        from .branch import BzrBranchFormat4

        format = BzrBranchFormat4()
        format.check_support_status(unsupported)
        return format.open(
            self, name, _found=True, possible_transports=possible_transports
        )

    def sprout(
        self,
        url,
        revision_id=None,
        force_new_repo=False,
        recurse=None,
        possible_transports=None,
        accelerator_tree=None,
        hardlink=False,
        stacked=False,
        create_tree_if_local=True,
        source_branch=None,
    ):
        """See ControlDir.sprout()."""
        if source_branch is not None:
            my_branch = self.open_branch()
            if source_branch.base != my_branch.base:
                raise AssertionError(
                    f"source branch {source_branch!r} is not within {self!r} with branch {my_branch!r}"
                )
        if stacked:
            raise _mod_branch.UnstackableBranchFormat(
                self._format, self.root_transport.base
            )
        if not create_tree_if_local:
            raise MustHaveWorkingTree(self._format, self.root_transport.base)
        from .workingtree import WorkingTreeFormat2

        self._make_tail(url)
        result = self._format._initialize_for_clone(url)
        with contextlib.suppress(errors.NoRepositoryPresent):
            self.open_repository().clone(result, revision_id=revision_id)
        with contextlib.suppress(errors.NotBranchError):
            self.open_branch().sprout(result, revision_id=revision_id)

        # we always want a working tree
        WorkingTreeFormat2().initialize(
            result, accelerator_tree=accelerator_tree, hardlink=hardlink
        )
        return result

    def set_branch_reference(self, target_branch, name=None):
        """Set a branch reference.

        Args:
            target_branch: The branch to reference.
            name: The name of the branch (must be None for this format).

        Raises:
            NoColocatedBranchSupport: If name is not None.
            IncompatibleFormat: This format doesn't support branch references.
        """
        from ...bzr.branch import BranchReferenceFormat

        if name is not None:
            raise NoColocatedBranchSupport(self)
        raise errors.IncompatibleFormat(BranchReferenceFormat, self._format)


class BzrDir4(BzrDirPreSplitOut):
    """A .bzr version 4 control object.

    This is a deprecated format and may be removed after sept 2006.
    """

    def create_repository(self, shared=False):
        """Create a repository in this bzrdir.

        Args:
            shared: Whether to create a shared repository.

        Returns:
            The created repository.
        """
        return self._format.repository_format.initialize(self, shared)

    def needs_format_conversion(self, format):
        """Check if this bzrdir needs conversion to a given format.

        Args:
            format: The target format to check against.

        Returns:
            bool: Always True, as format 4 is deprecated.
        """
        return True

    def open_repository(self):
        """Open the repository in this bzrdir.

        Returns:
            The opened repository.
        """
        from .repository import RepositoryFormat4

        return RepositoryFormat4().open(self, _found=True)


class BzrDir5(BzrDirPreSplitOut):
    """A .bzr version 5 control object.

    This is a deprecated format and may be removed after sept 2006.
    """

    def has_workingtree(self):
        """Check if this bzrdir contains a working tree.

        Returns:
            bool: Always True for format 5.
        """
        return True

    def open_repository(self):
        """Open the repository in this bzrdir.

        Returns:
            The opened repository.
        """
        from .repository import RepositoryFormat5

        return RepositoryFormat5().open(self, _found=True)

    def open_workingtree(self, unsupported=False, recommend_upgrade=True):
        """Open the working tree in this bzrdir.

        Args:
            unsupported: Whether to open even if unsupported.
            recommend_upgrade: Whether to recommend upgrading.

        Returns:
            The opened working tree.
        """
        from .workingtree import WorkingTreeFormat2

        wt_format = WorkingTreeFormat2()
        # we don't warn here about upgrades; that ought to be handled for the
        # bzrdir as a whole
        return wt_format.open(self, _found=True)


class BzrDir6(BzrDirPreSplitOut):
    """A .bzr version 6 control object.

    This is a deprecated format and may be removed after sept 2006.
    """

    def has_workingtree(self):
        """Check if this bzrdir contains a working tree.

        Returns:
            bool: Always True for format 6.
        """
        return True

    def open_repository(self):
        """Open the repository in this bzrdir.

        Returns:
            The opened repository.
        """
        from .repository import RepositoryFormat6

        return RepositoryFormat6().open(self, _found=True)

    def open_workingtree(self, unsupported=False, recommend_upgrade=True):
        """Open the working tree in this bzrdir.

        Args:
            unsupported: Whether to open even if unsupported.
            recommend_upgrade: Whether to recommend upgrading.

        Returns:
            The opened working tree.
        """
        # we don't warn here about upgrades; that ought to be handled for the
        # bzrdir as a whole
        from .workingtree import WorkingTreeFormat2

        return WorkingTreeFormat2().open(self, _found=True)
