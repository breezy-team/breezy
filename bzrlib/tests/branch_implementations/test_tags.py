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

"""Tags stored within a branch

The tags are actually in the Branch.tags namespace, but these are 
1:1 with Branch implementations so can be tested from here.
"""

import os
import re
import sys

import bzrlib
from bzrlib import bzrdir, errors, repository
from bzrlib.branch import Branch, needs_read_lock, needs_write_lock
from bzrlib.tests import TestCase, TestCaseWithTransport, TestSkipped
from bzrlib.trace import mutter
from bzrlib.workingtree import WorkingTree

from bzrlib.tests.branch_implementations.test_branch \
        import TestCaseWithBranch


class TestBranchTags(TestCaseWithBranch):

    def setUp(self):
        # formats that don't support tags can skip the rest of these 
        # tests...
        fmt = self.branch_format
        f = getattr(fmt, 'supports_tags')
        if f is None:
            raise TestSkipped("format %s doesn't declare whether it "
                "supports tags, assuming not" % fmt)
        if not f():
            raise TestSkipped("format %s doesn't support tags" % fmt)
        TestCaseWithBranch.setUp(self)

    def test_tags_initially_empty(self):
        b = self.make_branch('b')
        tags = b.tags.get_tag_dict()
        self.assertEqual(tags, {})

    def test_make_and_lookup_tag(self):
        b = self.make_branch('b')
        b.tags.set_tag('tag-name', 'target-revid-1')
        b.tags.set_tag('other-name', 'target-revid-2')
        # then reopen the branch and see they're still there
        b = Branch.open('b')
        self.assertEqual(b.tags.get_tag_dict(),
            {'tag-name': 'target-revid-1',
             'other-name': 'target-revid-2',
            })
        # read one at a time
        result = b.tags.lookup_tag('tag-name')
        self.assertEqual(result, 'target-revid-1')
        # and try has_tag
        self.assertTrue(b.tags.has_tag('tag-name'))
        self.assertFalse(b.tags.has_tag('imaginary'))

    def test_reverse_tag_dict(self):
        b = self.make_branch('b')
        b.tags.set_tag('tag-name', 'target-revid-1')
        b.tags.set_tag('other-name', 'target-revid-2')
        # then reopen the branch and check reverse map id->tags list
        b = Branch.open('b')
        self.assertEqual(b.tags.get_reverse_tag_dict(),
            {'target-revid-1': ['tag-name'],
             'target-revid-2': ['other-name'],
            })

    def test_no_such_tag(self):
        b = self.make_branch('b')
        try:
            b.tags.lookup_tag('bosko')
        except errors.NoSuchTag, e:
            self.assertEquals(e.tag_name, 'bosko')
            self.assertEquals(str(e), 'No such tag: bosko')
        else:
            self.fail("didn't get expected exception")

    def test_merge_tags(self):
        b1 = self.make_branch('b1')
        b2 = self.make_branch('b2')
        # if there are tags in the source and not the destination, then they
        # just go across
        b1.tags.set_tag('tagname', 'revid')
        b1.tags.merge_to(b2.tags)
        self.assertEquals(b2.tags.lookup_tag('tagname'), 'revid')
        # if a tag is in the destination and not in the source, it is not
        # removed when we merge them
        b2.tags.set_tag('in-destination', 'revid')
        result = b1.tags.merge_to(b2.tags)
        self.assertEquals(result, [])
        self.assertEquals(b2.tags.lookup_tag('in-destination'), 'revid')
        # if there's a conflicting tag, it's reported -- the command line
        # interface will say "these tags couldn't be copied"
        b1.tags.set_tag('conflicts', 'revid-1')
        b2.tags.set_tag('conflicts', 'revid-2')
        result = b1.tags.merge_to(b2.tags)
        self.assertEquals(result,
            [('conflicts', 'revid-1', 'revid-2')])
        # and it keeps the same value
        self.assertEquals(b2.tags.lookup_tag('conflicts'), 'revid-2')


    def test_unicode_tag(self):
        b1 = self.make_branch('b')
        tag_name = u'\u3070'
        # in anticipation of the planned change to treating revision ids as
        # just 8bit strings
        revid = ('revid' + tag_name).encode('utf-8')
        b1.tags.set_tag(tag_name, revid)
        self.assertEquals(b1.tags.lookup_tag(tag_name), revid)

    def test_delete_tag(self):
        b = self.make_branch('b')
        tag_name = u'\N{GREEK SMALL LETTER ALPHA}'
        revid = ('revid' + tag_name).encode('utf-8')
        b.tags.set_tag(tag_name, revid)
        # now try to delete it
        b.tags.delete_tag(tag_name)
        # now you can't look it up
        self.assertRaises(errors.NoSuchTag,
            b.tags.lookup_tag, tag_name)
        # and it's not in the dictionary
        self.assertEquals(b.tags.get_tag_dict(), {})
        # and you can't remove it a second time
        self.assertRaises(errors.NoSuchTag,
            b.tags.delete_tag, tag_name)
        # or remove a tag that never existed
        self.assertRaises(errors.NoSuchTag,
            b.tags.delete_tag, tag_name + '2')

    def test_merge_empty_tags(self):
        # you can merge tags between two instances, since neither have tags
        b1 = self.make_branch('b1')
        b2 = self.make_branch('b2')
        b1.tags.merge_to(b2.tags)


class TestUnsupportedTags(TestCaseWithBranch):
    """Formats that don't support tags should give reasonable errors."""

    def setUp(self):
        fmt = self.branch_format
        supported = getattr(fmt, 'supports_tags')
        if supported is None:
            warn("Format %s doesn't declare whether it supports tags or not"
                 % fmt)
            raise TestSkipped('No tag support at all')
        if supported():
            raise TestSkipped("Format %s declares that tags are supported"
                              % fmt)
            # it's covered by TestBranchTags
        TestCaseWithBranch.setUp(self)
    
    def test_tag_methods_raise(self):
        b = self.make_branch('b')
        self.assertRaises(errors.TagsNotSupported,
            b.tags.set_tag, 'foo', 'bar')
        self.assertRaises(errors.TagsNotSupported,
            b.tags.lookup_tag, 'foo')
        self.assertRaises(errors.TagsNotSupported,
            b.tags.set_tag, 'foo', 'bar')
        self.assertRaises(errors.TagsNotSupported,
            b.tags.delete_tag, 'foo')

    def test_merge_empty_tags(self):
        # you can merge tags between two instances, since neither have tags
        b1 = self.make_branch('b1')
        b2 = self.make_branch('b2')
        b1.tags.merge_to(b2.tags)
