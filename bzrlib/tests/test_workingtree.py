# Copyright (C) 2005, 2006 Canonical Ltd
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

from cStringIO import StringIO
import os

from bzrlib import ignores
import bzrlib
from bzrlib.branch import Branch
from bzrlib import bzrdir, conflicts, errors, workingtree
from bzrlib.bzrdir import BzrDir
from bzrlib.errors import NotBranchError, NotVersionedError
from bzrlib.lockdir import LockDir
from bzrlib.osutils import pathjoin, getcwd, has_symlinks
from bzrlib.tests import TestCaseWithTransport, TestSkipped
from bzrlib.trace import mutter
from bzrlib.transport import get_transport
from bzrlib.workingtree import (TreeEntry, TreeDirectory, TreeFile, TreeLink,
                                WorkingTree)

class TestTreeDirectory(TestCaseWithTransport):

    def test_kind_character(self):
        self.assertEqual(TreeDirectory().kind_character(), '/')


class TestTreeEntry(TestCaseWithTransport):

    def test_kind_character(self):
        self.assertEqual(TreeEntry().kind_character(), '???')


class TestTreeFile(TestCaseWithTransport):

    def test_kind_character(self):
        self.assertEqual(TreeFile().kind_character(), '')


class TestTreeLink(TestCaseWithTransport):

    def test_kind_character(self):
        self.assertEqual(TreeLink().kind_character(), '')


class TestDefaultFormat(TestCaseWithTransport):

    def test_get_set_default_format(self):
        old_format = workingtree.WorkingTreeFormat.get_default_format()
        # default is 3
        self.assertTrue(isinstance(old_format, workingtree.WorkingTreeFormat3))
        workingtree.WorkingTreeFormat.set_default_format(SampleTreeFormat())
        try:
            # the default branch format is used by the meta dir format
            # which is not the default bzrdir format at this point
            dir = bzrdir.BzrDirMetaFormat1().initialize('.')
            dir.create_repository()
            dir.create_branch()
            result = dir.create_workingtree()
            self.assertEqual(result, 'A tree')
        finally:
            workingtree.WorkingTreeFormat.set_default_format(old_format)
        self.assertEqual(old_format, workingtree.WorkingTreeFormat.get_default_format())


class SampleTreeFormat(workingtree.WorkingTreeFormat):
    """A sample format

    this format is initializable, unsupported to aid in testing the 
    open and open_downlevel routines.
    """

    def get_format_string(self):
        """See WorkingTreeFormat.get_format_string()."""
        return "Sample tree format."

    def initialize(self, a_bzrdir, revision_id=None):
        """Sample branches cannot be created."""
        t = a_bzrdir.get_workingtree_transport(self)
        t.put('format', StringIO(self.get_format_string()))
        return 'A tree'

    def is_supported(self):
        return False

    def open(self, transport, _found=False):
        return "opened tree."


class TestWorkingTreeFormat(TestCaseWithTransport):
    """Tests for the WorkingTreeFormat facility."""

    def test_find_format(self):
        # is the right format object found for a working tree?
        # create a branch with a few known format objects.
        self.build_tree(["foo/", "bar/"])
        def check_format(format, url):
            dir = format._matchingbzrdir.initialize(url)
            dir.create_repository()
            dir.create_branch()
            format.initialize(dir)
            t = get_transport(url)
            found_format = workingtree.WorkingTreeFormat.find_format(dir)
            self.failUnless(isinstance(found_format, format.__class__))
        check_format(workingtree.WorkingTreeFormat3(), "bar")
        
    def test_find_format_no_tree(self):
        dir = bzrdir.BzrDirMetaFormat1().initialize('.')
        self.assertRaises(errors.NoWorkingTree,
                          workingtree.WorkingTreeFormat.find_format,
                          dir)

    def test_find_format_unknown_format(self):
        dir = bzrdir.BzrDirMetaFormat1().initialize('.')
        dir.create_repository()
        dir.create_branch()
        SampleTreeFormat().initialize(dir)
        self.assertRaises(errors.UnknownFormatError,
                          workingtree.WorkingTreeFormat.find_format,
                          dir)

    def test_register_unregister_format(self):
        format = SampleTreeFormat()
        # make a control dir
        dir = bzrdir.BzrDirMetaFormat1().initialize('.')
        dir.create_repository()
        dir.create_branch()
        # make a branch
        format.initialize(dir)
        # register a format for it.
        workingtree.WorkingTreeFormat.register_format(format)
        # which branch.Open will refuse (not supported)
        self.assertRaises(errors.UnsupportedFormatError, workingtree.WorkingTree.open, '.')
        # but open_downlevel will work
        self.assertEqual(format.open(dir), workingtree.WorkingTree.open_downlevel('.'))
        # unregister the format
        workingtree.WorkingTreeFormat.unregister_format(format)


