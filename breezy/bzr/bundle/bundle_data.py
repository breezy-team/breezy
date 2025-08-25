# Copyright (C) 2005-2010 Canonical Ltd
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

"""Read in a bundle stream, and process it into a BundleReader object."""

import base64
import os
import pprint
from io import BytesIO

from ... import cache_utf8, osutils
from ...errors import BzrError, NoSuchId, TestamentMismatch
from ...osutils import pathjoin, sha_string, sha_strings
from ...revision import NULL_REVISION, Revision
from ...trace import mutter, warning
from ...tree import InterTree
from ..inventory import Inventory, InventoryDirectory, InventoryFile, InventoryLink
from ..inventorytree import InventoryTree
from ..testament import StrictTestament
from ..xml5 import inventory_serializer_v5
from . import apply_bundle


class RevisionInfo:
    """Gets filled out for each revision object that is read."""

    def __init__(self, revision_id):
        """Initialize revision information for a specific revision.

        Args:
            revision_id: The unique identifier for this revision.
        """
        self.revision_id = revision_id
        self.sha1 = None
        self.committer = None
        self.date = None
        self.timestamp = None
        self.timezone = None
        self.inventory_sha1 = None

        self.parent_ids = None
        self.base_id = None
        self.message = None
        self.properties = None
        self.tree_actions = None

    def __str__(self):
        """Return a pretty-printed representation of the revision info.

        Returns:
            A formatted string representation of all revision attributes.
        """
        return pprint.pformat(self.__dict__)

    def as_revision(self):
        """Convert this RevisionInfo into a Revision object.

        Parses the stored revision properties and creates a proper Revision
        object with all necessary metadata including timestamp, timezone,
        inventory SHA1, and revision properties.

        Returns:
            A Revision object containing all the revision metadata.

        Raises:
            ValueError: If a property line is malformed (missing colon).
        """
        properties = {}
        if self.properties:
            for property in self.properties:
                key_end = property.find(": ")
                if key_end == -1:
                    if not property.endswith(":"):
                        raise ValueError(property)
                    key = str(property[:-1])
                    value = ""
                else:
                    key = str(property[:key_end])
                    value = property[key_end + 2 :]
                properties[key] = value

        return Revision(
            revision_id=self.revision_id,
            committer=self.committer,
            timestamp=float(self.timestamp),
            timezone=int(self.timezone),
            inventory_sha1=self.inventory_sha1,
            message="\n".join(self.message),
            parent_ids=self.parent_ids or [],
            properties=properties,
        )

    @staticmethod
    def from_revision(revision):
        """Create a RevisionInfo from an existing Revision object.

        Extracts all relevant information from a Revision object and
        creates a corresponding RevisionInfo with properly formatted
        date, message lines, and properties.

        Args:
            revision: A Revision object to convert.

        Returns:
            A RevisionInfo object populated with the revision's data.
        """
        revision_info = RevisionInfo(revision.revision_id)
        date = osutils.format_highres_date(revision.timestamp, revision.timezone)
        revision_info.date = date
        revision_info.timezone = revision.timezone
        revision_info.timestamp = revision.timestamp
        revision_info.message = revision.message.split("\n")
        revision_info.properties = [": ".join(p) for p in revision.properties.items()]
        return revision_info


