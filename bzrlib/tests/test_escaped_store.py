# Copyright (C) 2005 by Canonical Development Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Test Escaped Stores."""

from cStringIO import StringIO
import os
import gzip

from bzrlib.errors import BzrError, UnlistableStore, NoSuchFile
from bzrlib.store import copy_all
from bzrlib.store.text import TextStore
from bzrlib.tests import TestCaseWithTransport
import bzrlib.transport


class TestEscaped(TestCaseWithTransport):
    """Mixin template class that provides some common tests for stores"""

    def get_store(self, prefixed=False, escaped=True):
        t = bzrlib.transport.get_transport(self.get_url())
        return TextStore(t, prefixed=prefixed, escaped=escaped)

    def test_paths(self):
        text_store = self.get_store()

        self.assertEqual('a', text_store._relpath('a'))
        self.assertEqual('a', text_store._relpath(u'a'))
        self.assertEqual('%2520', text_store._relpath(' '))
        self.assertEqual('%40%253A%253C%253E', text_store._relpath('@:<>'))
        self.assertEqual('%25C3%25A5', text_store._relpath(u'\xe5'))

    def test_prefixed(self):
        # Prefix should be determined by unescaped string
        text_store = self.get_store(prefixed=True)

        # hash_prefix() is not defined for unicode characters
        # it is only defined for byte streams.
        # so hash_prefix() needs to operate on *at most* utf-8
        # encoded. However urlescape() does both encoding to utf-8
        # and urllib quoting, so we will use the escaped form
        # as the path passed to hash_prefix

        self.assertEqual('62/a', text_store._relpath('a'))
        self.assertEqual('88/%2520', text_store._relpath(' '))
        self.assertEqual('12/%40%253A%253C%253E',
                text_store._relpath('@:<>'))
        self.assertEqual('37/%25C3%25A5', text_store._relpath(u'\xe5'))

    def test_files(self):
        text_store = self.get_store(prefixed=True)

        text_store.add(StringIO('a'), 'a')
        self.failUnlessExists('62/a')

        text_store.add(StringIO('space'), ' ')
        self.failUnlessExists('88/%20')
        self.assertEquals('space', text_store.get(' ').read())

        text_store.add(StringIO('surprise'), '@:<>')
        self.failUnlessExists('12/@%3A%3C%3E')
        self.assertEquals('surprise', text_store.get('@:<>').read())

        text_store.add(StringIO('unicode'), u'\xe5')
        self.failUnlessExists('37/%C3%A5')
        self.assertEquals('unicode', text_store.get(u'\xe5').read())

    def test_weave(self):
        from bzrlib.store.versioned import WeaveStore
        from bzrlib.transactions import PassThroughTransaction

        trans = PassThroughTransaction()

        t = bzrlib.transport.get_transport(self.get_url())
        weave_store = WeaveStore(t, prefixed=True, escaped=True)

        weave_store.add_text('a', 'r', ['a'], [], trans)
        self.failUnlessExists('62/a.weave')
        self.assertEqual(['a'], weave_store.get_lines('a', 'r', trans))

        weave_store.add_text(' ', 'r', ['space'], [], trans)
        self.failIfExists('21/ .weave')
        self.failUnlessExists('88/%20.weave')
        self.assertEquals(['space'], weave_store.get_lines(' ', 'r', trans))

        weave_store.add_text('@:<>', 'r', ['surprise'], [], trans)
        self.failUnlessExists('12/@%3A%3C%3E.weave')
        self.assertEquals(['surprise'], weave_store.get_lines('@:<>', 'r', trans))

        weave_store.add_text(u'\xe5', 'r', ['unicode'], [], trans)
        self.failUnlessExists('37/%C3%A5.weave')
        self.assertEquals(['unicode'], weave_store.get_lines(u'\xe5', 'r', trans))