class TestWorkingTreeFormat3(TestCaseWithTransport):
    """Tests specific to WorkingTreeFormat3."""

    def test_disk_layout(self):
        control = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        control.create_repository()
        control.create_branch()
        tree = workingtree.WorkingTreeFormat3().initialize(control)
        # we want:
        # format 'Bazaar-NG Working Tree format 3'
        # inventory = blank inventory
        # pending-merges = ''
        # stat-cache = ??
        # no inventory.basis yet
        t = control.get_workingtree_transport(None)
        self.assertEqualDiff('Bazaar-NG Working Tree format 3',
                             t.get('format').read())
        self.assertEqualDiff('<inventory format="5">\n'
                             '</inventory>\n',
                             t.get('inventory').read())
        self.assertEqualDiff('### bzr hashcache v5\n',
                             t.get('stat-cache').read())
        self.assertFalse(t.has('inventory.basis'))
        # no last-revision file means 'None' or 'NULLREVISION'
        self.assertFalse(t.has('last-revision'))
        # TODO RBC 20060210 do a commit, check the inventory.basis is created 
        # correctly and last-revision file becomes present.

    def test_uses_lockdir(self):
        """WorkingTreeFormat3 uses its own LockDir:
            
            - lock is a directory
            - when the WorkingTree is locked, LockDir can see that
        """
        t = self.get_transport()
        url = self.get_url()
        dir = bzrdir.BzrDirMetaFormat1().initialize(url)
        repo = dir.create_repository()
        branch = dir.create_branch()
        try:
            tree = workingtree.WorkingTreeFormat3().initialize(dir)
        except errors.NotLocalUrl:
            raise TestSkipped('Not a local URL')
        self.assertIsDirectory('.bzr', t)
        self.assertIsDirectory('.bzr/checkout', t)
        self.assertIsDirectory('.bzr/checkout/lock', t)
        our_lock = LockDir(t, '.bzr/checkout/lock')
        self.assertEquals(our_lock.peek(), None)
        tree.lock_write()
        self.assertTrue(our_lock.peek())
        tree.unlock()
        self.assertEquals(our_lock.peek(), None)

    def test_missing_pending_merges(self):
        control = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        control.create_repository()
        control.create_branch()
        tree = workingtree.WorkingTreeFormat3().initialize(control)
        tree._control_files._transport.delete("pending-merges")
        self.assertEqual([], tree.pending_merges())


class TestFormat2WorkingTree(TestCaseWithTransport):
    """Tests that are specific to format 2 trees."""

    def create_format2_tree(self, url):
        return self.make_branch_and_tree(
            url, format=bzrlib.bzrdir.BzrDirFormat6())

    def test_conflicts(self):
        # test backwards compatability
        tree = self.create_format2_tree('.')
        self.assertRaises(errors.UnsupportedOperation, tree.set_conflicts,
                          None)
        file('lala.BASE', 'wb').write('labase')
        expected = conflicts.ContentsConflict('lala')
        self.assertEqual(list(tree.conflicts()), [expected])
        file('lala', 'wb').write('la')
        tree.add('lala', 'lala-id')
        expected = conflicts.ContentsConflict('lala', file_id='lala-id')
        self.assertEqual(list(tree.conflicts()), [expected])
        file('lala.THIS', 'wb').write('lathis')
        file('lala.OTHER', 'wb').write('laother')
        # When "text conflict"s happen, stem, THIS and OTHER are text
        expected = conflicts.TextConflict('lala', file_id='lala-id')
        self.assertEqual(list(tree.conflicts()), [expected])
        os.unlink('lala.OTHER')
        os.mkdir('lala.OTHER')
        expected = conflicts.ContentsConflict('lala', file_id='lala-id')
        self.assertEqual(list(tree.conflicts()), [expected])


