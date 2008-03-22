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

The only bzr-related info uploaded with the working tree is the corrseponding
revision id. The uploaded working tree is not linked to any other bzr data.

The intended use is for web sites.
"""

from bzrlib import (
    branch,
    commands,
    errors,
    option,
    revisionspec,
    transport,
    )

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

    def upload_full_tree(self):
        self.to_transport.ensure_base() # XXX: Handle errors
        self.tree.lock_read()
        try:
            for dp, ie in self.tree.inventory.iter_entries():
                if dp in ('', '.bzrignore'):
                    # skip root ('')
                    # .bzrignore has no meaning outside of a working tree
                    # so do not upload it
                    continue

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
        # XXX: errors out if NoSuchFile and recommand --full on first upload ?
        # Add tests.
        rev_id = self.get_uploaded_revid()
        # XXX: errors out if rev_id not in branch history (probably someone
        # uploaded from a different branch).
        from_tree = self.branch.repository.revision_tree(rev_id)
        self.to_transport.ensure_base() # XXX: Handle errors
        changes = self.tree.changes_from(from_tree)
        self.tree.lock_read()
        try:
            # XXX: handle removed, renamed, kind_changed
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
