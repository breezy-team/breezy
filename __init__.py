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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Upload a working tree, incrementally.

The only bzr-related info uploaded with the working tree is the corresponding
revision id. The uploaded working tree is not linked to any other bzr data.

The intended use is for web developers with no shell access on their web site
forced to used FTP or SFTP to upload thei site content.

Known limitations:
- Symlinks are ignored,

- chmod bits are not supported.
"""

# TODO: the chmod bits *can* be supported via the upload protocols
# (i.e. poorly), but since the web developers use these protocols to upload
# manually, it is expected that the associated web server is coherent with
# their presence/absence. In other words, if a web hosting provider requires
# chmod bits but don't provide an ftp server that support them, well, better
# find another provider ;-)

from bzrlib import (
    commands,
    lazy_import,
    option,
    )
lazy_import.lazy_import(globals(), """
from bzrlib import (
    branch,
    errors,
    revisionspec,
    transport,
    )
""")

class cmd_upload(commands.Command):
    """Upload a working tree, as a whole or incrementally.

    If no destination is specified use the last one used.
    If no revision is specified upload the changes since the last upload.
    """
    takes_args = ['location?']
    takes_options = [
        'revision',
        'remember',
        option.Option('full', 'Upload the full working tree.'),
        option.Option('directory',
                      help='Branch to upload from, '
                      'rather than the one containing the working directory.',
                      short_name='d',
                      type=unicode,
                      ),
       ]

    def run(self, location, full=False, revision=None, remember=None,
            directory=None,
            ):
        if directory is None:
            directory = u'.'
        self.branch = branch.Branch.open_containing(directory)[0]

        if location is None:
            stored_loc = self.get_upload_location()
            if stored_loc is None:
                raise errors.BzrCommandError('No upload location'
                                             ' known or specified.')
            else:
                display_url = urlutils.unescape_for_display(stored_loc,
                        self.outf.encoding)
                self.outf.write("Using saved location: %s\n" % display_url)
                location = stored_loc

        self.to_transport = transport.get_transport(location)
        if revision is None:
            rev_id = self.branch.last_revision()
        else:
            if len(revision) != 1:
                raise errors.BzrCommandError(
                    'bzr upload --revision takes exactly 1 argument')
            rev_id = revision[0].in_history(self.branch).rev_id

        self.tree = self.branch.repository.revision_tree(rev_id)
        self.rev_id = rev_id
        self._pending_renames = []
        self._pending_deletions = []
        if full:
            self.upload_full_tree()
        else:
            self.upload_tree()

        # We uploaded successfully, remember it
        if self.get_upload_location() is None or remember:
            self.set_upload_location(self.to_transport.base)

    def set_upload_location(self, location):
        self.branch.get_config().set_user_option('upload_location', location)

    def get_upload_location(self):
        return self.branch.get_config().get_user_option('upload_location')

    bzr_upload_revid_file_name = '.bzr-upload.revid'

    def set_uploaded_revid(self, rev_id):
        # XXX: Add tests for concurrent updates, etc.
        self.to_transport.put_bytes(self.bzr_upload_revid_file_name, rev_id)

    def get_uploaded_revid(self):
        return self.to_transport.get_bytes(self.bzr_upload_revid_file_name)

    def upload_file(self, relpath, id):
        self.to_transport.put_bytes(relpath, self.tree.get_file_text(id))

    def make_remote_dir(self, relpath):
        # XXX: handle mode
        self.to_transport.mkdir(relpath)

    def delete_remote_file(self, relpath):
        self.to_transport.delete(relpath)

    def delete_remote_dir(self, relpath):
        self.to_transport.rmdir(relpath)

    def delete_remote_dir_maybe(self, relpath):
        """Try to delete relpath, keeping failures to retry later."""
        try:
            self.to_transport.rmdir(relpath)
        # any kind of PathError would be OK, though we normally expect
        # DirectoryNotEmpty
        except errors.PathError:
            self._pending_deletions.append(relpath)

    def finish_deletions(self):
        if self._pending_deletions:
            # Process the previously failed deletions in reverse order to
            # delete children before parents
            for relpath in reversed(self._pending_deletions):
                self.to_transport.rmdir(relpath)
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

        stamp = '.tmp.%.9f.%d.%d' % (time.time(),
                                     os.getpid(),
                                     random.randint(0,0x7FFFFFFF))
        self.to_transport.rename(old_relpath, stamp)
        self._pending_renames.append((stamp, new_relpath))

    def finish_renames(self):
        for (stamp, new_path) in self._pending_renames:
            self.to_transport.rename(stamp, new_path)
        # The following shouldn't be needed since we use it once per upload,
        # but better safe than sorry ;-)
        self._pending_renames = []

    def upload_full_tree(self):
        self.to_transport.ensure_base() # XXX: Handle errors (add
                                        # --create-prefix option ?)
        self.tree.lock_read()
        try:
            for dp, ie in self.tree.inventory.iter_entries():
                if dp in ('', '.bzrignore'):
                    # skip root ('')
                    # .bzrignore has no meaning outside of a working tree
                    # so do not upload it
                    continue
                # XXX: We need to be more robust in case we upload on top of an
                # existing tree which may contains existing files or dirs whose
                # names will make attempts to upload dirs or files fail.
                if ie.kind == 'file':
                    self.upload_file(dp, ie.file_id)
                elif ie.kind == 'directory':
                    try:
                        self.make_remote_dir(dp)
                    except errors.FileExists:
                        # The directory existed before the upload
                        pass
                else:
                    raise NotImplementedError
            self.set_uploaded_revid(self.rev_id)
        finally:
            self.tree.unlock()

    def upload_tree(self):
        # XXX: if we get NoSuchFile shoudl we consider it the first upload ever
        # and upload changes since the first revision ?  Add tests.
        rev_id = self.get_uploaded_revid()
        # XXX: errors out if rev_id not in branch history (probably someone
        # uploaded from a different branch).
        from_tree = self.branch.repository.revision_tree(rev_id)
        self.to_transport.ensure_base() # XXX: Handle errors (add
                                        # --create-prefix option ?)
        changes = self.tree.changes_from(from_tree)
        self.tree.lock_read()
        try:
            # XXX: handle kind_changed
            for (path, id, kind) in changes.removed:
                if kind is 'file':
                    self.delete_remote_file(path)
                elif kind is  'directory':
                    self.delete_remote_dir_maybe(path)
                else:
                    raise NotImplementedError

            for (old_path, new_path, id, kind,
                 content_change, exec_change) in changes.renamed:
                self.rename_remote(old_path, new_path)
            self.finish_renames()
            self.finish_deletions()

            for (path, id, kind) in changes.added:
                if kind is 'file':
                    self.upload_file(path, id)
                elif kind is 'directory':
                    self.make_remote_dir(path)
                else:
                    raise NotImplementedError

            # XXX: Add a test for exec_change
            for (path, id, kind,
                 content_change, exec_change) in changes.modified:
                if kind is 'file':
                    self.upload_file(path, id)
                else:
                    raise NotImplementedError

            self.set_uploaded_revid(self.rev_id)
        finally:
            self.tree.unlock()


commands.register_command(cmd_upload)


def test_suite():
    from bzrlib.tests import TestUtil

    suite = TestUtil.TestSuite()
    loader = TestUtil.TestLoader()
    testmod_names = [
        'test_upload',
        ]

    suite.addTest(loader.loadTestsFromModuleNames(
            ["%s.%s" % (__name__, tmn) for tmn in testmod_names]))
    return suite
