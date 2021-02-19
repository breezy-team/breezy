# Copyright (C) 2006, 2007, 2009, 2010, 2011 Canonical Ltd
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
    conflicts,
    tests,
    workingtree,
    )
from breezy.tests import script, features


def make_tree_with_conflicts(test, this_path='this', other_path='other',
                             prefix='my'):
    this_tree = test.make_branch_and_tree(this_path)
    test.build_tree_contents([
        ('%s/%sfile' % (this_path, prefix), b'this content\n'),
        ('%s/%s_other_file' % (this_path, prefix), b'this content\n'),
        ('%s/%sdir/' % (this_path, prefix),),
        ])
    this_tree.add(prefix + 'file')
    this_tree.add(prefix + '_other_file')
    this_tree.add(prefix + 'dir')
    this_tree.commit(message="new")
    other_tree = this_tree.controldir.sprout(other_path).open_workingtree()
    test.build_tree_contents([
        ('%s/%sfile' % (other_path, prefix), b'contentsb\n'),
        ('%s/%s_other_file' % (other_path, prefix), b'contentsb\n'),
        ])
    other_tree.rename_one(prefix + 'dir', prefix + 'dir2')
    other_tree.commit(message="change")
    test.build_tree_contents([
        ('%s/%sfile' % (this_path, prefix), b'contentsa2\n'),
        ('%s/%s_other_file' % (this_path, prefix), b'contentsa2\n'),
        ])
    this_tree.rename_one(prefix + 'dir', prefix + 'dir3')
    this_tree.commit(message='change')
    this_tree.merge_from_branch(other_tree.branch)
    return this_tree, other_tree


class TestConflicts(script.TestCaseWithTransportAndScript):

    def setUp(self):
        super(TestConflicts, self).setUp()
        make_tree_with_conflicts(self, 'branch', 'other')

    def test_conflicts(self):
        self.run_script("""\
$ cd branch
$ brz conflicts
Text conflict in my_other_file
Path conflict: mydir3 / mydir2
Text conflict in myfile
""")

    def test_conflicts_text(self):
        self.run_script("""\
$ cd branch
$ brz conflicts --text
my_other_file
myfile
""")

    def test_conflicts_directory(self):
        self.run_script("""\
$ brz conflicts  -d branch
Text conflict in my_other_file
Path conflict: mydir3 / mydir2
Text conflict in myfile
""")


class TestUnicodePaths(tests.TestCaseWithTransport):
    """Unicode characters in conflicts should be displayed properly"""

    _test_needs_features = [features.UnicodeFilenameFeature]
    encoding = "UTF-8"

    def _as_output(self, text):
        return text

    def test_messages(self):
        """Conflict messages involving non-ascii paths are displayed okay"""
        make_tree_with_conflicts(self, "branch", prefix=u"\xA7")
        out, err = self.run_bzr(["conflicts", "-d", "branch"],
                                encoding=self.encoding)
        self.assertEqual(out,
                         u"Text conflict in \xA7_other_file\n"
                         u"Path conflict: \xA7dir3 / \xA7dir2\n"
                         u"Text conflict in \xA7file\n")
        self.assertEqual(err, "")

    def test_text_conflict_paths(self):
        """Text conflicts on non-ascii paths are displayed okay"""
        make_tree_with_conflicts(self, "branch", prefix=u"\xA7")
        out, err = self.run_bzr(["conflicts", "-d", "branch", "--text"],
                                encoding=self.encoding)
        self.assertEqual(out,
                         u"\xA7_other_file\n"
                         u"\xA7file\n")
        self.assertEqual(err, "")


class TestUnicodePathsOnAsciiTerminal(TestUnicodePaths):
    """Undisplayable unicode characters in conflicts should be escaped"""

    encoding = "ascii"

    def setUp(self):
        self.skipTest("Need to decide if replacing is the desired behaviour")

    def _as_output(self, text):
        return text.encode(self.encoding, "replace")