class BundleInfo:
    """This contains the meta information. Stuff that allows you to
    recreate the revision or inventory XML.
    """

    def __init__(self, bundle_format=None):
        """Initialize bundle metadata container.

        Args:
            bundle_format: The format version of the bundle (currently unused).
        """
        self.bundle_format = None
        self.committer = None
        self.date = None
        self.message = None

        # A list of RevisionInfo objects
        self.revisions = []

        # The next entries are created during complete_info() and
        # other post-read functions.

        # A list of real Revision objects
        self.real_revisions = []

        self.timestamp = None
        self.timezone = None

        # Have we checked the repository yet?
        self._validated_revisions_against_repo = False

    def __str__(self):
        """Return a pretty-printed representation of the bundle info.

        Returns:
            A formatted string representation of all bundle attributes.
        """
        return pprint.pformat(self.__dict__)

    def complete_info(self):
        """This makes sure that all information is properly
        split up, based on the assumptions that can be made
        when information is missing.
        """
        # Put in all of the guessable information.
        if not self.timestamp and self.date:
            self.timestamp, self.timezone = osutils.unpack_highres_date(self.date)

        self.real_revisions = []
        for rev in self.revisions:
            if rev.timestamp is None:
                if rev.date is not None:
                    rev.timestamp, rev.timezone = osutils.unpack_highres_date(rev.date)
                else:
                    rev.timestamp = self.timestamp
                    rev.timezone = self.timezone
            if rev.message is None and self.message:
                rev.message = self.message
            if rev.committer is None and self.committer:
                rev.committer = self.committer
            self.real_revisions.append(rev.as_revision())

    def get_base(self, revision):
        """Get the base revision for a given revision.

        Determines what revision this revision is based on, either from
        the explicitly stored base_id or by examining the revision's
        parent relationships.

        Args:
            revision: The Revision object to find the base for.

        Returns:
            The revision ID that this revision is based on, or NULL_REVISION
            if this is the first revision in the bundle.
        """
        revision_info = self.get_revision_info(revision.revision_id)
        if revision_info.base_id is not None:
            return revision_info.base_id
        if len(revision.parent_ids) == 0:
            # There is no base listed, and
            # the lowest revision doesn't have a parent
            # so this is probably against the empty tree
            # and thus base truly is NULL_REVISION
            return NULL_REVISION
        else:
            return revision.parent_ids[-1]

    def _get_target(self):
        """Return the target revision."""
        if len(self.real_revisions) > 0:
            return self.real_revisions[0].revision_id
        elif len(self.revisions) > 0:
            return self.revisions[0].revision_id
        return None

    target = property(_get_target, doc="The target revision id")

    def get_revision(self, revision_id):
        """Get a Revision object by its revision ID.

        Args:
            revision_id: The revision ID to look up.

        Returns:
            The Revision object with the matching ID.

        Raises:
            KeyError: If no revision with the given ID is found.
        """
        for r in self.real_revisions:
            if r.revision_id == revision_id:
                return r
        raise KeyError(revision_id)

    def get_revision_info(self, revision_id):
        """Get a RevisionInfo object by its revision ID.

        Args:
            revision_id: The revision ID to look up.

        Returns:
            The RevisionInfo object with the matching ID.

        Raises:
            KeyError: If no revision info with the given ID is found.
        """
        for r in self.revisions:
            if r.revision_id == revision_id:
                return r
        raise KeyError(revision_id)

    def revision_tree(self, repository, revision_id, base=None):
        """Create a tree representing the state at the given revision.

        Builds a BundleTree that represents the file system state at the
        specified revision, applying all changes from the bundle data.
        The tree is validated for consistency including inventory and
        revision hashes.

        Args:
            repository: The repository to use for base revision data.
            revision_id: The revision ID to build the tree for.
            base: Unused parameter (base is determined automatically).

        Returns:
            A BundleTree representing the file system at the revision.

        Raises:
            AssertionError: If the revision references itself as its base.
        """
        revision = self.get_revision(revision_id)
        base = self.get_base(revision)
        if base == revision_id:
            raise AssertionError()
        if not self._validated_revisions_against_repo:
            self._validate_references_from_repository(repository)
        self.get_revision_info(revision_id)
        inventory_revision_id = revision_id
        bundle_tree = BundleTree(repository.revision_tree(base), inventory_revision_id)
        self._update_tree(bundle_tree, revision_id)

        inv = bundle_tree.inventory
        self._validate_inventory(inv, revision_id)
        self._validate_revision(bundle_tree, revision_id)

        return bundle_tree

    def _validate_references_from_repository(self, repository):
        """Now that we have a repository which should have some of the
        revisions we care about, go through and validate all of them
        that we can.
        """
        rev_to_sha = {}
        inv_to_sha = {}

        def add_sha(d, revision_id, sha1):
            if revision_id is None:
                if sha1 is not None:
                    raise BzrError("A Null revision should alwayshave a null sha1 hash")
                return
            if revision_id in d:
                # This really should have been validated as part
                # of _validate_revisions but lets do it again
                if sha1 != d[revision_id]:
                    raise BzrError(
                        f"** Revision {revision_id!r} referenced with 2 different"
                        f" sha hashes {sha1} != {d[revision_id]}"
                    )
            else:
                d[revision_id] = sha1

        # All of the contained revisions were checked
        # in _validate_revisions
        checked = {}
        for rev_info in self.revisions:
            checked[rev_info.revision_id] = True
            add_sha(rev_to_sha, rev_info.revision_id, rev_info.sha1)

        for _rev, rev_info in zip(self.real_revisions, self.revisions):
            add_sha(inv_to_sha, rev_info.revision_id, rev_info.inventory_sha1)

        count = 0
        missing = {}
        for revision_id, sha1 in rev_to_sha.items():
            if repository.has_revision(revision_id):
                StrictTestament.from_revision(repository, revision_id)
                local_sha1 = self._testament_sha1_from_revision(repository, revision_id)
                if sha1 != local_sha1:
                    raise BzrError(
                        f"sha1 mismatch. For revision id {{{revision_id}}}"
                        f"local: {local_sha1}, bundle: {sha1}"
                    )
                else:
                    count += 1
            elif revision_id not in checked:
                missing[revision_id] = sha1

        if len(missing) > 0:
            # I don't know if this is an error yet
            warning(
                "Not all revision hashes could be validated."
                " Unable validate %d hashes" % len(missing)
            )
        mutter("Verified %d sha hashes for the bundle." % count)
        self._validated_revisions_against_repo = True

    def _validate_inventory(self, inv, revision_id):
        """At this point we should have generated the BundleTree,
        so build up an inventory, and make sure the hashes match.
        """
        # Now we should have a complete inventory entry.
        cs = inventory_serializer_v5.write_inventory_to_chunks(inv)
        sha1 = sha_strings(cs)
        # Target revision is the last entry in the real_revisions list
        rev = self.get_revision(revision_id)
        if rev.revision_id != revision_id:
            raise AssertionError()
        if sha1 != rev.inventory_sha1:
            with open(",,bogus-inv", "wb") as f:
                f.writelines(cs)
            warning(
                f"Inventory sha hash mismatch for revision {revision_id}. {sha1}"
                f" != {rev.inventory_sha1}"
            )

    def _testament(self, revision, tree):
        raise NotImplementedError(self._testament)

    def _validate_revision(self, tree, revision_id):
        """Make sure all revision entries match their checksum."""
        # This is a mapping from each revision id to its sha hash
        rev_to_sha1 = {}

        rev = self.get_revision(revision_id)
        rev_info = self.get_revision_info(revision_id)
        if not (rev.revision_id == rev_info.revision_id):
            raise AssertionError()
        if not (rev.revision_id == revision_id):
            raise AssertionError()
        testament = self._testament(rev, tree)
        sha1 = testament.as_sha1()
        if sha1 != rev_info.sha1:
            raise TestamentMismatch(rev.revision_id, rev_info.sha1, sha1)
        if rev.revision_id in rev_to_sha1:
            raise BzrError(
                "Revision {{{}}} given twice in the list".format(rev.revision_id)
            )
        rev_to_sha1[rev.revision_id] = sha1

    def _update_tree(self, bundle_tree, revision_id):
        """This fills out a BundleTree based on the information
        that was read in.

        :param bundle_tree: A BundleTree to update with the new information.
        """

        def get_rev_id(last_changed, path, kind):
            if last_changed is not None:
                # last_changed will be a Unicode string because of how it was
                # read. Convert it back to utf8.
                changed_revision_id = cache_utf8.encode(last_changed)
            else:
                changed_revision_id = revision_id
            bundle_tree.note_last_changed(path, changed_revision_id)
            return changed_revision_id

        def extra_info(info, new_path):
            last_changed = None
            encoding = None
            for info_item in info:
                try:
                    name, value = info_item.split(":", 1)
                except ValueError as e:
                    raise ValueError(f"Value {info_item!r} has no colon") from e
                if name == "last-changed":
                    last_changed = value
                elif name == "executable":
                    val = value == "yes"
                    bundle_tree.note_executable(new_path, val)
                elif name == "target":
                    bundle_tree.note_target(new_path, value)
                elif name == "encoding":
                    encoding = value
            return last_changed, encoding

        def do_patch(path, lines, encoding):
            if encoding == "base64":
                patch = base64.b64decode(b"".join(lines))
            elif encoding is None:
                patch = b"".join(lines)
            else:
                raise ValueError(encoding)
            bundle_tree.note_patch(path, patch)

        def renamed(kind, extra, lines):
            info = extra.split(" // ")
            if len(info) < 2:
                raise BzrError(
                    "renamed action lines need both a from and to: {!r}".format(extra)
                )
            old_path = info[0]
            new_path = info[1][3:] if info[1].startswith("=> ") else info[1]

            bundle_tree.note_rename(old_path, new_path)
            last_modified, encoding = extra_info(info[2:], new_path)
            get_rev_id(last_modified, new_path, kind)
            if lines:
                do_patch(new_path, lines, encoding)

        def removed(kind, extra, lines):
            info = extra.split(" // ")
            if len(info) > 1:
                # TODO: in the future we might allow file ids to be
                # given for removed entries
                raise BzrError(
                    "removed action lines should only have the path: {!r}".format(extra)
                )
            path = info[0]
            bundle_tree.note_deletion(path)

        def added(kind, extra, lines):
            info = extra.split(" // ")
            if len(info) <= 1:
                raise BzrError(
                    "add action lines require the path and file id: {!r}".format(extra)
                )
            elif len(info) > 5:
                raise BzrError(
                    "add action lines have fewer than 5 entries.: {!r}".format(extra)
                )
            path = info[0]
            if not info[1].startswith("file-id:"):
                raise BzrError(
                    "The file-id should follow the path for an add: {!r}".format(extra)
                )
            # This will be Unicode because of how the stream is read. Turn it
            # back into a utf8 file_id
            file_id = cache_utf8.encode(info[1][8:])

            bundle_tree.note_id(file_id, path, kind)
            # this will be overridden in extra_info if executable is specified.
            bundle_tree.note_executable(path, False)
            last_changed, encoding = extra_info(info[2:], path)
            get_rev_id(last_changed, path, kind)
            if kind == "directory":
                return
            do_patch(path, lines, encoding)

        def modified(kind, extra, lines):
            info = extra.split(" // ")
            if len(info) < 1:
                raise BzrError(
                    "modified action lines have at leastthe path in them: {!r}".format(
                        extra
                    )
                )
            path = info[0]

            last_modified, encoding = extra_info(info[1:], path)
            get_rev_id(last_modified, path, kind)
            if lines:
                do_patch(path, lines, encoding)

        valid_actions = {
            "renamed": renamed,
            "removed": removed,
            "added": added,
            "modified": modified,
        }
        for action_line, lines in self.get_revision_info(revision_id).tree_actions:
            first = action_line.find(" ")
            if first == -1:
                raise BzrError(f"Bogus action line (no opening space): {action_line!r}")
            second = action_line.find(" ", first + 1)
            if second == -1:
                raise BzrError(
                    "Bogus action line (missing second space): {!r}".format(action_line)
                )
            action = action_line[:first]
            kind = action_line[first + 1 : second]
            if kind not in ("file", "directory", "symlink"):
                raise BzrError(
                    f"Bogus action line (invalid object kind {kind!r}): {action_line!r}"
                )
            extra = action_line[second + 1 :]

            if action not in valid_actions:
                raise BzrError(
                    "Bogus action line (unrecognized action): {!r}".format(action_line)
                )
            valid_actions[action](kind, extra, lines)

    def install_revisions(self, target_repo, stream_input=True):
        """Install revisions and return the target revision.

        :param target_repo: The repository to install into
        :param stream_input: Ignored by this implementation.
        """
        apply_bundle.install_bundle(target_repo, self)
        return self.target

    def get_merge_request(self, target_repo):
        """Provide data for performing a merge.

        Returns suggested base, suggested target, and patch verification status
        """
        return None, self.target, "inapplicable"


