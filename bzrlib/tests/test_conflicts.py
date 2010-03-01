# Copyright (C) 2005-2010 Canonical Ltd
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


import os

from bzrlib import (
    branchbuilder,
    bzrdir,
    conflicts,
    errors,
    option,
    tests,
    workingtree,
    )
from bzrlib.tests import script


# TODO: Test commit with some added, and added-but-missing files
# RBC 20060124 is that not tested in test_commit.py ?

# The order of 'path' here is important - do not let it
# be a sorted list.
# u'\xe5' == a with circle
# '\xc3\xae' == u'\xee' == i with hat
# So these are u'path' and 'id' only with a circle and a hat. (shappo?)
example_conflicts = conflicts.ConflictList(
    [conflicts.MissingParent('Not deleting', u'p\xe5thg', '\xc3\xaedg'),
     conflicts.ContentsConflict(u'p\xe5tha', None, '\xc3\xaeda'),
     conflicts.TextConflict(u'p\xe5tha'),
     conflicts.PathConflict(u'p\xe5thb', u'p\xe5thc', '\xc3\xaedb'),
     conflicts.DuplicateID('Unversioned existing file',
                           u'p\xe5thc', u'p\xe5thc2',
                           '\xc3\xaedc', '\xc3\xaedc'),
    conflicts.DuplicateEntry('Moved existing file to',
                             u'p\xe5thdd.moved', u'p\xe5thd',
                             '\xc3\xaedd', None),
    conflicts.ParentLoop('Cancelled move', u'p\xe5the', u'p\xe5th2e',
                         None, '\xc3\xaed2e'),
    conflicts.UnversionedParent('Versioned directory',
                                u'p\xe5thf', '\xc3\xaedf'),
    conflicts.NonDirectoryParent('Created directory',
                                 u'p\xe5thg', '\xc3\xaedg'),
])


