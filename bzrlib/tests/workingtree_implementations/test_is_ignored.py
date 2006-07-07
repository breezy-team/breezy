# (C) 2006 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from bzrlib import config, osutils

from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree


class TestIsIgnored(TestCaseWithWorkingTree):

    def test_is_ignored(self):
        tree = self.make_branch_and_tree('.')
        # this will break if a tree changes the ignored format. That is fine
        # because at the moment tree format is orthogonal to user data, and
        # .bzrignore is user data so must not be changed by a tree format.
        self.build_tree_contents([
            ('.bzrignore', './rootdir\n'
                           'randomfile*\n'
                           'path/from/ro?t\n'
                           'unicode\xc2\xb5\n' # u'\xb5'.encode('utf8')
                           'dos\r\n'
                           '\n' # empty line
                           '#comment\n'
                           ' xx \n' # whitespace
            )])
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

        self.assertEqual(u'unicode\xb5', tree.is_ignored(u'unicode\xb5'))
        self.assertEqual(u'unicode\xb5', tree.is_ignored(u'subdir/unicode\xb5'))
        self.assertEqual(None, tree.is_ignored(u'unicode\xe5'))
        self.assertEqual(None, tree.is_ignored(u'unicode'))
        self.assertEqual(None, tree.is_ignored(u'\xb5'))

        self.assertEqual('dos', tree.is_ignored('dos'))
        self.assertEqual(None, tree.is_ignored('dosfoo'))

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

        config.ensure_config_dir_exists()
        user_ignore_file = config.user_ignore_config_filename()
        f = open(user_ignore_file, 'wb')
        try:
            f.write('*.py[co]\n'
                    './.shelf\n'
                    '# comment line\n'
                    '\n' #Blank line
                    '\r\n' #Blank dos line
                    ' * \n' #Trailing and suffix spaces
                    'crlf\r\n' # dos style line
                    '*\xc3\xa5*\n' # u'\xe5'.encode('utf8')
                    )
        finally:
            f.close()

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
