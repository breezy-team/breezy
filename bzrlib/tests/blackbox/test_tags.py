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

"""Tests for commands related to tags"""

from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir
from bzrlib.tests import TestCaseWithTransport
from bzrlib.repository import RepositoryFormatKnit2


class TestTagging(TestCaseWithTransport):

    # as of 0.14, the default format doesn't do tags so we need to use a
    # specific format
    
    def make_branch_and_tree(self, relpath):
        control = BzrDir.create(relpath)
        repo = RepositoryFormatKnit2().initialize(control)
        control.create_branch()
        return control.create_workingtree()

    def test_tag_command_help(self):
        out, err = self.run_bzr_captured(['help', 'tag'])
        self.assertContainsRe(out, 'Create a tag')

    def test_cannot_tag_range(self):
        out, err = self.run_bzr('tag', '-r1..10', 'name', retcode=3)
        self.assertContainsRe(err,
            "Tags can only be placed on a single revision")

    def test_tag_current_rev(self):
        t = self.make_branch_and_tree('branch')
        t.commit(allow_pointless=True, message='initial commit',
            rev_id='first-revid')
        # make a tag through the command line
        out, err = self.run_bzr('tag', '-d', 'branch', 'NEWTAG')
        self.assertContainsRe(out, 'created tag NEWTAG')
        # tag should be observable through the api
        repo = t.branch.repository
        self.assertEquals(repo.get_tag_dict(), dict(NEWTAG='first-revid'))
        # can also create tags using -r
        self.run_bzr('tag', '-d', 'branch', 'tag2', '-r1')
        self.assertEquals(repo.lookup_tag('tag2'), 'first-revid')
