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

from bzrformats.inventory import (
    Inventory,
    InventoryDirectory,
    InventoryFile,
    InventoryLink,
)
from bzrformats.xml5 import inventory_serializer_v5

from ... import cache_utf8, osutils
from ...errors import BzrError, NoSuchId, TestamentMismatch
from ...osutils import pathjoin, sha_string, sha_strings
from ...revision import NULL_REVISION, Revision
from ...trace import mutter, warning
from ...tree import InterTree
from ..inventorytree import InventoryTree
from ..testament import StrictTestament
from . import apply_bundle


class RevisionInfo:
    """Gets filled out for each revision object that is read."""

    def __init__(self, revision_id):
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
        return pprint.pformat(self.__dict__)

    def as_revision(self):
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
        for r in self.real_revisions:
            if r.revision_id == revision_id:
                return r
        raise KeyError(revision_id)

    def get_revision_info(self, revision_id):
        for r in self.revisions:
            if r.revision_id == revision_id:
                return r
        raise KeyError(revision_id)

    def revision_tree(self, repository, revision_id, base=None):
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
    def __init__(self, base_tree, revision_id):
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
        """Files that don't exist in base need a new id."""
        self._new_id[new_path] = new_id
        self._new_id_r[new_id] = new_path
        self._kinds[new_path] = kind

    def note_last_changed(self, file_id, revision_id):
        if file_id in self._last_changed and self._last_changed[file_id] != revision_id:
            raise BzrError(
                f"Mismatched last-changed revision for file_id {{{file_id}}}"
                f": {self._last_changed[file_id]} != {revision_id}"
            )
        self._last_changed[file_id] = revision_id

    def note_patch(self, new_path, patch):
        """There is a patch for a given filename."""
        self.patches[new_path] = patch

    def note_target(self, new_path, target):
        """The symlink at the new path has the given target."""
        self._targets[new_path] = target

    def note_deletion(self, old_path):
        """The file at old_path has been deleted."""
        self.deleted.append(old_path)

    def note_executable(self, new_path, executable):
        self._executable[new_path] = executable

    def old_path(self, new_path):
        """Get the old_path (path in the base_tree) for the file at new_path."""
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
        """Get the new_path (path in the target_tree) for the file at old_path
        in the base tree.
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
        """Return the id of the file present at path in the target tree."""
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
        """Return the new path in the target tree of the file with id file_id."""
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
        """Return a file-like object containing the new contents of the
        file given by file_id.

        TODO:   It might be nice if this actually generated an entry
                in the text-store, so that the file contents would
                then be cached.
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
        try:
            return self._targets[path]
        except KeyError:
            old_path = self.old_path(path)
            return self.base_tree.get_symlink_target(old_path)

    def kind(self, path):
        try:
            return self._kinds[path]
        except KeyError:
            old_path = self.old_path(path)
            return self.base_tree.kind(old_path)

    def get_file_revision(self, path):
        if path in self._last_changed:
            return self._last_changed[path]
        else:
            old_path = self.old_path(path)
            return self.base_tree.get_file_revision(old_path)

    def is_executable(self, path):
        if path in self._executable:
            return self._executable[path]
        else:
            old_path = self.old_path(path)
            return self.base_tree.is_executable(old_path)

    def get_last_changed(self, path):
        if path in self._last_changed:
            return self._last_changed[path]
        old_path = self.old_path(path)
        return self.base_tree.get_file_revision(old_path)

    def get_size_and_sha1(self, new_path):
        """Return the size and sha1 hash of the given file id.
        If the file was not locally modified, this is extracted
        from the base_tree. Rather than re-reading the file.
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

        This need to be called before ever accessing self.inventory
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
        return {entry.file_id for path, entry in self.inventory.iter_entries()}

    def all_versioned_paths(self):
        return {path for path, entry in self.inventory.iter_entries()}

    def list_files(self, include_root=False, from_dir=None, recursive=True):
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
    """Produce a file-like object with the patched version of a text."""
    from ...osutils import IterableFile
    from ...patches import iter_patched

    if file_patch == b"":
        return IterableFile(())
    # string.splitlines(True) also splits on '\r', but the iter_patched code
    # only expects to iterate over '\n' style lines
    return IterableFile(iter_patched(original, BytesIO(file_patch).readlines()))