class TestConflicts(tests.TestCaseWithTransport):

    def test_conflicts(self):
        """Conflicts are detected properly"""
        # Use BzrDirFormat6 so we can fake conflicts
        tree = self.make_branch_and_tree('.', format=bzrdir.BzrDirFormat6())
        self.build_tree_contents([('hello', 'hello world4'),
                                  ('hello.THIS', 'hello world2'),
                                  ('hello.BASE', 'hello world1'),
                                  ('hello.OTHER', 'hello world3'),
                                  ('hello.sploo.BASE', 'yellowworld'),
                                  ('hello.sploo.OTHER', 'yellowworld2'),
                                  ])
        tree.lock_read()
        self.assertEqual(6, len(list(tree.list_files())))
        tree.unlock()
        tree_conflicts = tree.conflicts()
        self.assertEqual(2, len(tree_conflicts))
        self.assertTrue('hello' in tree_conflicts[0].path)
        self.assertTrue('hello.sploo' in tree_conflicts[1].path)
        conflicts.restore('hello')
        conflicts.restore('hello.sploo')
        self.assertEqual(0, len(tree.conflicts()))
        self.assertFileEqual('hello world2', 'hello')
        self.assertFalse(os.path.lexists('hello.sploo'))
        self.assertRaises(errors.NotConflicted, conflicts.restore, 'hello')
        self.assertRaises(errors.NotConflicted,
                          conflicts.restore, 'hello.sploo')

    def test_resolve_conflict_dir(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree_contents([('hello', 'hello world4'),
                                  ('hello.THIS', 'hello world2'),
                                  ('hello.BASE', 'hello world1'),
                                  ])
        os.mkdir('hello.OTHER')
        tree.add('hello', 'q')
        l = conflicts.ConflictList([conflicts.TextConflict('hello')])
        l.remove_files(tree)

    def test_select_conflicts(self):
        tree = self.make_branch_and_tree('.')
        clist = conflicts.ConflictList

        def check_select(not_selected, selected, paths, **kwargs):
            self.assertEqual(
                (not_selected, selected),
                tree_conflicts.select_conflicts(tree, paths, **kwargs))

        foo = conflicts.ContentsConflict('foo')
        bar = conflicts.ContentsConflict('bar')
        tree_conflicts = clist([foo, bar])

        check_select(clist([bar]), clist([foo]), ['foo'])
        check_select(clist(), tree_conflicts,
                     [''], ignore_misses=True, recurse=True)

        foobaz  = conflicts.ContentsConflict('foo/baz')
        tree_conflicts = clist([foobaz, bar])

        check_select(clist([bar]), clist([foobaz]),
                     ['foo'], ignore_misses=True, recurse=True)

        qux = conflicts.PathConflict('qux', 'foo/baz')
        tree_conflicts = clist([qux])

        check_select(clist(), tree_conflicts,
                     ['foo'], ignore_misses=True, recurse=True)
        check_select (tree_conflicts, clist(), ['foo'], ignore_misses=True)

    def test_resolve_conflicts_recursive(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['dir/', 'dir/hello'])
        tree.add(['dir', 'dir/hello'])

        dirhello = conflicts.ConflictList([conflicts.TextConflict('dir/hello')])
        tree.set_conflicts(dirhello)

        conflicts.resolve(tree, ['dir'], recursive=False, ignore_misses=True)
        self.assertEqual(dirhello, tree.conflicts())

        conflicts.resolve(tree, ['dir'], recursive=True, ignore_misses=True)
        self.assertEqual(conflicts.ConflictList([]), tree.conflicts())


class TestConflictStanzas(tests.TestCase):

    def test_stanza_roundtrip(self):
        # write and read our example stanza.
        stanza_iter = example_conflicts.to_stanzas()
        processed = conflicts.ConflictList.from_stanzas(stanza_iter)
        for o, p in zip(processed, example_conflicts):
            self.assertEqual(o, p)

            self.assertIsInstance(o.path, unicode)

            if o.file_id is not None:
                self.assertIsInstance(o.file_id, str)

            conflict_path = getattr(o, 'conflict_path', None)
            if conflict_path is not None:
                self.assertIsInstance(conflict_path, unicode)

            conflict_file_id = getattr(o, 'conflict_file_id', None)
            if conflict_file_id is not None:
                self.assertIsInstance(conflict_file_id, str)

    def test_stanzification(self):
        for stanza in example_conflicts.to_stanzas():
            if 'file_id' in stanza:
                # In Stanza form, the file_id has to be unicode.
                self.assertStartsWith(stanza['file_id'], u'\xeed')
            self.assertStartsWith(stanza['path'], u'p\xe5th')
            if 'conflict_path' in stanza:
                self.assertStartsWith(stanza['conflict_path'], u'p\xe5th')
            if 'conflict_file_id' in stanza:
                self.assertStartsWith(stanza['conflict_file_id'], u'\xeed')


# FIXME: The shell-like tests should be converted to real whitebox tests... or
# moved to a blackbox module -- vila 20100205

# FIXME: Tests missing for DuplicateID conflict type
class TestResolveConflicts(script.TestCaseWithTransportAndScript):

    preamble = None # The setup script set by daughter classes

    def setUp(self):
        super(TestResolveConflicts, self).setUp()
        self.run_script(self.preamble)


class TestResolveTextConflicts(TestResolveConflicts):
    # TBC
    pass


class TestResolveContentConflicts(tests.TestCaseWithTransport):

    # FIXME: We need to add the reverse case (delete in trunk, modify in
    # branch) but that could wait until the resolution mechanism is implemented.

    def setUp(self):
        super(TestResolveContentConflicts, self).setUp()
        builder = self.make_branch_builder('trunk')
        builder.start_series()
        # Create an empty trunk
        builder.build_snapshot('start', None, [
                ('add', ('', 'root-id', 'directory', ''))])
        # Add a minimal base content
        builder.build_snapshot('base', ['start'], [
                ('add', ('file', 'file-id', 'file', 'trunk content\n'))])
        # Modify the base content in branch
        builder.build_snapshot('other', ['base'], [
                ('unversion', 'file-id')])
        # Modify the base content in trunk
        builder.build_snapshot('this', ['base'], [
                ('modify', ('file-id', 'trunk content\nmore content\n'))])
        builder.finish_series()
        self.builder = builder

    def _merge_other_into_this(self):
        b = self.builder.get_branch()
        wt = b.bzrdir.sprout('branch').open_workingtree()
        wt.merge_from_branch(b, 'other')
        return wt

    def assertConflict(self, wt, ctype, **kwargs):
        confs = wt.conflicts()
        self.assertEqual(1, len(confs))
        c = confs[0]
        self.assertIsInstance(c, ctype)
        sentinel = object() # An impossible value
        for k, v in kwargs.iteritems():
            self.assertEqual(v, getattr(c, k, sentinel))

    def assertResolved(self, wt, item, action):
        conflicts.resolve(wt, [item], action=action)
        # Check that we don't have any conflicts nor unknown left
        self.assertEqual(0, len(wt.conflicts()))
        self.assertEqual(0, len(list(wt.unknowns())))

    def test_resolve_taking_this(self):
        wt = self._merge_other_into_this()
        self.assertConflict(wt, conflicts.ContentsConflict,
                            path='file', file_id='file-id',)
        self.assertResolved(wt, 'file', 'take_this')
        self.assertFileEqual('trunk content\nmore content\n', 'branch/file')

    def test_resolve_taking_other(self):
        wt = self._merge_other_into_this()
        self.assertConflict(wt, conflicts.ContentsConflict,
                            path='file', file_id='file-id',)
        self.assertResolved(wt, 'file', 'take_other')
        self.failIfExists('branch/file')


class TestResolveDuplicateEntry(TestResolveConflicts):

    preamble = """
$ bzr init trunk
$ cd trunk
$ echo 'trunk content' >file
$ bzr add file
$ bzr commit -m 'Create trunk'

$ echo 'trunk content too' >file2
$ bzr add file2
$ bzr commit -m 'Add file2 in trunk'

$ bzr branch . -r 1 ../branch
$ cd ../branch
$ echo 'branch content' >file2
$ bzr add file2
$ bzr commit -m 'Add file2 in branch'

$ bzr merge ../trunk
2>+N  file2
2>R   file2 => file2.moved
2>Conflict adding file file2.  Moved existing file to file2.moved.
2>1 conflicts encountered.
"""

    def test_keep_this(self):
        self.run_script("""
$ bzr rm file2  --force
$ bzr mv file2.moved file2
$ bzr resolve file2
$ bzr commit --strict -m 'No more conflicts nor unknown files'
""")

    def test_keep_other(self):
        self.failIfExists('branch/file2.moved')
        self.run_script("""
$ bzr rm file2.moved --force
$ bzr resolve file2
$ bzr commit --strict -m 'No more conflicts nor unknown files'
""")
        self.failIfExists('branch/file2.moved')

    def test_resolve_taking_this(self):
        self.run_script("""
$ bzr resolve --take-this file2
$ bzr commit --strict -m 'No more conflicts nor unknown files'
""")

    def test_resolve_taking_other(self):
        self.run_script("""
$ bzr resolve --take-other file2
$ bzr commit --strict -m 'No more conflicts nor unknown files'
""")


class TestResolveUnversionedParent(TestResolveConflicts):

    # FIXME: Add the reverse tests: dir deleted in trunk, file added in branch

    # FIXME: While this *creates* UnversionedParent conflicts, this really only
    # tests MissingParent resolution :-/
    preamble = """
$ bzr init trunk
$ cd trunk
$ mkdir dir
$ bzr add dir
$ bzr commit -m 'Create trunk'

$ echo 'trunk content' >dir/file
$ bzr add dir/file
$ bzr commit -m 'Add dir/file in trunk'

$ bzr branch . -r 1 ../branch
$ cd ../branch
$ bzr rm dir
$ bzr commit -m 'Remove dir in branch'

$ bzr merge ../trunk
2>+N  dir/
2>+N  dir/file
2>Conflict adding files to dir.  Created directory.
2>Conflict because dir is not versioned, but has versioned children.  Versioned directory.
2>2 conflicts encountered.
"""

    def test_take_this(self):
        self.run_script("""
$ bzr rm dir  --force
$ bzr resolve dir
$ bzr commit --strict -m 'No more conflicts nor unknown files'
""")

    def test_take_other(self):
        self.run_script("""
$ bzr resolve dir
$ bzr commit --strict -m 'No more conflicts nor unknown files'
""")


class TestResolveMissingParent(TestResolveConflicts):

    preamble = """
$ bzr init trunk
$ cd trunk
$ mkdir dir
$ echo 'trunk content' >dir/file
$ bzr add
$ bzr commit -m 'Create trunk'

$ echo 'trunk content' >dir/file2
$ bzr add dir/file2
$ bzr commit -m 'Add dir/file2 in branch'

$ bzr branch . -r 1 ../branch
$ cd ../branch
$ bzr rm dir/file --force
$ bzr rm dir
$ bzr commit -m 'Remove dir/file'

$ bzr merge ../trunk
2>+N  dir/
2>+N  dir/file2
2>Conflict adding files to dir.  Created directory.
2>Conflict because dir is not versioned, but has versioned children.  Versioned directory.
2>2 conflicts encountered.
"""

    def test_keep_them_all(self):
        self.run_script("""
$ bzr resolve dir
$ bzr commit --strict -m 'No more conflicts nor unknown files'
""")

    def test_adopt_child(self):
        self.run_script("""
$ bzr mv dir/file2 file2
$ bzr rm dir --force
$ bzr resolve dir
$ bzr commit --strict -m 'No more conflicts nor unknown files'
""")

    def test_kill_them_all(self):
        self.run_script("""
$ bzr rm dir --force
$ bzr resolve dir
$ bzr commit --strict -m 'No more conflicts nor unknown files'
""")

    def test_resolve_taking_this(self):
        self.run_script("""
$ bzr resolve --take-this dir
$ bzr commit --strict -m 'No more conflicts nor unknown files'
""")

    def test_resolve_taking_other(self):
        self.run_script("""
$ bzr resolve --take-other dir
$ bzr commit --strict -m 'No more conflicts nor unknown files'
""")


class TestResolveDeletingParent(TestResolveConflicts):

    preamble = """
$ bzr init trunk
$ cd trunk
$ mkdir dir
$ echo 'trunk content' >dir/file
$ bzr add
$ bzr commit -m 'Create trunk'

$ bzr rm dir/file --force
$ bzr rm dir --force
$ bzr commit -m 'Remove dir/file'

$ bzr branch . -r 1 ../branch
$ cd ../branch
$ echo 'branch content' >dir/file2
$ bzr add dir/file2
$ bzr commit -m 'Add dir/file2 in branch'

$ bzr merge ../trunk
2>-D  dir/file
2>Conflict: can't delete dir because it is not empty.  Not deleting.
2>Conflict because dir is not versioned, but has versioned children.  Versioned directory.
2>2 conflicts encountered.
"""

    def test_keep_them_all(self):
        self.run_script("""
$ bzr resolve dir
$ bzr commit --strict -m 'No more conflicts nor unknown files'
""")

    def test_adopt_child(self):
        self.run_script("""
$ bzr mv dir/file2 file2
$ bzr rm dir --force
$ bzr resolve dir
$ bzr commit --strict -m 'No more conflicts nor unknown files'
""")

    def test_kill_them_all(self):
        self.run_script("""
$ bzr rm dir --force
$ bzr resolve dir
$ bzr commit --strict -m 'No more conflicts nor unknown files'
""")

    def test_resolve_taking_this(self):
        self.run_script("""
$ bzr resolve --take-this dir
$ bzr commit --strict -m 'No more conflicts nor unknown files'
""")

    def test_resolve_taking_other(self):
        self.run_script("""
$ bzr resolve --take-other dir
$ bzr commit --strict -m 'No more conflicts nor unknown files'
""")


class TestResolvePathConflict(TestResolveConflicts):

    preamble = """
$ bzr init trunk
$ cd trunk
$ echo 'Boo!' >file
$ bzr add
$ bzr commit -m 'Create trunk'

$ bzr mv file file-in-trunk
$ bzr commit -m 'Renamed to file-in-trunk'

$ bzr branch . -r 1 ../branch
$ cd ../branch
$ bzr mv file file-in-branch
$ bzr commit -m 'Renamed to file-in-branch'

$ bzr merge ../trunk
2>R   file-in-branch => file-in-trunk
2>Path conflict: file-in-branch / file-in-trunk
2>1 conflicts encountered.
"""

    def test_keep_source(self):
        self.run_script("""
$ bzr resolve file-in-trunk
$ bzr commit --strict -m 'No more conflicts nor unknown files'
""")

    def test_keep_target(self):
        self.run_script("""
$ bzr mv file-in-trunk file-in-branch
$ bzr resolve file-in-branch
$ bzr commit --strict -m 'No more conflicts nor unknown files'
""")

    def test_resolve_taking_this(self):
        self.run_script("""
$ bzr resolve --take-this file-in-branch
$ bzr commit --strict -m 'No more conflicts nor unknown files'
""")

    def test_resolve_taking_other(self):
        self.run_script("""
$ bzr resolve --take-other file-in-branch
$ bzr commit --strict -m 'No more conflicts nor unknown files'
""")


class TestResolveParentLoop(TestResolveConflicts):

    preamble = """
$ bzr init trunk
$ cd trunk
$ bzr mkdir dir1
$ bzr mkdir dir2
$ bzr commit -m 'Create trunk'

$ bzr mv dir2 dir1
$ bzr commit -m 'Moved dir2 into dir1'

$ bzr branch . -r 1 ../branch
$ cd ../branch
$ bzr mv dir1 dir2
$ bzr commit -m 'Moved dir1 into dir2'

$ bzr merge ../trunk
2>Conflict moving dir2/dir1 into dir2.  Cancelled move.
2>1 conflicts encountered.
"""

    def test_take_this(self):
        self.run_script("""
$ bzr resolve dir2
$ bzr commit --strict -m 'No more conflicts nor unknown files'
""")

    def test_take_other(self):
        self.run_script("""
$ bzr mv dir2/dir1 dir1
$ bzr mv dir2 dir1
$ bzr resolve dir2
$ bzr commit --strict -m 'No more conflicts nor unknown files'
""")

    def test_resolve_taking_this(self):
        self.run_script("""
$ bzr resolve --take-this dir2
$ bzr commit --strict -m 'No more conflicts nor unknown files'
""")
        self.failUnlessExists('dir2')

    def test_resolve_taking_other(self):
        self.run_script("""
$ bzr resolve --take-other dir2
$ bzr commit --strict -m 'No more conflicts nor unknown files'
""")
        self.failUnlessExists('dir1')


class TestResolveNonDirectoryParent(TestResolveConflicts):

    preamble = """
$ bzr init trunk
$ cd trunk
$ bzr mkdir foo
$ bzr commit -m 'Create trunk'
$ echo "Boing" >foo/bar
$ bzr add foo/bar
$ bzr commit -m 'Add foo/bar'

$ bzr branch . -r 1 ../branch
$ cd ../branch
$ rm -r foo
$ echo "Boo!" >foo
$ bzr commit -m 'foo is now a file'

$ bzr merge ../trunk
2>+N  foo.new/bar
2>RK  foo => foo.new/
# FIXME: The message is misleading, foo.new *is* a directory when the message
# is displayed -- vila 090916
2>Conflict: foo.new is not a directory, but has files in it.  Created directory.
2>1 conflicts encountered.
"""

    def test_take_this(self):
        self.run_script("""
$ bzr rm foo.new --force
# FIXME: Isn't it weird that foo is now unkown even if foo.new has been put
# aside ? -- vila 090916
$ bzr add foo
$ bzr resolve foo.new
$ bzr commit --strict -m 'No more conflicts nor unknown files'
""")

    def test_take_other(self):
        self.run_script("""
$ bzr rm foo --force
$ bzr mv foo.new foo
$ bzr resolve foo
$ bzr commit --strict -m 'No more conflicts nor unknown files'
""")

    def test_resolve_taking_this(self):
        self.run_script("""
$ bzr resolve --take-this foo.new
$ bzr commit --strict -m 'No more conflicts nor unknown files'
""")

    def test_resolve_taking_other(self):
        self.run_script("""
$ bzr resolve --take-other foo.new
$ bzr commit --strict -m 'No more conflicts nor unknown files'
""")


class TestMalformedTransform(script.TestCaseWithTransportAndScript):

    def test_bug_430129(self):
        # This is nearly like TestResolveNonDirectoryParent but with branch and
        # trunk switched. As such it should certainly produce the same
        # conflict.
        self.run_script("""
$ bzr init trunk
$ cd trunk
$ bzr mkdir foo
$ bzr commit -m 'Create trunk'
$ rm -r foo
$ echo "Boo!" >foo
$ bzr commit -m 'foo is now a file'

$ bzr branch . -r 1 ../branch
$ cd ../branch
$ echo "Boing" >foo/bar
$ bzr add foo/bar
$ bzr commit -m 'Add foo/bar'

$ bzr merge ../trunk
2>bzr: ERROR: Tree transform is malformed [('unversioned executability', 'new-1')]
""")


class TestResolveActionOption(tests.TestCase):

    def setUp(self):
        super(TestResolveActionOption, self).setUp()
        self.options = [conflicts.ResolveActionOption()]
        self.parser = option.get_optparser(dict((o.name, o)
                                                for o in self.options))

    def parse(self, args):
        return self.parser.parse_args(args)

    def test_unknown_action(self):
        self.assertRaises(errors.BadOptionValue,
                          self.parse, ['--action', 'take-me-to-the-moon'])

    def test_done(self):
        opts, args = self.parse(['--action', 'done'])
        self.assertEqual({'action':'done'}, opts)

    def test_take_this(self):
        opts, args = self.parse(['--action', 'take-this'])
        self.assertEqual({'action': 'take_this'}, opts)
        opts, args = self.parse(['--take-this'])
        self.assertEqual({'action': 'take_this'}, opts)

    def test_take_other(self):
        opts, args = self.parse(['--action', 'take-other'])
        self.assertEqual({'action': 'take_other'}, opts)
        opts, args = self.parse(['--take-other'])
        self.assertEqual({'action': 'take_other'}, opts)