class BundleTree(InventoryTree):
    """A tree that represents the result of applying bundle changes to a base tree.

    BundleTree maintains information about file modifications, renames, additions,
    and deletions relative to a base tree, allowing reconstruction of the complete
    file system state at a specific revision.
    """

    def __init__(self, base_tree, revision_id):
        """Initialize a bundle tree with a base tree and target revision.

        Args:
            base_tree: The base tree to apply bundle changes to.
            revision_id: The target revision ID this tree represents.
        """
        self.base_tree = base_tree
        self._renamed = {}  # Mapping from old_path => new_path
        self._renamed_r = {}  # new_path => old_path
        self._new_id = {}  # new_path => new_id
        self._new_id_r = {}  # new_id => new_path
        self._kinds = {}  # new_path => kind
        self._last_changed = {}  # new_id => revision_id
        self._executable = {}  # new_id => executable value
        self.patches = {}
        self._targets = {}  # new path => new symlink target
        self.deleted = []
        self.revision_id = revision_id
        self._inventory = None
        self._base_inter = InterTree.get(self.base_tree, self)

    def __str__(self):
        """Return a pretty-printed representation of the bundle tree.

        Returns:
            A formatted string representation of all tree attributes.
        """
        return pprint.pformat(self.__dict__)

    def note_rename(self, old_path, new_path):
        """A file/directory has been renamed from old_path => new_path."""
        if new_path in self._renamed:
            raise AssertionError(new_path)
        if old_path in self._renamed_r:
            raise AssertionError(old_path)
        self._renamed[new_path] = old_path
        self._renamed_r[old_path] = new_path

    def note_id(self, new_id, new_path, kind="file"):
        """Record a new file ID for a path that doesn't exist in the base tree.

        Args:
            new_id: The file ID to assign to the new file.
            new_path: The path where the file will exist.
            kind: The kind of file ("file", "directory", or "symlink").
        """
        self._new_id[new_path] = new_id
        self._new_id_r[new_id] = new_path
        self._kinds[new_path] = kind

    def note_last_changed(self, file_id, revision_id):
        """Record the revision when a file was last changed.

        Args:
            file_id: The file ID being updated.
            revision_id: The revision ID when this file was last modified.

        Raises:
            BzrError: If file_id already has a different last-changed revision.
        """
        if file_id in self._last_changed and self._last_changed[file_id] != revision_id:
            raise BzrError(
                f"Mismatched last-changed revision for file_id {{{file_id}}}"
                f": {self._last_changed[file_id]} != {revision_id}"
            )
        self._last_changed[file_id] = revision_id

    def note_patch(self, new_path, patch):
        """Record a patch that should be applied to a file.

        Args:
            new_path: The path of the file to patch.
            patch: The patch data to apply to the file.
        """
        self.patches[new_path] = patch

    def note_target(self, new_path, target):
        """Record the target for a symbolic link.

        Args:
            new_path: The path of the symbolic link.
            target: The target path the symbolic link points to.
        """
        self._targets[new_path] = target

    def note_deletion(self, old_path):
        """Record that a file has been deleted.

        Args:
            old_path: The path of the file that was deleted.
        """
        self.deleted.append(old_path)

    def note_executable(self, new_path, executable):
        """Record the executable status of a file.

        Args:
            new_path: The path of the file.
            executable: True if the file should be executable, False otherwise.
        """
        self._executable[new_path] = executable

    def old_path(self, new_path):
        r"""Get the old_path (path in the base_tree) for the file at new_path.

        Traverses the rename mappings to determine what path this file
        had in the base tree, if any.

        Args:
            new_path: The path in this tree.

        Returns:
            The corresponding path in the base tree, or None if the file
            is new or has been renamed away.

        Raises:
            ValueError: If new_path starts with '\' or '/'.
        """
        if new_path[:1] in ("\\", "/"):
            raise ValueError(new_path)
        old_path = self._renamed.get(new_path)
        if old_path is not None:
            return old_path
        dirname, basename = os.path.split(new_path)
        # dirname is not '' doesn't work, because
        # dirname may be a unicode entry, and is
        # requires the objects to be identical
        if dirname != "":
            old_dir = self.old_path(dirname)
            old_path = None if old_dir is None else pathjoin(old_dir, basename)
        else:
            old_path = new_path
        # If the new path wasn't in renamed, the old one shouldn't be in
        # renamed_r
        if old_path in self._renamed_r:
            return None
        return old_path

    def new_path(self, old_path):
        r"""Get the new_path (path in the target_tree) for the file at old_path.

        Traverses the rename mappings to determine what path this file
        will have in the target tree, if any.

        Args:
            old_path: The path in the base tree.

        Returns:
            The corresponding path in this tree, or None if the file
            has been deleted or renamed away.

        Raises:
            ValueError: If old_path starts with '\' or '/'.
        """
        if old_path[:1] in ("\\", "/"):
            raise ValueError(old_path)
        new_path = self._renamed_r.get(old_path)
        if new_path is not None:
            return new_path
        if new_path in self._renamed:
            return None
        dirname, basename = os.path.split(old_path)
        if dirname != "":
            new_dir = self.new_path(dirname)
            new_path = None if new_dir is None else pathjoin(new_dir, basename)
        else:
            new_path = old_path
        # If the old path wasn't in renamed, the new one shouldn't be in
        # renamed_r
        if new_path in self._renamed:
            return None
        return new_path

    def path2id(self, path):
        """Return the file ID of the file present at path in the target tree.

        Args:
            path: The path to look up.

        Returns:
            The file ID at the given path, or None if no file exists there.
        """
        file_id = self._new_id.get(path)
        if file_id is not None:
            return file_id
        old_path = self.old_path(path)
        if old_path is None:
            return None
        if old_path in self.deleted:
            return None
        return self.base_tree.path2id(old_path)

    def id2path(self, file_id, recurse="down"):
        """Return the new path in the target tree of the file with the given ID.

        Args:
            file_id: The file ID to look up.
            recurse: Recursion direction (inherited from base class, unused).

        Returns:
            The path of the file with the given ID.

        Raises:
            NoSuchId: If the file ID is not found or has been deleted.
        """
        path = self._new_id_r.get(file_id)
        if path is not None:
            return path
        old_path = self.base_tree.id2path(file_id, recurse)
        if old_path is None:
            raise NoSuchId(file_id, self)
        if old_path in self.deleted:
            raise NoSuchId(file_id, self)
        new_path = self.new_path(old_path)
        if new_path is None:
            raise NoSuchId(file_id, self)
        return new_path

    def get_file(self, path):
        """Return a file-like object containing the new contents of the file.

        Applies any patches to the base file content to produce the final
        file content for this tree. If no patches exist, returns the original
        file from the base tree.

        Args:
            path: The path of the file to retrieve.

        Returns:
            A file-like object containing the file's contents.

        Raises:
            AssertionError: If the file doesn't exist in base and has no patches.
            ValueError: If the patch format is malformed.
        """
        old_path = self._base_inter.find_source_path(path)
        patch_original = None if old_path is None else self.base_tree.get_file(old_path)
        file_patch = self.patches.get(path)
        if file_patch is None:
            if patch_original is None and self.kind(path) == "directory":
                return BytesIO()
            if patch_original is None:
                raise AssertionError(f"None: {file_id}")
            return patch_original

        if file_patch.startswith(b"\\"):
            raise ValueError(f"Malformed patch for {file_id}, {file_patch!r}")
        return patched_file(file_patch, patch_original)

    def get_symlink_target(self, path):
        """Get the target of a symbolic link.

        Args:
            path: The path of the symbolic link.

        Returns:
            The target path the symbolic link points to.
        """
        try:
            return self._targets[path]
        except KeyError:
            old_path = self.old_path(path)
            return self.base_tree.get_symlink_target(old_path)

    def kind(self, path):
        """Get the kind of file at the given path.

        Args:
            path: The path to examine.

        Returns:
            The file kind: 'file', 'directory', or 'symlink'.
        """
        try:
            return self._kinds[path]
        except KeyError:
            old_path = self.old_path(path)
            return self.base_tree.kind(old_path)

    def get_file_revision(self, path):
        """Get the revision ID when the file was last changed.

        Args:
            path: The path of the file.

        Returns:
            The revision ID when this file was last modified.
        """
        if path in self._last_changed:
            return self._last_changed[path]
        else:
            old_path = self.old_path(path)
            return self.base_tree.get_file_revision(old_path)

    def is_executable(self, path):
        """Check if a file is executable.

        Args:
            path: The path of the file to check.

        Returns:
            True if the file is executable, False otherwise.
        """
        if path in self._executable:
            return self._executable[path]
        else:
            old_path = self.old_path(path)
            return self.base_tree.is_executable(old_path)

    def get_last_changed(self, path):
        """Get the revision ID when the file was last changed.

        This is an alias for get_file_revision for compatibility.

        Args:
            path: The path of the file.

        Returns:
            The revision ID when this file was last modified.
        """
        if path in self._last_changed:
            return self._last_changed[path]
        old_path = self.old_path(path)
        return self.base_tree.get_file_revision(old_path)

    def get_size_and_sha1(self, new_path):
        """Return the size and SHA1 hash of the given file.

        If the file was not locally modified, this is extracted from the
        base_tree rather than re-reading the file. For modified files,
        the content is generated and hashed.

        Args:
            new_path: The path of the file.

        Returns:
            A tuple of (size, sha1_hash) for the file, or (None, None)
            if the path is None.
        """
        if new_path is None:
            return None, None
        if new_path not in self.patches:
            # If the entry does not have a patch, then the
            # contents must be the same as in the base_tree
            base_path = self.old_path(new_path)
            text_size = self.base_tree.get_file_size(base_path)
            text_sha1 = self.base_tree.get_file_sha1(base_path)
            return text_size, text_sha1
        fileobj = self.get_file(new_path)
        content = fileobj.read()
        return len(content), sha_string(content)

    def _get_inventory(self):
        """Build up the inventory entry for the BundleTree.

        Constructs a complete inventory by combining information from the
        base tree with the bundle's modifications. Creates appropriate
        inventory entries for files, directories, and symlinks with
        correct file IDs, sizes, SHA1 hashes, and other metadata.

        This needs to be called before ever accessing self.inventory.

        Returns:
            An Inventory object representing the complete file system state.

        Raises:
            BzrError: If a file has a text_size of None when it shouldn't.
        """
        from os.path import basename, dirname

        inv = Inventory(None, self.revision_id)

        def add_entry(path, file_id):
            if path == "":
                parent_id = None
            else:
                parent_path = dirname(path)
                parent_id = self.path2id(parent_path)

            kind = self.kind(path)
            revision_id = self.get_last_changed(path)

            name = basename(path)
            if kind == "directory":
                ie = InventoryDirectory(file_id, name, parent_id, revision_id)
            elif kind == "file":
                text_size, text_sha1 = self.get_size_and_sha1(path)
                if text_size is None:
                    raise BzrError(f"Got a text_size of None for file_id {file_id!r}")
                ie = InventoryFile(
                    file_id,
                    name,
                    parent_id,
                    revision_id,
                    executable=self.is_executable(path),
                    text_size=text_size,
                    text_sha1=text_sha1,
                )
            elif kind == "symlink":
                ie = InventoryLink(
                    file_id,
                    name,
                    parent_id,
                    revision_id,
                    symlink_target=self.get_symlink_target(path),
                )

            inv.add(ie)

        sorted_entries = self.sorted_path_id()
        for path, file_id in sorted_entries:
            add_entry(path, file_id)

        return inv

    # Have to overload the inherited inventory property
    # because _get_inventory is only called in the parent.
    # Reading the docs, property() objects do not use
    # overloading, they use the function as it was defined
    # at that instant
    inventory = property(_get_inventory)

    root_inventory = property(_get_inventory)

    def all_file_ids(self):
        """Return a set of all file IDs in this tree.

        Returns:
            A set containing all file IDs present in the inventory.
        """
        return {entry.file_id for path, entry in self.inventory.iter_entries()}

    def all_versioned_paths(self):
        """Return a set of all versioned paths in this tree.

        Returns:
            A set containing all paths that are under version control.
        """
        return {path for path, entry in self.inventory.iter_entries()}

    def list_files(self, include_root=False, from_dir=None, recursive=True):
        """List all files in the tree.

        Args:
            include_root: If True, include the root directory in results.
            from_dir: Directory to start listing from, or None for root.
            recursive: If True, list files recursively in subdirectories.

        Yields:
            Tuples of (path, status, kind, entry) for each file.
            Status is always 'V' (versioned) for bundle trees.
        """
        # The only files returned by this are those from the version
        inv = self.inventory
        if from_dir is None:
            from_dir_id = None
        else:
            from_dir_id = inv.path2id(from_dir)
            if from_dir_id is None:
                # Directory not versioned
                return
        entries = inv.iter_entries(from_dir=from_dir_id, recursive=recursive)
        if inv.root is not None and not include_root and from_dir is None:
            # skip the root for compatibility with the current apis.
            next(entries)
        for path, entry in entries:
            yield path, "V", entry.kind, entry

    def sorted_path_id(self):
        """Return a sorted list of (path, file_id) tuples for all files.

        Combines files from both the new additions and base tree,
        excluding any that have been deleted.

        Returns:
            A sorted list of (path, file_id) tuples.
        """
        paths = []
        for result in self._new_id.items():
            paths.append(result)
        for id in self.base_tree.all_file_ids():
            try:
                path = self.id2path(id, recurse="none")
            except NoSuchId:
                continue
            paths.append((path, id))
        paths.sort()
        return paths


def patched_file(file_patch, original):
    """Produce a file-like object with the patched version of a text.

    Applies a unified diff patch to an original file to produce the
    modified content. Handles both normal patches and empty patches.

    Args:
        file_patch: The patch data as bytes, or empty bytes for no changes.
        original: A file-like object containing the original content,
                 or None if this is a new file.

    Returns:
        A file-like object containing the patched content. For empty
        patches, returns an empty file. For normal patches, returns
        the result of applying the patch to the original content.
    """
    from ...osutils import IterableFile
    from ...patches import iter_patched

    if file_patch == b"":
        return IterableFile(())
    # string.splitlines(True) also splits on '\r', but the iter_patched code
    # only expects to iterate over '\n' style lines
    return IterableFile(iter_patched(original, BytesIO(file_patch).readlines()))
