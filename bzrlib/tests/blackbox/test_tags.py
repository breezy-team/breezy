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

from bzrlib import bzrdir
from bzrlib.branch import (
    Branch,
    )
from bzrlib.bzrdir import BzrDir
from bzrlib.tests import TestCaseWithTransport
from bzrlib.repository import (
    Repository,
    )
from bzrlib.workingtree import WorkingTree


class TestTagging(TestCaseWithTransport):

    # as of 0.14, the default format doesn't do tags so we need to use a
    # specific format
    
    def make_branch_and_tree(self, relpath):
        format = bzrdir.format_registry.make_bzrdir('dirstate-with-subtree')
        return TestCaseWithTransport.make_branch_and_tree(self, relpath,
            format=format)

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
        self.assertContainsRe(out, 'Created tag NEWTAG.')
        # tag should be observable through the api
        self.assertEquals(t.branch.tags.get_tag_dict(),
                dict(NEWTAG='first-revid'))
        # can also create tags using -r
        self.run_bzr('tag', '-d', 'branch', 'tag2', '-r1')
        self.assertEquals(t.branch.tags.lookup_tag('tag2'), 'first-revid')
        # regression test: make sure a unicode revision from the user
        # gets turned into a str object properly. The use of a unicode
        # object for the revid is intentional.
        self.run_bzr('tag', '-d', 'branch', 'tag3', u'-rrevid:first-revid')
        self.assertEquals(t.branch.tags.lookup_tag('tag3'), 'first-revid')
        # can also delete an existing tag
        out, err = self.run_bzr('tag', '--delete', '-d', 'branch', 'tag2')
        # cannot replace an existing tag normally
        out, err = self.run_bzr('tag', '-d', 'branch', 'NEWTAG', retcode=3)
        self.assertContainsRe(err, 'Tag NEWTAG already exists\\.')
        # ... but can if you use --force
        out, err = self.run_bzr('tag', '-d', 'branch', 'NEWTAG', '--force')

    def test_branch_push_pull_merge_copies_tags(self):
        t = self.make_branch_and_tree('branch1')
        t.commit(allow_pointless=True, message='initial commit',
            rev_id='first-revid')
        b1 = t.branch
        b1.tags.set_tag('tag1', 'first-revid')
        # branching copies the tag across
        self.run_bzr('branch', 'branch1', 'branch2')
        b2 = Branch.open('branch2')
        self.assertEquals(b2.tags.lookup_tag('tag1'), 'first-revid')
        # make a new tag and pull it
        b1.tags.set_tag('tag2', 'twa')
        self.run_bzr('pull', '-d', 'branch2', 'branch1')
        self.assertEquals(b2.tags.lookup_tag('tag2'), 'twa')
        # make a new tag and push it
        b1.tags.set_tag('tag3', 'san')
        self.run_bzr('push', '-d', 'branch1', 'branch2')
        self.assertEquals(b2.tags.lookup_tag('tag3'), 'san')
        # make a new tag and merge it
        t.commit(allow_pointless=True, message='second commit',
            rev_id='second-revid')
        t2 = WorkingTree.open('branch2')
        t2.commit(allow_pointless=True, message='commit in second')
        b1.tags.set_tag('tag4', 'second-revid')
        self.run_bzr('merge', '-d', 'branch2', 'branch1')
        self.assertEquals(b2.tags.lookup_tag('tag4'), 'second-revid')
        # pushing to a new location copies the tag across
        self.run_bzr('push', '-d', 'branch1', 'branch3')
        b3 = Branch.open('branch3')
        self.assertEquals(b3.tags.lookup_tag('tag1'), 'first-revid')

    def test_list_tags(self):
        t = self.make_branch_and_tree('branch1')
        b1 = t.branch
        tagname = u'\u30d0zaar'
        b1.tags.set_tag(tagname, 'revid-1')
        out, err = self.run_bzr('tags', '-d', 'branch1', encoding='utf-8')
        self.assertEquals(err, '')
        self.assertContainsRe(out,
            u'^\u30d0zaar  *revid-1\n'.encode('utf-8'))

    def test_conflicting_tags(self):
        # setup two empty branches with different tags
        t1 = self.make_branch_and_tree('one')
        t2 = self.make_branch_and_tree('two')
        b1 = t1.branch
        b2 = t2.branch
        tagname = u'\u30d0zaar'
        b1.tags.set_tag(tagname, 'revid1')
        b2.tags.set_tag(tagname, 'revid2')
        # push should give a warning about the tags
        out, err = self.run_bzr('push', '-d', 'one', 'two', encoding='utf-8')
        self.assertContainsRe(out,
                'Conflicting tags:\n.*' + tagname.encode('utf-8'))
        # pull should give a warning about the tags
        out, err = self.run_bzr('pull', '-d', 'one', 'two', encoding='utf-8')
        self.assertContainsRe(out,
                'Conflicting tags:\n.*' + tagname.encode('utf-8'))
        # merge should give a warning about the tags -- not implemented yet
        ## out, err = self.run_bzr('merge', '-d', 'one', 'two', encoding='utf-8')
        ## self.assertContainsRe(out,
        ##         'Conflicting tags:\n.*' + tagname.encode('utf-8'))
