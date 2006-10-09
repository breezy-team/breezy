# Copyright (C) 2006 by Canonical Ltd
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

"""Test that lazy regexes are not compiled right away"""

import re

from bzrlib import (
    lazy_regex,
    tests,
    )


class InstrumentedLazyRegex(lazy_regex.LazyRegex):
    """Keep track of actions on the lazy regex"""

    _actions = []

    @classmethod
    def use_actions(cls, actions):
        cls._actions = actions

    def __getattr__(self, attr):
        self._actions.append(('__getattr__', attr))
        return super(InstrumentedLazyRegex, self).__getattr__(attr)

    def _real_re_compile(self, *args, **kwargs):
        self._actions.append(('_real_re_compile',
                                               args, kwargs))
        return super(InstrumentedLazyRegex, self)._real_re_compile(*args, **kwargs)


class TestLazyRegex(tests.TestCase):

    def test_lazy_compile(self):
        """Make sure that LazyRegex objects compile at the right time"""
        actions = []
        InstrumentedLazyRegex.use_actions(actions)

        pattern = InstrumentedLazyRegex(args=('foo',))
        actions.append(('created regex', 'foo'))
        # This match call should compile the regex and go through __getattr__
        pattern.match('foo')
        # But a further call should not go through __getattr__ because it has
        # been bound locally.
        pattern.match('foo')

        self.assertEqual([('created regex', 'foo'),
                          ('__getattr__', 'match'),
                          ('_real_re_compile', ('foo',), {}),
                         ], actions)


class TestLazyCompile(tests.TestCase):

    def test_simple_acts_like_regex(self):
        """Test that the returned object has basic regex like functionality"""
        pattern = lazy_regex.lazy_compile('foo')
        self.assertIsInstance(pattern, lazy_regex.LazyRegex)
        self.assertTrue(pattern.match('foo'))
        self.assertIs(None, pattern.match('bar'))

    def test_extra_args(self):
        """Test that extra arguments are also properly passed"""
        pattern = lazy_regex.lazy_compile('foo', re.I)
        self.assertIsInstance(pattern, lazy_regex.LazyRegex)
        self.assertTrue(pattern.match('foo'))
        self.assertTrue(pattern.match('Foo'))

