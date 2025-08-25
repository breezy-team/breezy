# Copyright (C) 2011, 2012 Canonical Ltd
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

"""bzr-upload command implementations."""

from ... import commands, config, errors, lazy_import, option, osutils

lazy_import.lazy_import(
    globals(),
    """
import stat

from breezy import (
    controldir,
    globbing,
    ignores,
    revision,
    transport,
    urlutils,
    )
""",
)


auto_option = config.Option(
    "upload_auto",
    default=False,
    from_unicode=config.bool_from_store,
    help="""\
Whether upload should occur when the tip of the branch changes.
""",
)
auto_quiet_option = config.Option(
    "upload_auto_quiet",
    default=False,
    from_unicode=config.bool_from_store,
    help="""\
Whether upload should occur quietly.
""",
)
location_option = config.Option(
    "upload_location",
    default=None,
    help="""\
The url to upload the working tree to.
""",
)
revid_location_option = config.Option(
    "upload_revid_location",
    default=".bzr-upload.revid",
    help="""\
The relative path to be used to store the uploaded revid.

The only bzr-related info uploaded with the working tree is the corresponding
revision id. The uploaded working tree is not linked to any other bzr data.

If the layout of your remote server is such that you can't write in the
root directory but only in the directories inside that root, you will need
to use the 'upload_revid_location' configuration variable to specify the
relative path to be used. That configuration variable can be specified in
locations.conf or branch.conf.

For example, given the following layout:

  Project/
    private/
    public/

you may have write access in 'private' and 'public' but in 'Project'
itself. In that case, you can add the following in your locations.conf or
branch.conf file:

  upload_revid_location = private/.bzr-upload.revid
""",
)


# FIXME: Add more tests around invalid paths or relative paths that doesn't
# exist on remote (if only to get proper error messages) for
# 'upload_revid_location'


