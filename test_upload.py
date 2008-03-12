# Copyright (C) 2007 Canonical Ltd
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

import os


from bzrlib import (
    errors,
    revisionspec,
    tests,
    )

from bzrlib.plugins.upload import cmd_upload


class TestUpload(tests.TestCaseWithTransport):

    def _create_branch(self):
        tree = self.make_branch_and_tree('branch')
        self.build_tree_contents([('branch/hello', 'foo')])
        tree.add('hello')
        tree.commit('setup')

        self.build_tree_contents([('branch/hello', 'bar'),
                                  ('branch/goodbye', 'baz')])
        tree.add('goodbye')
        tree.commit('setup')
        return tree

    def test_full_upload(self):
        self._create_branch()

        os.chdir('branch')
        upload = cmd_upload()

        upload.run('../upload', full=True)

        self.assertFileEqual('bar', '../upload/hello')
        self.assertFileEqual('baz', '../upload/goodbye')

    def test_incremental_upload(self):
        self._create_branch()

        os.chdir('branch')
        upload = cmd_upload()

        # Upload revision 1 only
        revspec = revisionspec.RevisionSpec.from_string('1')
        upload.run('../upload', revision=[revspec], full=True)

        self.assertFileEqual('foo', '../upload/hello')
        self.failIfExists('../upload/goodbye')

        # Upload current revision
        upload.run('../upload')

        self.assertFileEqual('bar','../upload/hello')
        self.assertFileEqual('baz', '../upload/goodbye')

    def test_invalid_revspec(self):
        self._create_branch()
        rev1 = revisionspec.RevisionSpec.from_string('1')
        rev2 = revisionspec.RevisionSpec.from_string('2')
        upload = cmd_upload()
        self.assertRaises(errors.BzrCommandError, upload.run,
                          '../upload', revision=[rev1, rev2])

