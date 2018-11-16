# Copyright (C) 2006, 2011 Canonical Ltd
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

"""Test that lazy regexes are not compiled right away"""

import pickle
import re

from .. import errors
from .. import (
    lazy_regex,
    tests,
    )


class TestErrors(tests.TestCase):

    def test_invalid_pattern(self):
        error = lazy_regex.InvalidPattern('Bad pattern msg.')
        self.assertEqualDiff("Invalid pattern(s) found. Bad pattern msg.",
                             str(error))


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
        self._actions.append(('_real_re_compile', args, kwargs))
        return super(InstrumentedLazyRegex, self)._real_re_compile(
            *args, **kwargs)


class TestLazyRegex(tests.TestCase):

    def test_lazy_compile(self):
        """Make sure that LazyRegex objects compile at the right time"""
        actions = []
        InstrumentedLazyRegex.use_actions(actions)

        pattern = InstrumentedLazyRegex(args=('foo',), kwargs={})
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

    def test_bad_pattern(self):
        """Ensure lazy regex handles bad patterns cleanly."""
        p = lazy_regex.lazy_compile('RE:[')
        # As p.match is lazy, we make it into a lambda so its handled
        # by assertRaises correctly.
        e = self.assertRaises(lazy_regex.InvalidPattern,
                              lambda: p.match('foo'))
        # Expect either old or new form of error message
        self.assertContainsRe(e.msg, '^"RE:\\[" '
                              '(unexpected end of regular expression'
                              '|unterminated character set at position 3)$')


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

    def test_findall(self):
        pattern = lazy_regex.lazy_compile('fo*')
        self.assertEqual(['f', 'fo', 'foo', 'fooo'],
                         pattern.findall('f fo foo fooo'))

    def test_finditer(self):
        pattern = lazy_regex.lazy_compile('fo*')
        matches = [(m.start(), m.end(), m.group())
                   for m in pattern.finditer('foo bar fop')]
        self.assertEqual([(0, 3, 'foo'), (8, 10, 'fo')], matches)

    def test_match(self):
        pattern = lazy_regex.lazy_compile('fo*')
        self.assertIs(None, pattern.match('baz foo'))
        self.assertEqual('fooo', pattern.match('fooo').group())

    def test_search(self):
        pattern = lazy_regex.lazy_compile('fo*')
        self.assertEqual('foo', pattern.search('baz foo').group())
        self.assertEqual('fooo', pattern.search('fooo').group())

    def test_split(self):
        pattern = lazy_regex.lazy_compile('[,;]+')
        self.assertEqual(['x', 'y', 'z'], pattern.split('x,y;z'))

    def test_pickle(self):
        # When pickling, just compile the regex.
        # Sphinx, which we use for documentation, pickles
        # some compiled regexes.
        lazy_pattern = lazy_regex.lazy_compile('[,;]+')
        pickled = pickle.dumps(lazy_pattern)
        unpickled_lazy_pattern = pickle.loads(pickled)
        self.assertEqual(
            ['x', 'y', 'z'], unpickled_lazy_pattern.split('x,y;z'))