class BzrUploader:
    """Handles uploading working tree contents to a remote location.

    This class manages the process of uploading files, directories, and symlinks
    from a Bazaar working tree to a remote server via transport. It supports both
    full uploads and incremental updates based on revision differences.

    The uploader tracks uploaded revision IDs to enable efficient incremental
    uploads and handles various edge cases like file collisions, renames, and
    deletions.

    Attributes:
        branch: The Bazaar branch to upload from.
        to_transport: Transport object for the destination location.
        outf: Output stream for progress messages.
        tree: The revision tree to upload.
        rev_id: The revision ID being uploaded.
        quiet: Whether to suppress progress output.
        _pending_deletions: List of directories to delete later.
        _pending_renames: List of pending rename operations.
        _uploaded_revid: The last uploaded revision ID (cached).
        _ignored: Globster object for ignored file patterns.
    """

    def __init__(self, branch, to_transport, outf, tree, rev_id, quiet=False):
        """Initialize the BzrUploader.

        Args:
            branch: The Bazaar branch to upload from.
            to_transport: Transport object for the destination location.
            outf: Output stream for progress messages.
            tree: The revision tree to upload.
            rev_id: The revision ID to upload.
            quiet: Whether to suppress progress output. Defaults to False.
        """
        self.branch = branch
        self.to_transport = to_transport
        self.outf = outf
        self.tree = tree
        self.rev_id = rev_id
        self.quiet = quiet
        self._pending_deletions = []
        self._pending_renames = []
        self._uploaded_revid = None
        self._ignored = None

    def _up_stat(self, relpath):
        """Get file statistics from the remote location.

        Args:
            relpath: Relative path to the file on the remote.

        Returns:
            stat_result: File statistics object.
        """
        return self.to_transport.stat(urlutils.escape(relpath))

    def _up_rename(self, old_path, new_path):
        """Rename a file or directory on the remote location.

        Args:
            old_path: Current path on the remote.
            new_path: New path on the remote.

        Returns:
            Result of the rename operation.
        """
        return self.to_transport.rename(
            urlutils.escape(old_path), urlutils.escape(new_path)
        )

    def _up_delete(self, relpath):
        """Delete a file on the remote location.

        Args:
            relpath: Relative path to the file to delete.

        Returns:
            Result of the delete operation.
        """
        return self.to_transport.delete(urlutils.escape(relpath))

    def _up_delete_tree(self, relpath):
        """Recursively delete a directory tree on the remote location.

        Args:
            relpath: Relative path to the directory tree to delete.

        Returns:
            Result of the delete tree operation.
        """
        return self.to_transport.delete_tree(urlutils.escape(relpath))

    def _up_mkdir(self, relpath, mode):
        """Create a directory on the remote location.

        Args:
            relpath: Relative path for the new directory.
            mode: Unix file permissions for the directory.

        Returns:
            Result of the mkdir operation.
        """
        return self.to_transport.mkdir(urlutils.escape(relpath), mode)

    def _up_rmdir(self, relpath):
        """Remove an empty directory on the remote location.

        Args:
            relpath: Relative path to the directory to remove.

        Returns:
            Result of the rmdir operation.
        """
        return self.to_transport.rmdir(urlutils.escape(relpath))

    def _up_put_bytes(self, relpath, bytes, mode):
        """Write bytes to a file on the remote location.

        Args:
            relpath: Relative path for the file.
            bytes: Content to write to the file.
            mode: Unix file permissions for the file.
        """
        self.to_transport.put_bytes(urlutils.escape(relpath), bytes, mode)

    def _up_get_bytes(self, relpath):
        """Read bytes from a file on the remote location.

        Args:
            relpath: Relative path to the file to read.

        Returns:
            bytes: Content of the file.
        """
        return self.to_transport.get_bytes(urlutils.escape(relpath))

    def set_uploaded_revid(self, rev_id):
        """Store the uploaded revision ID on the remote location.

        This writes the revision ID to a special file on the remote server
        to track which revision was last uploaded. This enables incremental
        uploads in future operations.

        Args:
            rev_id: The revision ID that was uploaded.
        """
        # XXX: Add tests for concurrent updates, etc.
        revid_path = self.branch.get_config_stack().get("upload_revid_location")
        self.to_transport.put_bytes(urlutils.escape(revid_path), rev_id)
        self._uploaded_revid = rev_id

    def get_uploaded_revid(self):
        """Retrieve the last uploaded revision ID from the remote location.

        This reads the revision ID from a special file on the remote server
        to determine what was previously uploaded. If no previous upload
        exists, returns NULL_REVISION.

        Returns:
            str: The revision ID of the last upload, or NULL_REVISION if
                no previous upload exists.
        """
        if self._uploaded_revid is None:
            revid_path = self.branch.get_config_stack().get("upload_revid_location")
            try:
                self._uploaded_revid = self._up_get_bytes(revid_path)
            except transport.NoSuchFile:
                # We have not uploaded to here.
                self._uploaded_revid = revision.NULL_REVISION
        return self._uploaded_revid

    def _get_ignored(self):
        """Get the Globster object for ignored file patterns.

        Reads the .bzrignore-upload file from the tree and creates a
        Globster object for matching ignored files. The result is cached
        for efficiency.

        Returns:
            Globster: Object for matching ignored file patterns.
        """
        if self._ignored is None:
            try:
                ignore_file_path = ".bzrignore-upload"
                ignore_file = self.tree.get_file(ignore_file_path)
            except transport.NoSuchFile:
                ignored_patterns = []
            else:
                ignored_patterns = ignores.parse_ignore_file(ignore_file)
            self._ignored = globbing.Globster(ignored_patterns)
        return self._ignored

    def is_ignored(self, relpath):
        """Check if a file path should be ignored during upload.

        Checks both the file itself and all parent directories against
        the ignore patterns from .bzrignore-upload.

        Args:
            relpath: Relative path to check.

        Returns:
            bool: True if the path should be ignored, False otherwise.
        """
        glob = self._get_ignored()
        ignored = glob.match(relpath)
        import os

        if not ignored:
            # We still need to check that all parents are not ignored
            dir = os.path.dirname(relpath)
            while dir and not ignored:
                ignored = glob.match(dir)
                if not ignored:
                    dir = os.path.dirname(dir)
        return ignored

    def upload_file(self, old_relpath, new_relpath, mode=None):
        """Upload a file to the remote location.

        Args:
            old_relpath: Path where the file should be placed on remote.
            new_relpath: Path to read the file content from in the tree.
            mode: Unix file permissions. If None, automatically determines
                based on executable status (755 for executable, 644 otherwise).
        """
        if mode is None:
            mode = 509 if self.tree.is_executable(new_relpath) else 436
        if not self.quiet:
            self.outf.write(f"Uploading {old_relpath}\n")
        self._up_put_bytes(old_relpath, self.tree.get_file_text(new_relpath), mode)

    def _force_clear(self, relpath):
        """Forcefully clear any existing item at the given path.

        Removes whatever exists at the path (file, directory, or symlink)
        to make way for uploading new content. Ignores errors if nothing
        exists at the path.

        Args:
            relpath: Relative path to clear on the remote.
        """
        try:
            st = self._up_stat(relpath)
            if stat.S_ISDIR(st.st_mode):
                # A simple rmdir may not be enough
                if not self.quiet:
                    self.outf.write(
                        f"Clearing {self.to_transport.external_url()}/{relpath}\n"
                    )
                self._up_delete_tree(relpath)
            elif stat.S_ISLNK(st.st_mode):
                if not self.quiet:
                    self.outf.write(
                        f"Clearing {self.to_transport.external_url()}/{relpath}\n"
                    )
                self._up_delete(relpath)
        except errors.PathError:
            pass

    def upload_file_robustly(self, relpath, mode=None):
        """Upload a file, clearing the way on the remote side.

        When doing a full upload, it may happen that a directory exists where
        we want to put our file. This method handles such collisions by
        forcefully clearing any existing item at the target path before
        uploading the file.

        Args:
            relpath: Path where the file should be uploaded.
            mode: Unix file permissions. If None, automatically determines
                based on executable status.
        """
        self._force_clear(relpath)
        self.upload_file(relpath, relpath, mode)

    def upload_symlink(self, relpath, target):
        """Create a symbolic link on the remote location.

        Args:
            relpath: Path where the symlink should be created.
            target: Target path that the symlink should point to.
        """
        self.to_transport.symlink(target, relpath)

    def upload_symlink_robustly(self, relpath, target):
        """Upload a symlink, clearing any existing item at the path.

        Creates a symbolic link on the remote location, first removing
        any existing file or directory at the target path. The target
        path is normalized relative to the symlink's directory.

        Args:
            relpath: Path where the symlink should be created.
            target: Target path that the symlink should point to.
        """
        self._force_clear(relpath)
        # Target might not be there at this time; dummy file should be
        # overwritten at some point, possibly by another upload.
        target = osutils.normpath(osutils.pathjoin(osutils.dirname(relpath), target))
        self.upload_symlink(relpath, target)

    def make_remote_dir(self, relpath, mode=None):
        """Create a directory on the remote location.

        Args:
            relpath: Path for the new directory.
            mode: Unix file permissions. Defaults to 0o775 if not specified.
        """
        if mode is None:
            mode = 0o775
        self._up_mkdir(relpath, mode)

    def make_remote_dir_robustly(self, relpath, mode=None):
        """Create a remote directory, clearing the way on the remote side.

        When doing a full upload, it may happen that a file exists where we
        want to create our directory. This method checks if something exists
        at the target path and removes it if it's not a directory.

        Args:
            relpath: Path for the new directory.
            mode: Unix file permissions. Defaults to 0o775 if not specified.
        """
        try:
            st = self._up_stat(relpath)
            if not stat.S_ISDIR(st.st_mode):
                if not self.quiet:
                    self.outf.write(
                        f"Deleting {self.to_transport.external_url()}/{relpath}\n"
                    )
                self._up_delete(relpath)
            else:
                # Ok the remote dir already exists, nothing to do
                return
        except errors.PathError:
            pass
        self.make_remote_dir(relpath, mode)

    def delete_remote_file(self, relpath):
        """Delete a file from the remote location.

        Args:
            relpath: Path to the file to delete.
        """
        if not self.quiet:
            self.outf.write(f"Deleting {relpath}\n")
        self._up_delete(relpath)

    def delete_remote_dir(self, relpath):
        """Delete an empty directory from the remote location.

        Args:
            relpath: Path to the directory to delete.
        """
        if not self.quiet:
            self.outf.write(f"Deleting {relpath}\n")
        self._up_rmdir(relpath)
        # XXX: Add a test where a subdir is ignored but we still want to
        # delete the dir -- vila 100106

    def delete_remote_dir_maybe(self, relpath):
        """Try to delete a directory, deferring if not empty.

        Attempts to delete a directory. If it fails (typically because
        it's not empty), adds it to pending deletions to retry later
        after its contents have been removed.

        Args:
            relpath: Path to the directory to delete.
        """
        try:
            self._up_rmdir(relpath)
        # any kind of PathError would be OK, though we normally expect
        # DirectoryNotEmpty
        except errors.PathError:
            self._pending_deletions.append(relpath)

    def finish_deletions(self):
        """Complete all pending directory deletions.

        Processes directories that couldn't be deleted earlier because
        they weren't empty. Deletions are performed in reverse order
        to ensure child directories are removed before their parents.
        """
        if self._pending_deletions:
            # Process the previously failed deletions in reverse order to
            # delete children before parents
            for relpath in reversed(self._pending_deletions):
                self._up_rmdir(relpath)
            # The following shouldn't be needed since we use it once per
            # upload, but better safe than sorry ;-)
            self._pending_deletions = []

    def rename_remote(self, old_relpath, new_relpath):
        """Rename a remote file or directory taking care of collisions.

        To avoid collisions during bulk renames, each renamed target is
        temporarily assigned a unique name. When all renames have been done,
        each target get its proper name. This two-stage process prevents
        conflicts when swapping file names or performing circular renames.

        Args:
            old_relpath: Current path of the item to rename.
            new_relpath: Desired new path for the item.
        """
        # We generate a sufficiently random name to *assume* that
        # no collisions will occur and don't worry about it (nor
        # handle it).
        import os
        import random
        import time

        stamp = ".tmp.%.9f.%d.%d" % (
            time.time(),
            os.getpid(),
            random.randint(0, 0x7FFFFFFF),  # noqa: S311
        )
        if not self.quiet:
            self.outf.write(f"Renaming {old_relpath} to {new_relpath}\n")
        self._up_rename(old_relpath, stamp)
        self._pending_renames.append((stamp, new_relpath))

    def finish_renames(self):
        """Complete all pending rename operations.

        Finishes the two-stage rename process by renaming all temporarily
        named files to their final destinations.
        """
        for stamp, new_path in self._pending_renames:
            self._up_rename(stamp, new_path)
        # The following shouldn't be needed since we use it once per upload,
        # but better safe than sorry ;-)
        self._pending_renames = []

    def upload_full_tree(self):
        """Upload the entire working tree to the remote location.

        Performs a complete upload of all files, directories, and symlinks
        in the working tree, respecting ignore patterns. This is used for
        initial uploads or when incremental upload is not possible.
        """
        self.to_transport.ensure_base()  # XXX: Handle errors (add
        # --create-prefix option ?)
        with self.tree.lock_read():
            for relpath, ie in self.tree.iter_entries_by_dir():
                if relpath in ("", ".bzrignore", ".bzrignore-upload"):
                    # skip root ('')
                    # .bzrignore and .bzrignore-upload have no meaning outside
                    # a working tree so do not upload them
                    continue
                if self.is_ignored(relpath):
                    if not self.quiet:
                        self.outf.write(f"Ignoring {relpath}\n")
                    continue
                if ie.kind == "file":
                    self.upload_file_robustly(relpath)
                elif ie.kind == "symlink":
                    try:
                        self.upload_symlink_robustly(relpath, ie.symlink_target)
                    except errors.TransportNotPossible:
                        if not self.quiet:
                            target = self.tree.path_content_summary(relpath)[3]
                            self.outf.write(
                                f"Not uploading symlink {relpath} -> {target}\n"
                            )
                elif ie.kind == "directory":
                    self.make_remote_dir_robustly(relpath)
                else:
                    raise NotImplementedError
            self.set_uploaded_revid(self.rev_id)

    def upload_tree(self):
        """Upload the working tree, using incremental updates if possible.

        Attempts to perform an incremental upload by comparing the current
        tree with the previously uploaded revision. Falls back to full
        upload if no previous upload is found or if the uploaded revision
        is not in the repository.
        """
        # If we can't find the revid file on the remote location, upload the
        # full tree instead
        rev_id = self.get_uploaded_revid()

        if rev_id == revision.NULL_REVISION:
            if not self.quiet:
                self.outf.write(
                    "No uploaded revision id found, switching to full upload\n"
                )
            self.upload_full_tree()
            # We're done
            return

        # Check if the revision hasn't already been uploaded
        if rev_id == self.rev_id and not self.quiet:
            self.outf.write("Remote location already up to date\n")

        from_tree = self.branch.repository.revision_tree(rev_id)
        self.to_transport.ensure_base()  # XXX: Handle errors (add
        # --create-prefix option ?)
        changes = self.tree.changes_from(from_tree)
        with self.tree.lock_read():
            for change in changes.removed:
                if self.is_ignored(change.path[0]):
                    if not self.quiet:
                        self.outf.write(f"Ignoring {change.path[0]}\n")
                    continue
                if change.kind[0] == "file":
                    self.delete_remote_file(change.path[0])
                elif change.kind[0] == "directory":
                    self.delete_remote_dir_maybe(change.path[0])
                elif change.kind[0] == "symlink":
                    self.delete_remote_file(change.path[0])
                else:
                    raise NotImplementedError

            for change in changes.renamed:
                if self.is_ignored(change.path[0]) and self.is_ignored(change.path[1]):
                    if not self.quiet:
                        self.outf.write(f"Ignoring {change.path[0]}\n")
                        self.outf.write(f"Ignoring {change.path[1]}\n")
                    continue
                if change.changed_content:
                    # We update the change.path[0] content because renames and
                    # deletions are differed.
                    self.upload_file(change.path[0], change.path[1])
                self.rename_remote(change.path[0], change.path[1])
            self.finish_renames()
            self.finish_deletions()

            for change in changes.kind_changed:
                if self.is_ignored(change.path[1]):
                    if not self.quiet:
                        self.outf.write(f"Ignoring {change.path[1]}\n")
                    continue
                if change.kind[0] in ("file", "symlink"):
                    self.delete_remote_file(change.path[0])
                elif change.kind[0] == "directory":
                    self.delete_remote_dir(change.path[0])
                else:
                    raise NotImplementedError

                if change.kind[1] == "file":
                    self.upload_file(change.path[1], change.path[1])
                elif change.kind[1] == "symlink":
                    target = self.tree.get_symlink_target(change.path[1])
                    self.upload_symlink(change.path[1], target)
                elif change.kind[1] == "directory":
                    self.make_remote_dir(change.path[1])
                else:
                    raise NotImplementedError

            for change in changes.added + changes.copied:
                if self.is_ignored(change.path[1]):
                    if not self.quiet:
                        self.outf.write(f"Ignoring {change.path[1]}\n")
                    continue
                if change.kind[1] == "file":
                    self.upload_file(change.path[1], change.path[1])
                elif change.kind[1] == "directory":
                    self.make_remote_dir(change.path[1])
                elif change.kind[1] == "symlink":
                    target = self.tree.get_symlink_target(change.path[1])
                    try:
                        self.upload_symlink(change.path[1], target)
                    except errors.TransportNotPossible:
                        if not self.quiet:
                            self.outf.write(
                                f"Not uploading symlink {change.path[1]} -> {target}\n"
                            )
                else:
                    raise NotImplementedError

            # XXX: Add a test for exec_change
            for change in changes.modified:
                if self.is_ignored(change.path[1]):
                    if not self.quiet:
                        self.outf.write(f"Ignoring {change.path[1]}\n")
                    continue
                if change.kind[1] == "file":
                    self.upload_file(change.path[1], change.path[1])
                elif change.kind[1] == "symlink":
                    target = self.tree.get_symlink_target(change.path[1])
                    self.upload_symlink(change.path[1], target)
                else:
                    raise NotImplementedError

            self.set_uploaded_revid(self.rev_id)