class TestNonFormatSpecificCode(TestCaseWithTransport):
    """This class contains tests of workingtree that are not format specific."""

    
    def test_gen_file_id(self):
        gen_file_id = bzrlib.workingtree.gen_file_id

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
        self.failUnless(len(fid) < 60)

        # restricting length happens after the other actions, so
        # we preserve as much as possible
        fid = gen_file_id('\xe5\xb5..aBcd\tefGhijKLMnop\tqrstuvwxyz')
        self.assertStartsWith(fid, 'abcdefghijklmnopqrst-')
        self.failUnless(len(fid) < 60)

    def test_next_id_suffix(self):
        bzrlib.workingtree._gen_id_suffix = None
        bzrlib.workingtree._next_id_suffix()
        self.assertNotEqual(None, bzrlib.workingtree._gen_id_suffix)
        bzrlib.workingtree._gen_id_suffix = "foo-"
        bzrlib.workingtree._gen_id_serial = 1
        self.assertEqual("foo-2", bzrlib.workingtree._next_id_suffix())
        self.assertEqual("foo-3", bzrlib.workingtree._next_id_suffix())
        self.assertEqual("foo-4", bzrlib.workingtree._next_id_suffix())
        self.assertEqual("foo-5", bzrlib.workingtree._next_id_suffix())
        self.assertEqual("foo-6", bzrlib.workingtree._next_id_suffix())
        self.assertEqual("foo-7", bzrlib.workingtree._next_id_suffix())
        self.assertEqual("foo-8", bzrlib.workingtree._next_id_suffix())
        self.assertEqual("foo-9", bzrlib.workingtree._next_id_suffix())
        self.assertEqual("foo-10", bzrlib.workingtree._next_id_suffix())

    def test__translate_ignore_rule(self):
        tree = self.make_branch_and_tree('.')
        # translation should return the regex, the number of groups in it,
        # and the original rule in a tuple.
        # there are three sorts of ignore rules:
        # root only - regex is the rule itself without the leading ./
        self.assertEqual(
            "(rootdirrule$)", 
            tree._translate_ignore_rule("./rootdirrule"))
        # full path - regex is the rule itself
        self.assertEqual(
            "(path\\/to\\/file$)",
            tree._translate_ignore_rule("path/to/file"))
        # basename only rule - regex is a rule that ignores everything up
        # to the last / in the filename
        self.assertEqual(
            "((?:.*/)?(?!.*/)basenamerule$)",
            tree._translate_ignore_rule("basenamerule"))

    def test__combine_ignore_rules(self):
        tree = self.make_branch_and_tree('.')
        # the combined ignore regexs need the outer group indices
        # placed in a dictionary with the rules that were combined.
        # an empty set of rules
        # this is returned as a list of combined regex,rule sets, because
        # python has a limit of 100 combined regexes.
        compiled_rules = tree._combine_ignore_rules([])
        self.assertEqual([], compiled_rules)
        # one of each type of rule.
        compiled_rules = tree._combine_ignore_rules(
            ["rule1", "rule/two", "./three"])[0]
        # what type *is* the compiled regex to do an isinstance of ?
        self.assertEqual(3, compiled_rules[0].groups)
        self.assertEqual(
            {0:"rule1",1:"rule/two",2:"./three"},
            compiled_rules[1])

    def test__combine_ignore_rules_grouping(self):
        tree = self.make_branch_and_tree('.')
        # when there are too many rules, the output is split into groups of 100
        rules = []
        for index in range(198):
            rules.append('foo')
        self.assertEqual(2, len(tree._combine_ignore_rules(rules)))

    def test__get_ignore_rules_as_regex(self):
        tree = self.make_branch_and_tree('.')
        # Setup the default ignore list to be empty
        ignores.set_user_ignores([])

        # some plugins (shelf) modifies the DEFAULT_IGNORE list in memory
        # which causes this test to fail so force the DEFAULT_IGNORE
        # list to be empty
        orig_default = bzrlib.DEFAULT_IGNORE
        # Also make sure the runtime ignore list is empty
        orig_runtime = ignores._runtime_ignores
        try:
            bzrlib.DEFAULT_IGNORE = []
            ignores._runtime_ignores = set()

            self.build_tree_contents([('.bzrignore', 'CVS\n.hg\n')])
            reference_output = tree._combine_ignore_rules(['CVS', '.hg'])[0]
            regex_rules = tree._get_ignore_rules_as_regex()[0]
            self.assertEqual(len(reference_output[1]), regex_rules[0].groups)
            self.assertEqual(reference_output[1], regex_rules[1])
        finally:
            bzrlib.DEFAULT_IGNORE = orig_default
            ignores._runtime_ignores = orig_runtime
