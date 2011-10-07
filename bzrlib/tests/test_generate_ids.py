# Copyright (C) 2006, 2007, 2009, 2011 Canonical Ltd
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

"""Tests for bzrlib/generate_ids.py"""

from bzrlib import (
    generate_ids,
    tests,
    )


class TestFileIds(tests.TestCase):
    """Test functions which generate file ids"""

    def assertGenFileId(self, regex, filename):
        """gen_file_id should create a file id matching the regex.

        The file id should be ascii, and should be an 8-bit string
        """
        file_id = generate_ids.gen_file_id(filename)
        self.assertContainsRe(file_id, '^'+regex+'$')
        # It should be a utf8 file_id, not a unicode one
        self.assertIsInstance(file_id, str)
        # gen_file_id should always return ascii file ids.
        file_id.decode('ascii')

    def test_gen_file_id(self):
        gen_file_id = generate_ids.gen_file_id

        # We try to use the filename if possible
        self.assertStartsWith(gen_file_id('bar'), 'bar-')

        # but we squash capitalization, and remove non word characters
        self.assertStartsWith(gen_file_id('Mwoo oof\t m'), 'mwoooofm-')

        # We also remove leading '.' characters to prevent hidden file-ids
        self.assertStartsWith(gen_file_id('..gam.py'), 'gam.py-')
        self.assertStartsWith(gen_file_id('..Mwoo oof\t m'), 'mwoooofm-')

        # we remove unicode characters, and still don't end up with a
        # hidden file id
        self.assertStartsWith(gen_file_id(u'\xe5\xb5.txt'), 'txt-')

        # Our current method of generating unique ids adds 33 characters
        # plus an serial number (log10(N) characters)
        # to the end of the filename. We now restrict the filename portion to
        # be <= 20 characters, so the maximum length should now be approx < 60

        # Test both case squashing and length restriction
        fid = gen_file_id('A'*50 + '.txt')
        self.assertStartsWith(fid, 'a'*20 + '-')
        self.assertTrue(len(fid) < 60)

        # restricting length happens after the other actions, so
        # we preserve as much as possible
        fid = gen_file_id('\xe5\xb5..aBcd\tefGhijKLMnop\tqrstuvwxyz')
        self.assertStartsWith(fid, 'abcdefghijklmnopqrst-')
        self.assertTrue(len(fid) < 60)

    def test_file_ids_are_ascii(self):
        tail = r'-\d{14}-[a-z0-9]{16}-\d+'
        self.assertGenFileId('foo' + tail, 'foo')
        self.assertGenFileId('foo' + tail, u'foo')
        self.assertGenFileId('bar' + tail, u'bar')
        self.assertGenFileId('br' + tail, u'b\xe5r')

    def test__next_id_suffix_sets_suffix(self):
        generate_ids._gen_file_id_suffix = None
        generate_ids._next_id_suffix()
        self.assertNotEqual(None, generate_ids._gen_file_id_suffix)

    def test__next_id_suffix_increments(self):
        generate_ids._gen_file_id_suffix = "foo-"
        generate_ids._gen_file_id_serial = 1
        try:
            self.assertEqual("foo-2", generate_ids._next_id_suffix())
            self.assertEqual("foo-3", generate_ids._next_id_suffix())
            self.assertEqual("foo-4", generate_ids._next_id_suffix())
            self.assertEqual("foo-5", generate_ids._next_id_suffix())
            self.assertEqual("foo-6", generate_ids._next_id_suffix())
            self.assertEqual("foo-7", generate_ids._next_id_suffix())
            self.assertEqual("foo-8", generate_ids._next_id_suffix())
            self.assertEqual("foo-9", generate_ids._next_id_suffix())
            self.assertEqual("foo-10", generate_ids._next_id_suffix())
        finally:
            # Reset so that all future ids generated in the test suite
            # don't end in 'foo-XXX'
            generate_ids._gen_file_id_suffix = None
            generate_ids._gen_file_id_serial = 0

    def test_gen_root_id(self):
        # Mostly just make sure gen_root_id() exists
        root_id = generate_ids.gen_root_id()
        self.assertStartsWith(root_id, 'tree_root-')


class TestGenRevisionId(tests.TestCase):
    """Test generating revision ids"""

    def assertGenRevisionId(self, regex, username, timestamp=None):
        """gen_revision_id should create a revision id matching the regex"""
        revision_id = generate_ids.gen_revision_id(username, timestamp)
        self.assertContainsRe(revision_id, '^'+regex+'$')
        # It should be a utf8 revision_id, not a unicode one
        self.assertIsInstance(revision_id, str)
        # gen_revision_id should always return ascii revision ids.
        revision_id.decode('ascii')

    def test_timestamp(self):
        """passing a timestamp should cause it to be used"""
        self.assertGenRevisionId(r'user@host-\d{14}-[a-z0-9]{16}', 'user@host')
        self.assertGenRevisionId('user@host-20061102205056-[a-z0-9]{16}',
                                 'user@host', 1162500656.688)
        self.assertGenRevisionId(r'user@host-20061102205024-[a-z0-9]{16}',
                                 'user@host', 1162500624.000)

    def test_gen_revision_id_email(self):
        """gen_revision_id uses email address if present"""
        regex = r'user\+joe_bar@foo-bar\.com-\d{14}-[a-z0-9]{16}'
        self.assertGenRevisionId(regex,'user+joe_bar@foo-bar.com')
        self.assertGenRevisionId(regex, '<user+joe_bar@foo-bar.com>')
        self.assertGenRevisionId(regex, 'Joe Bar <user+joe_bar@foo-bar.com>')
        self.assertGenRevisionId(regex, 'Joe Bar <user+Joe_Bar@Foo-Bar.com>')
        self.assertGenRevisionId(regex, u'Joe B\xe5r <user+Joe_Bar@Foo-Bar.com>')

    def test_gen_revision_id_user(self):
        """If there is no email, fall back to the whole username"""
        tail = r'-\d{14}-[a-z0-9]{16}'
        self.assertGenRevisionId('joe_bar' + tail, 'Joe Bar')
        self.assertGenRevisionId('joebar' + tail, 'joebar')
        self.assertGenRevisionId('joe_br' + tail, u'Joe B\xe5r')
        self.assertGenRevisionId(r'joe_br_user\+joe_bar_foo-bar.com' + tail,
                                 u'Joe B\xe5r <user+Joe_Bar_Foo-Bar.com>')

    def test_revision_ids_are_ascii(self):
        """gen_revision_id should always return an ascii revision id."""
        tail = r'-\d{14}-[a-z0-9]{16}'
        self.assertGenRevisionId('joe_bar' + tail, 'Joe Bar')
        self.assertGenRevisionId('joe_bar' + tail, u'Joe Bar')
        self.assertGenRevisionId('joe@foo' + tail, u'Joe Bar <joe@foo>')
        # We cheat a little with this one, because email-addresses shouldn't
        # contain non-ascii characters, but generate_ids should strip them
        # anyway.
        self.assertGenRevisionId('joe@f' + tail, u'Joe Bar <joe@f\xb6>')