class CannotUploadToWorkingTree(errors.CommandError):
    """Error raised when attempting to upload to a Bazaar working tree.

    This error occurs when the upload destination is detected to be
    a Bazaar-controlled working tree, which is not a valid upload target.
    """

    _fmt = 'Cannot upload to a bzr managed working tree: %(url)s".'


class DivergedUploadedTree(errors.CommandError):
    """Error raised when the branch and uploaded tree have diverged.

    This error occurs when the revision to be uploaded is not a descendant
    of the previously uploaded revision, indicating that the remote tree
    and local branch have diverged.
    """

    _fmt = (
        "Your branch (%(revid)s)"
        " and the uploaded tree (%(uploaded_revid)s) have diverged: "
    )


class cmd_upload(commands.Command):
    """Upload a working tree, as a whole or incrementally.

    If no destination is specified use the last one used.
    If no revision is specified upload the changes since the last upload.

    Changes include files added, renamed, modified or removed.
    """

    _see_also = ["plugins/upload"]
    takes_args = ["location?"]
    takes_options = [
        "revision",
        "remember",
        "overwrite",
        option.Option("full", "Upload the full working tree."),
        option.Option("quiet", "Do not output what is being done.", short_name="q"),
        option.Option(
            "directory",
            help="Branch to upload from, "
            "rather than the one containing the working directory.",
            short_name="d",
            type=str,
        ),
        option.Option(
            "auto",
            "Trigger an upload from this branch whenever the tip revision changes.",
        ),
    ]

    def run(
        self,
        location=None,
        full=False,
        revision=None,
        remember=None,
        directory=None,
        quiet=False,
        auto=None,
        overwrite=False,
    ):
        """Execute the upload command.

        Args:
            location: URL of the upload destination. If None, uses the
                previously saved location.
            full: If True, forces a full upload instead of incremental.
            revision: Specific revision to upload. If None, uploads the
                latest revision.
            remember: If True, saves the upload location for future use.
            directory: Directory containing the branch to upload from.
                Defaults to current directory.
            quiet: If True, suppresses progress output.
            auto: If True, enables automatic uploads on branch changes.
            overwrite: If True, allows uploading even if trees have diverged.

        Raises:
            CommandError: If no upload location is specified or saved.
            UncommittedChanges: If there are uncommitted changes in the tree.
            CannotUploadToWorkingTree: If destination is a Bazaar working tree.
            DivergedUploadedTree: If trees have diverged and overwrite is False.
        """
        if directory is None:
            directory = "."

        (wt, branch, relpath) = controldir.ControlDir.open_containing_tree_or_branch(
            directory
        )

        locked = wt if wt else branch
        with locked.lock_read():
            if wt:
                changes = wt.changes_from(wt.basis_tree())

                if revision is None and changes.has_changed():
                    raise errors.UncommittedChanges(wt)

            conf = branch.get_config_stack()
            if location is None:
                stored_loc = conf.get("upload_location")
                if stored_loc is None:
                    raise errors.CommandError("No upload location known or specified.")
                else:
                    # FIXME: Not currently tested
                    display_url = urlutils.unescape_for_display(
                        stored_loc, self.outf.encoding
                    )
                    self.outf.write(f"Using saved location: {display_url}\n")
                    location = stored_loc

            to_transport = transport.get_transport(location)

            # Check that we are not uploading to a existing working tree.
            try:
                to_bzr_dir = controldir.ControlDir.open_from_transport(to_transport)
                has_wt = to_bzr_dir.has_workingtree()
            except errors.NotBranchError:
                has_wt = False
            except errors.NotLocalUrl:
                # The exception raised is a bit weird... but that's life.
                has_wt = True

            if has_wt:
                raise CannotUploadToWorkingTree(url=location)
            if revision is None:
                rev_id = branch.last_revision()
            else:
                if len(revision) != 1:
                    raise errors.CommandError(
                        "bzr upload --revision takes exactly 1 argument"
                    )
                rev_id = revision[0].in_history(branch).rev_id

            tree = branch.repository.revision_tree(rev_id)

            uploader = BzrUploader(
                branch, to_transport, self.outf, tree, rev_id, quiet=quiet
            )

            if not overwrite:
                prev_uploaded_rev_id = uploader.get_uploaded_revid()
                graph = branch.repository.get_graph()
                if not graph.is_ancestor(prev_uploaded_rev_id, rev_id):
                    raise DivergedUploadedTree(
                        revid=rev_id, uploaded_revid=prev_uploaded_rev_id
                    )
            if full:
                uploader.upload_full_tree()
            else:
                uploader.upload_tree()

        # We uploaded successfully, remember it
        with branch.lock_write():
            upload_location = conf.get("upload_location")
            if upload_location is None or remember:
                conf.set("upload_location", urlutils.unescape(to_transport.base))
            if auto is not None:
                conf.set("upload_auto", auto)
