# Copyright (C) 2005, 2006 Canonical Ltd
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


"""Tests for the commit CLI of bzr."""

import os
import re
import sys

from bzrlib import (
    ignores,
    )
from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir
from bzrlib.errors import BzrCommandError
from bzrlib.tests.blackbox import ExternalBase
from bzrlib.workingtree import WorkingTree


class TestCommit(ExternalBase):

    def test_05_empty_commit(self):
        """Commit of tree with no versioned files should fail"""
        # If forced, it should succeed, but this is not tested here.
        self.run_bzr("init")
        self.build_tree(['hello.txt'])
        out,err = self.run_bzr('commit -m empty', retcode=3)
        self.assertEqual('', out)
        self.assertStartsWith(err, 'bzr: ERROR: no changes to commit.'
                                  ' use --unchanged to commit anyhow\n')

    def test_commit_success(self):
        """Successful commit should not leave behind a bzr-commit-* file"""
        self.run_bzr("init")
        self.run_bzr('commit --unchanged -m message')
        self.assertEqual('', self.run_bzr('unknowns')[0])

        # same for unicode messages
        self.run_bzr(["commit", "--unchanged", "-m", u'foo\xb5'])
        self.assertEqual('', self.run_bzr('unknowns')[0])

    def test_commit_with_path(self):
        """Commit tree with path of root specified"""
        self.run_bzr('init a')
        self.build_tree(['a/a_file'])
        self.run_bzr('add a/a_file')
        self.run_bzr('commit -m first-commit a')

        self.run_bzr('branch a b')
        self.build_tree_contents([('b/a_file', 'changes in b')])
        self.run_bzr('commit -m first-commit-in-b b')

        self.build_tree_contents([('a/a_file', 'new contents')])
        self.run_bzr('commit -m change-in-a a')

        os.chdir('b')
        self.run_bzr('merge ../a', retcode=1) # will conflict
        os.chdir('..')
        self.run_bzr('resolved b/a_file')
        self.run_bzr('commit -m merge-into-b b')


    def test_10_verbose_commit(self):
        """Add one file and examine verbose commit output"""
        self.run_bzr("init")
        self.build_tree(['hello.txt'])
        self.run_bzr("add hello.txt")
        out,err = self.run_bzr('commit -m added')
        self.assertEqual('', out)
        self.assertEqual('added hello.txt\n'
                         'Committed revision 1.\n',
                         err)

    def prepare_simple_history(self):
        """Prepare and return a working tree with one commit of one file"""
        # Commit with modified file should say so
        wt = BzrDir.create_standalone_workingtree('.')
        self.build_tree(['hello.txt', 'extra.txt'])
        wt.add(['hello.txt'])
        wt.commit(message='added')
        return wt

    def test_verbose_commit_modified(self):
        # Verbose commit of modified file should say so
        wt = self.prepare_simple_history()
        self.build_tree_contents([('hello.txt', 'new contents')])
        out, err = self.run_bzr('commit -m modified')
        self.assertEqual('', out)
        self.assertEqual('modified hello.txt\n'
                         'Committed revision 2.\n',
                         err)

    def test_verbose_commit_renamed(self):
        # Verbose commit of renamed file should say so
        wt = self.prepare_simple_history()
        wt.rename_one('hello.txt', 'gutentag.txt')
        out, err = self.run_bzr('commit -m renamed')
        self.assertEqual('', out)
        self.assertEqual('renamed hello.txt => gutentag.txt\n'
                         'Committed revision 2.\n',
                         err)

    def test_verbose_commit_moved(self):
        # Verbose commit of file moved to new directory should say so
        wt = self.prepare_simple_history()
        os.mkdir('subdir')
        wt.add(['subdir'])
        wt.rename_one('hello.txt', 'subdir/hello.txt')
        out, err = self.run_bzr('commit -m renamed')
        self.assertEqual('', out)
        self.assertEqualDiff('added subdir\n'
                             'renamed hello.txt => subdir/hello.txt\n'
                             'Committed revision 2.\n',
                             err)

    def test_verbose_commit_with_unknown(self):
        """Unknown files should not be listed by default in verbose output"""
        # Is that really the best policy?
        wt = BzrDir.create_standalone_workingtree('.')
        self.build_tree(['hello.txt', 'extra.txt'])
        wt.add(['hello.txt'])
        out,err = self.run_bzr('commit -m added')
        self.assertEqual('', out)
        self.assertEqual('added hello.txt\n'
                         'Committed revision 1.\n',
                         err)

    def test_verbose_commit_with_unchanged(self):
        """Unchanged files should not be listed by default in verbose output"""
        self.run_bzr("init")
        self.build_tree(['hello.txt', 'unchanged.txt'])
        self.run_bzr('add unchanged.txt')
        self.run_bzr('commit -m unchanged unchanged.txt')
        self.run_bzr("add hello.txt")
        out,err = self.run_bzr('commit -m added')
        self.assertEqual('', out)
        self.assertEqual('added hello.txt\n'
                         'Committed revision 2.\n',
                         err)

    def test_commit_merge_reports_all_modified_files(self):
        # the commit command should show all the files that are shown by
        # bzr diff or bzr status when committing, even when they were not
        # changed by the user but rather through doing a merge.
        this_tree = self.make_branch_and_tree('this')
        # we need a bunch of files and dirs, to perform one action on each.
        self.build_tree([
            'this/dirtorename/',
            'this/dirtoreparent/',
            'this/dirtoleave/',
            'this/dirtoremove/',
            'this/filetoreparent',
            'this/filetorename',
            'this/filetomodify',
            'this/filetoremove',
            'this/filetoleave']
            )
        this_tree.add([
            'dirtorename',
            'dirtoreparent',
            'dirtoleave',
            'dirtoremove',
            'filetoreparent',
            'filetorename',
            'filetomodify',
            'filetoremove',
            'filetoleave']
            )
        this_tree.commit('create_files')
        other_dir = this_tree.bzrdir.sprout('other')
        other_tree = other_dir.open_workingtree()
        other_tree.lock_write()
        # perform the needed actions on the files and dirs.
        try:
            other_tree.rename_one('dirtorename', 'renameddir')
            other_tree.rename_one('dirtoreparent', 'renameddir/reparenteddir')
            other_tree.rename_one('filetorename', 'renamedfile')
            other_tree.rename_one('filetoreparent', 'renameddir/reparentedfile')
            other_tree.remove(['dirtoremove', 'filetoremove'])
            self.build_tree_contents([
                ('other/newdir/', ),
                ('other/filetomodify', 'new content'),
                ('other/newfile', 'new file content')])
            other_tree.add('newfile')
            other_tree.add('newdir/')
            other_tree.commit('modify all sample files and dirs.')
        finally:
            other_tree.unlock()
        this_tree.merge_from_branch(other_tree.branch)
        os.chdir('this')
        out,err = self.run_bzr('commit -m added')
        os.chdir('..')
        self.assertEqual('', out)
        self.assertEqualDiff(
            'modified filetomodify\n'
            'added newdir\n'
            'added newfile\n'
            'renamed dirtorename => renameddir\n'
            'renamed dirtoreparent => renameddir/reparenteddir\n'
            'renamed filetoreparent => renameddir/reparentedfile\n'
            'renamed filetorename => renamedfile\n'
            'deleted dirtoremove\n'
            'deleted filetoremove\n'
            'Committed revision 2.\n',
            err)

    def test_empty_commit_message(self):
        self.run_bzr("init")
        file('foo.c', 'wt').write('int main() {}')
        self.run_bzr('add foo.c')
        self.run_bzr('commit -m ""', retcode=3)

    def test_other_branch_commit(self):
        # this branch is to ensure consistent behaviour, whether we're run
        # inside a branch, or not.
        os.mkdir('empty_branch')
        os.chdir('empty_branch')
        self.run_bzr('init')
        os.mkdir('branch')
        os.chdir('branch')
        self.run_bzr('init')
        file('foo.c', 'wt').write('int main() {}')
        file('bar.c', 'wt').write('int main() {}')
        os.chdir('..')
        self.run_bzr('add branch/foo.c')
        self.run_bzr('add branch')
        # can't commit files in different trees; sane error
        self.run_bzr('commit -m newstuff branch/foo.c .', retcode=3)
        self.run_bzr('commit -m newstuff branch/foo.c')
        self.run_bzr('commit -m newstuff branch')
        self.run_bzr('commit -m newstuff branch', retcode=3)

    def test_out_of_date_tree_commit(self):
        # check we get an error code and a clear message committing with an out
        # of date checkout
        self.make_branch_and_tree('branch')
        # make a checkout
        self.run_bzr('checkout --lightweight branch checkout')
        # commit to the original branch to make the checkout out of date
        self.run_bzr('commit --unchanged -m message branch')
        # now commit to the checkout should emit
        # ERROR: Out of date with the branch, 'bzr update' is suggested
        output = self.run_bzr('commit --unchanged -m checkout_message '
                             'checkout', retcode=3)
        self.assertEqual(output,
                         ('',
                          "bzr: ERROR: Working tree is out of date, please run "
                          "'bzr update'.\n"))

    def test_local_commit_unbound(self):
        # a --local commit on an unbound branch is an error
        self.make_branch_and_tree('.')
        out, err = self.run_bzr('commit --local', retcode=3)
        self.assertEqualDiff('', out)
        self.assertEqualDiff('bzr: ERROR: Cannot perform local-only commits '
                             'on unbound branches.\n', err)

    def test_commit_a_text_merge_in_a_checkout(self):
        # checkouts perform multiple actions in a transaction across bond
        # branches and their master, and have been observed to fail in the
        # past. This is a user story reported to fail in bug #43959 where 
        # a merge done in a checkout (using the update command) failed to
        # commit correctly.
        self.run_bzr('init trunk')

        self.run_bzr('checkout trunk u1')
        self.build_tree_contents([('u1/hosts', 'initial contents')])
        self.run_bzr('add u1/hosts')
        self.run_bzr('commit -m add-hosts u1')

        self.run_bzr('checkout trunk u2')
        self.build_tree_contents([('u2/hosts', 'altered in u2')])
        self.run_bzr('commit -m checkin-from-u2 u2')

        # make an offline commits
        self.build_tree_contents([('u1/hosts', 'first offline change in u1')])
        self.run_bzr('commit -m checkin-offline --local u1')

        # now try to pull in online work from u2, and then commit our offline
        # work as a merge
        # retcode 1 as we expect a text conflict
        self.run_bzr('update u1', retcode=1)
        self.run_bzr('resolved u1/hosts')
        # add a text change here to represent resolving the merge conflicts in
        # favour of a new version of the file not identical to either the u1
        # version or the u2 version.
        self.build_tree_contents([('u1/hosts', 'merge resolution\n')])
        self.run_bzr('commit -m checkin-merge-of-the-offline-work-from-u1 u1')

    def test_commit_respects_spec_for_removals(self):
        """Commit with a file spec should only commit removals that match"""
        t = self.make_branch_and_tree('.')
        self.build_tree(['file-a', 'dir-a/', 'dir-a/file-b'])
        t.add(['file-a', 'dir-a', 'dir-a/file-b'])
        t.commit('Create')
        t.remove(['file-a', 'dir-a/file-b'])
        os.chdir('dir-a')
        result = self.run_bzr('commit . -m removed-file-b')[1]
        self.assertNotContainsRe(result, 'file-a')
        result = self.run_bzr('status')[0]
        self.assertContainsRe(result, 'removed:\n  file-a')

    def test_strict_commit(self):
        """Commit with --strict works if everything is known"""
        ignores._set_user_ignores([])
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a'])
        tree.add('a')
        # A simple change should just work
        self.run_bzr('commit --strict -m adding-a',
                     working_dir='tree')

    def test_strict_commit_no_changes(self):
        """commit --strict gives "no changes" if there is nothing to commit"""
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a'])
        tree.add('a')
        tree.commit('adding a')

        # With no changes, it should just be 'no changes'
        # Make sure that commit is failing because there is nothing to do
        self.run_bzr_error(['no changes to commit'],
                           'commit --strict -m no-changes',
                           working_dir='tree')

        # But --strict doesn't care if you supply --unchanged
        self.run_bzr('commit --strict --unchanged -m no-changes',
                     working_dir='tree')

    def test_strict_commit_unknown(self):
        """commit --strict fails if a file is unknown"""
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a'])
        tree.add('a')
        tree.commit('adding a')

        # Add one file so there is a change, but forget the other
        self.build_tree(['tree/b', 'tree/c'])
        tree.add('b')
        self.run_bzr_error(['Commit refused because there are unknown files'],
                           'commit --strict -m add-b',
                           working_dir='tree')

        # --no-strict overrides --strict
        self.run_bzr('commit --strict -m add-b --no-strict',
                     working_dir='tree')

    def test_fixes_bug_output(self):
        """commit --fixes=lp:23452 succeeds without output."""
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/hello.txt'])
        tree.add('hello.txt')
        output, err = self.run_bzr(
            'commit -m hello --fixes=lp:23452 tree/hello.txt')
        self.assertEqual('', output)
        self.assertEqual('added hello.txt\nCommitted revision 1.\n', err)

    def test_no_bugs_no_properties(self):
        """If no bugs are fixed, the bugs property is not set.

        see https://beta.launchpad.net/bzr/+bug/109613
        """
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/hello.txt'])
        tree.add('hello.txt')
        self.run_bzr( 'commit -m hello tree/hello.txt')
        # Get the revision properties, ignoring the branch-nick property, which
        # we don't care about for this test.
        last_rev = tree.branch.repository.get_revision(tree.last_revision())
        properties = dict(last_rev.properties)
        del properties['branch-nick']
        self.assertFalse('bugs' in properties)

    def test_fixes_bug_sets_property(self):
        """commit --fixes=lp:234 sets the lp:234 revprop to 'fixed'."""
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/hello.txt'])
        tree.add('hello.txt')
        self.run_bzr('commit -m hello --fixes=lp:234 tree/hello.txt')

        # Get the revision properties, ignoring the branch-nick property, which
        # we don't care about for this test.
        last_rev = tree.branch.repository.get_revision(tree.last_revision())
        properties = dict(last_rev.properties)
        del properties['branch-nick']

        self.assertEqual({'bugs': 'https://launchpad.net/bugs/234 fixed'},
                         properties)

    def test_fixes_multiple_bugs_sets_properties(self):
        """--fixes can be used more than once to show that bugs are fixed."""
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/hello.txt'])
        tree.add('hello.txt')
        self.run_bzr('commit -m hello --fixes=lp:123 --fixes=lp:235'
                     ' tree/hello.txt')

        # Get the revision properties, ignoring the branch-nick property, which
        # we don't care about for this test.
        last_rev = tree.branch.repository.get_revision(tree.last_revision())
        properties = dict(last_rev.properties)
        del properties['branch-nick']

        self.assertEqual(
            {'bugs': 'https://launchpad.net/bugs/123 fixed\n'
                     'https://launchpad.net/bugs/235 fixed'},
            properties)

    def test_fixes_bug_with_alternate_trackers(self):
        """--fixes can be used on a properly configured branch to mark bug
        fixes on multiple trackers.
        """
        tree = self.make_branch_and_tree('tree')
        tree.branch.get_config().set_user_option(
            'trac_twisted_url', 'http://twistedmatrix.com/trac')
        self.build_tree(['tree/hello.txt'])
        tree.add('hello.txt')
        self.run_bzr('commit -m hello --fixes=lp:123 --fixes=twisted:235 tree/')

        # Get the revision properties, ignoring the branch-nick property, which
        # we don't care about for this test.
        last_rev = tree.branch.repository.get_revision(tree.last_revision())
        properties = dict(last_rev.properties)
        del properties['branch-nick']

        self.assertEqual(
            {'bugs': 'https://launchpad.net/bugs/123 fixed\n'
                     'http://twistedmatrix.com/trac/ticket/235 fixed'},
            properties)

    def test_fixes_unknown_bug_prefix(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/hello.txt'])
        tree.add('hello.txt')
        self.run_bzr_error(
            ["Unrecognized bug %s. Commit refused." % 'xxx:123'],
            'commit -m add-b --fixes=xxx:123',
            working_dir='tree')

    def test_fixes_invalid_bug_number(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/hello.txt'])
        tree.add('hello.txt')
        self.run_bzr_error(
            ["Invalid bug identifier for %s. Commit refused." % 'lp:orange'],
            'commit -m add-b --fixes=lp:orange',
            working_dir='tree')

    def test_fixes_invalid_argument(self):
        """Raise an appropriate error when the fixes argument isn't tag:id."""
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/hello.txt'])
        tree.add('hello.txt')
        self.run_bzr_error(
            [r"Invalid bug orange. Must be in the form of 'tag:id'\. "
             r"Commit refused\."],
            'commit -m add-b --fixes=orange',
            working_dir='tree')
