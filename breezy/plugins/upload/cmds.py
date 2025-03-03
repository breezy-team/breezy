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
    def __init__(self, branch, to_transport, outf, tree, rev_id, quiet=False):
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
        return self.to_transport.stat(urlutils.escape(relpath))

    def _up_rename(self, old_path, new_path):
        return self.to_transport.rename(
            urlutils.escape(old_path), urlutils.escape(new_path)
        )

    def _up_delete(self, relpath):
        return self.to_transport.delete(urlutils.escape(relpath))

    def _up_delete_tree(self, relpath):
        return self.to_transport.delete_tree(urlutils.escape(relpath))

    def _up_mkdir(self, relpath, mode):
        return self.to_transport.mkdir(urlutils.escape(relpath), mode)

    def _up_rmdir(self, relpath):
        return self.to_transport.rmdir(urlutils.escape(relpath))

    def _up_put_bytes(self, relpath, bytes, mode):
        self.to_transport.put_bytes(urlutils.escape(relpath), bytes, mode)

    def _up_get_bytes(self, relpath):
        return self.to_transport.get_bytes(urlutils.escape(relpath))

    def set_uploaded_revid(self, rev_id):
        # XXX: Add tests for concurrent updates, etc.
        revid_path = self.branch.get_config_stack().get("upload_revid_location")
        self.to_transport.put_bytes(urlutils.escape(revid_path), rev_id)
        self._uploaded_revid = rev_id

    def get_uploaded_revid(self):
        if self._uploaded_revid is None:
            revid_path = self.branch.get_config_stack().get("upload_revid_location")
            try:
                self._uploaded_revid = self._up_get_bytes(revid_path)
            except transport.NoSuchFile:
                # We have not uploaded to here.
                self._uploaded_revid = revision.NULL_REVISION
        return self._uploaded_revid

    def _get_ignored(self):
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
        if mode is None:
            if self.tree.is_executable(new_relpath):
                mode = 0o775
            else:
                mode = 0o664
        if not self.quiet:
            self.outf.write("Uploading {}\n".format(old_relpath))
        self._up_put_bytes(old_relpath, self.tree.get_file_text(new_relpath), mode)

    def _force_clear(self, relpath):
        try:
            st = self._up_stat(relpath)
            if stat.S_ISDIR(st.st_mode):
                # A simple rmdir may not be enough
                if not self.quiet:
                    self.outf.write(
                        "Clearing {}/{}\n".format(
                            self.to_transport.external_url(), relpath
                        )
                    )
                self._up_delete_tree(relpath)
            elif stat.S_ISLNK(st.st_mode):
                if not self.quiet:
                    self.outf.write(
                        "Clearing {}/{}\n".format(
                            self.to_transport.external_url(), relpath
                        )
                    )
                self._up_delete(relpath)
        except errors.PathError:
            pass

    def upload_file_robustly(self, relpath, mode=None):
        """Upload a file, clearing the way on the remote side.

        When doing a full upload, it may happen that a directory exists where
        we want to put our file.
        """
        self._force_clear(relpath)
        self.upload_file(relpath, relpath, mode)

    def upload_symlink(self, relpath, target):
        self.to_transport.symlink(target, relpath)

    def upload_symlink_robustly(self, relpath, target):
        """Handle uploading symlinks."""
        self._force_clear(relpath)
        # Target might not be there at this time; dummy file should be
        # overwritten at some point, possibly by another upload.
        target = osutils.normpath(osutils.pathjoin(osutils.dirname(relpath), target))
        self.upload_symlink(relpath, target)

    def make_remote_dir(self, relpath, mode=None):
        if mode is None:
            mode = 0o775
        self._up_mkdir(relpath, mode)

    def make_remote_dir_robustly(self, relpath, mode=None):
        """Create a remote directory, clearing the way on the remote side.

        When doing a full upload, it may happen that a file exists where we
        want to create our directory.
        """
        try:
            st = self._up_stat(relpath)
            if not stat.S_ISDIR(st.st_mode):
                if not self.quiet:
                    self.outf.write(
                        "Deleting {}/{}\n".format(
                            self.to_transport.external_url(), relpath
                        )
                    )
                self._up_delete(relpath)
            else:
                # Ok the remote dir already exists, nothing to do
                return
        except errors.PathError:
            pass
        self.make_remote_dir(relpath, mode)

    def delete_remote_file(self, relpath):
        if not self.quiet:
            self.outf.write("Deleting {}\n".format(relpath))
        self._up_delete(relpath)

    def delete_remote_dir(self, relpath):
        if not self.quiet:
            self.outf.write("Deleting {}\n".format(relpath))
        self._up_rmdir(relpath)
        # XXX: Add a test where a subdir is ignored but we still want to
        # delete the dir -- vila 100106

    def delete_remote_dir_maybe(self, relpath):
        """Try to delete relpath, keeping failures to retry later."""
        try:
            self._up_rmdir(relpath)
        # any kind of PathError would be OK, though we normally expect
        # DirectoryNotEmpty
        except errors.PathError:
            self._pending_deletions.append(relpath)

    def finish_deletions(self):
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
        each target get its proper name.
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
            random.randint(0, 0x7FFFFFFF),
        )
        if not self.quiet:
            self.outf.write("Renaming {} to {}\n".format(old_relpath, new_relpath))
        self._up_rename(old_relpath, stamp)
        self._pending_renames.append((stamp, new_relpath))

    def finish_renames(self):
        for stamp, new_path in self._pending_renames:
            self._up_rename(stamp, new_path)
        # The following shouldn't be needed since we use it once per upload,
        # but better safe than sorry ;-)
        self._pending_renames = []

    def upload_full_tree(self):
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
                        self.outf.write("Ignoring {}\n".format(relpath))
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
                                "Not uploading symlink {} -> {}\n".format(
                                    relpath, target
                                )
                            )
                elif ie.kind == "directory":
                    self.make_remote_dir_robustly(relpath)
                else:
                    raise NotImplementedError
            self.set_uploaded_revid(self.rev_id)

    def upload_tree(self):
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
        if rev_id == self.rev_id:
            if not self.quiet:
                self.outf.write("Remote location already up to date\n")

        from_tree = self.branch.repository.revision_tree(rev_id)
        self.to_transport.ensure_base()  # XXX: Handle errors (add
        # --create-prefix option ?)
        changes = self.tree.changes_from(from_tree)
        with self.tree.lock_read():
            for change in changes.removed:
                if self.is_ignored(change.path[0]):
                    if not self.quiet:
                        self.outf.write("Ignoring {}\n".format(change.path[0]))
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
                        self.outf.write("Ignoring {}\n".format(change.path[0]))
                        self.outf.write("Ignoring {}\n".format(change.path[1]))
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
                        self.outf.write("Ignoring {}\n".format(change.path[1]))
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
                        self.outf.write("Ignoring {}\n".format(change.path[1]))
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
                                "Not uploading symlink {} -> {}\n".format(
                                    change.path[1], target
                                )
                            )
                else:
                    raise NotImplementedError

            # XXX: Add a test for exec_change
            for change in changes.modified:
                if self.is_ignored(change.path[1]):
                    if not self.quiet:
                        self.outf.write("Ignoring {}\n".format(change.path[1]))
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
    _fmt = 'Cannot upload to a bzr managed working tree: %(url)s".'


class DivergedUploadedTree(errors.CommandError):
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
        if directory is None:
            directory = "."

        (wt, branch, relpath) = controldir.ControlDir.open_containing_tree_or_branch(
            directory
        )

        if wt:
            locked = wt
        else:
            locked = branch
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
                    self.outf.write("Using saved location: {}\n".format(display_url))
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
