# Copyright (C) 2006, 2007, 2009, 2010 Canonical Ltd
# Authors:  Robert Collins <robert.collins@canonical.com>
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

from breezy import (
    bedding,
    ignores,
    tests,
    )
from breezy.tests.per_workingtree import TestCaseWithWorkingTree


class TestIsIgnored(TestCaseWithWorkingTree):

    def setUp(self):
        super(TestIsIgnored, self).setUp()
        if self.workingtree_format.ignore_filename != '.bzrignore':
            raise tests.TestNotApplicable(
                'format does not use .bzrignore for ignore patterns')

    def _set_user_ignore_content(self, ignores):
        """Create user ignore file and set its content to ignores."""
        bedding.ensure_config_dir_exists()
        user_ignore_file = bedding.user_ignore_config_path()
        with open(user_ignore_file, 'wb') as f:
            f.write(ignores)

    def test_is_ignored(self):
        tree = self.make_branch_and_tree('.')
        # this will break if a tree changes the ignored format. That is fine
        # because at the moment tree format is orthogonal to user data, and
        # .bzrignore is user data so must not be changed by a tree format.
        self.build_tree_contents([
            ('.bzrignore', b'./rootdir\n'
                           b'randomfile*\n'
                           b'*bar\n'
                           b'!bazbar\n'
                           b'?foo\n'
                           b'*.~*\n'
                           b'dir1/*f1\n'
                           b'dir1/?f2\n'
                           b'RE:dir2/.*\\.wombat\n'
                           b'path/from/ro?t\n'
                           b'**/piffle.py\n'
                           b'!b/piffle.py\n'
                           b'unicode\xc2\xb5\n'  # u'\xb5'.encode('utf8')
                           b'dos\r\n'
                           b'\n'  # empty line
                           b'#comment\n'
                           b' xx \n'  # whitespace
             )])
        # We set user ignore file to contain '' to avoid patterns from
        # user ignore being used instead of bzrignore. For .e.g. If we
        # don't do this 'foo.~1~' will match '*~' default user ignore
        # pattern instead of '*.~*' from bzr ignore as we expect below.
        self._set_user_ignore_content(b'')
        # is_ignored returns the matching ignore regex when a path is ignored.
        # we check some expected matches for each rule, and one or more
        # relevant not-matches that look plausible as cases for bugs.
        self.assertEqual('./rootdir', tree.is_ignored('rootdir'))
        self.assertEqual(None, tree.is_ignored('foo/rootdir'))
        self.assertEqual(None, tree.is_ignored('rootdirtrailer'))

        self.assertEqual('randomfile*', tree.is_ignored('randomfile'))
        self.assertEqual('randomfile*', tree.is_ignored('randomfiles'))
        self.assertEqual('randomfile*', tree.is_ignored('foo/randomfiles'))
        self.assertEqual(None, tree.is_ignored('randomfil'))
        self.assertEqual(None, tree.is_ignored('foo/randomfil'))

        self.assertEqual("path/from/ro?t", tree.is_ignored('path/from/root'))
        self.assertEqual("path/from/ro?t", tree.is_ignored('path/from/roat'))
        self.assertEqual(None, tree.is_ignored('roat'))

        self.assertEqual('**/piffle.py', tree.is_ignored('piffle.py'))
        self.assertEqual('**/piffle.py', tree.is_ignored('a/piffle.py'))
        self.assertEqual(None, tree.is_ignored('b/piffle.py'))  # exclusion
        self.assertEqual('**/piffle.py', tree.is_ignored('foo/bar/piffle.py'))
        self.assertEqual(None, tree.is_ignored('p/iffle.py'))

        self.assertEqual(u'unicode\xb5', tree.is_ignored(u'unicode\xb5'))
        self.assertEqual(
            u'unicode\xb5', tree.is_ignored(u'subdir/unicode\xb5'))
        self.assertEqual(None, tree.is_ignored(u'unicode\xe5'))
        self.assertEqual(None, tree.is_ignored(u'unicode'))
        self.assertEqual(None, tree.is_ignored(u'\xb5'))

        self.assertEqual('dos', tree.is_ignored('dos'))
        self.assertEqual(None, tree.is_ignored('dosfoo'))

        self.assertEqual('*bar', tree.is_ignored('foobar'))
        self.assertEqual('*bar', tree.is_ignored(r'foo\nbar'))
        self.assertEqual('*bar', tree.is_ignored('bar'))
        self.assertEqual('*bar', tree.is_ignored('.bar'))

        self.assertEqual(None, tree.is_ignored('bazbar'))  # exclusion

        self.assertEqual('?foo', tree.is_ignored('afoo'))
        self.assertEqual('?foo', tree.is_ignored('.foo'))

        self.assertEqual('*.~*', tree.is_ignored('blah.py.~1~'))

        self.assertEqual('dir1/*f1', tree.is_ignored('dir1/foof1'))
        self.assertEqual('dir1/*f1', tree.is_ignored('dir1/f1'))
        self.assertEqual('dir1/*f1', tree.is_ignored('dir1/.f1'))

        self.assertEqual('dir1/?f2', tree.is_ignored('dir1/ff2'))
        self.assertEqual('dir1/?f2', tree.is_ignored('dir1/.f2'))

        self.assertEqual('RE:dir2/.*\\.wombat',
                         tree.is_ignored('dir2/foo.wombat'))
        self.assertEqual(None, tree.is_ignored('dir2/foo'))

        # Blank lines and comments should be ignored
        self.assertEqual(None, tree.is_ignored(''))
        self.assertEqual(None, tree.is_ignored('test/'))

        self.assertEqual(None, tree.is_ignored('#comment'))

        # Whitespace should not be stripped
        self.assertEqual(' xx ', tree.is_ignored(' xx '))
        self.assertEqual(' xx ', tree.is_ignored('subdir/ xx '))
        self.assertEqual(None, tree.is_ignored('xx'))
        self.assertEqual(None, tree.is_ignored('xx '))
        self.assertEqual(None, tree.is_ignored(' xx'))
        self.assertEqual(None, tree.is_ignored('subdir/xx '))

    def test_global_ignored(self):
        tree = self.make_branch_and_tree('.')

        bedding.ensure_config_dir_exists()
        user_ignore_file = bedding.user_ignore_config_path()
        self._set_user_ignore_content(
            b'*.py[co]\n'
            b'./.shelf\n'
            b'# comment line\n'
            b'\n'  # Blank line
            b'\r\n'  # Blank dos line
            b' * \n'  # Trailing and suffix spaces
            b'crlf\r\n'  # dos style line
            b'*\xc3\xa5*\n'  # u'\xe5'.encode('utf8')
            )

        # Rooted
        self.assertEqual('./.shelf', tree.is_ignored('.shelf'))
        self.assertEqual(None, tree.is_ignored('foo/.shelf'))

        # Glob style
        self.assertEqual('*.py[co]', tree.is_ignored('foo.pyc'))
        self.assertEqual('*.py[co]', tree.is_ignored('foo.pyo'))
        self.assertEqual(None, tree.is_ignored('foo.py'))

        # Glob in subdir
        self.assertEqual('*.py[co]', tree.is_ignored('bar/foo.pyc'))
        self.assertEqual('*.py[co]', tree.is_ignored('bar/foo.pyo'))
        self.assertEqual(None, tree.is_ignored('bar/foo.py'))

        # Unicode
        self.assertEqual(u'*\xe5*', tree.is_ignored(u'b\xe5gfors'))
        self.assertEqual(u'*\xe5*', tree.is_ignored(u'\xe5gfors'))
        self.assertEqual(u'*\xe5*', tree.is_ignored(u'\xe5'))
        self.assertEqual(u'*\xe5*', tree.is_ignored(u'b\xe5'))
        self.assertEqual(u'*\xe5*', tree.is_ignored(u'b/\xe5'))

        # Whitespace
        self.assertEqual(' * ', tree.is_ignored(' bbb '))
        self.assertEqual(' * ', tree.is_ignored('subdir/ bbb '))
        self.assertEqual(None, tree.is_ignored('bbb '))
        self.assertEqual(None, tree.is_ignored(' bbb'))

        # Dos lines
        self.assertEqual('crlf', tree.is_ignored('crlf'))
        self.assertEqual('crlf', tree.is_ignored('subdir/crlf'))

        # Comment line should be ignored
        self.assertEqual(None, tree.is_ignored('# comment line'))

        # Blank line should also be ignored
        self.assertEqual(None, tree.is_ignored(''))
        self.assertEqual(None, tree.is_ignored('baz/'))

    def test_mixed_is_ignored(self):
        tree = self.make_branch_and_tree('.')
        ignores._set_user_ignores(['*.py[co]', './.shelf'])
        self.build_tree_contents([('.bzrignore', b'./rootdir\n*.swp\n')])

        self.assertEqual('*.py[co]', tree.is_ignored('foo.pyc'))
        self.assertEqual('./.shelf', tree.is_ignored('.shelf'))
        self.assertEqual('./rootdir', tree.is_ignored('rootdir'))
        self.assertEqual('*.swp', tree.is_ignored('foo.py.swp'))
        self.assertEqual('*.swp', tree.is_ignored('.foo.py.swp'))
        self.assertEqual(None, tree.is_ignored('.foo.py.swo'))

    def test_runtime_ignores(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree_contents([('.bzrignore', b'')])
        ignores._set_user_ignores([])

        orig_runtime = ignores._runtime_ignores
        try:
            ignores._runtime_ignores = set()
            self.assertEqual(None, tree.is_ignored('foobar.py'))

            tree._flush_ignore_list_cache()
            ignores.add_runtime_ignores(['./foobar.py'])
            self.assertEqual({'./foobar.py'}, ignores.get_runtime_ignores())
            self.assertEqual('./foobar.py', tree.is_ignored('foobar.py'))
        finally:
            ignores._runtime_ignores = orig_runtime

    def test_ignore_caching(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['ignoreme'])

        self.assertEqual(None, tree.is_ignored('ignoreme'))

        # Bug #129694 specifically references WorkingTree.unknowns()
        tree.unknowns()

        self.build_tree_contents([('.bzrignore', b'ignoreme')])
        self.assertEqual('ignoreme', tree.is_ignored('ignoreme'))
