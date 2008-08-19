# Copyright (C) 2006, 2007 Canonical Ltd
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
#
# Author: Aaron Bentley <aaron.bentley@utoronto.ca>

"""Black-box tests for bzr merge.
"""

import os

from bzrlib import merge_directive
from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir
from bzrlib.conflicts import ConflictList, ContentsConflict
from bzrlib.osutils import abspath, file_kind, pathjoin
from bzrlib.tests.blackbox import ExternalBase
import bzrlib.urlutils as urlutils
from bzrlib.workingtree import WorkingTree


class TestMerge(ExternalBase):

    def example_branch(self, path='.'):
        tree = self.make_branch_and_tree(path)
        self.build_tree_contents([
            (pathjoin(path, 'hello'), 'foo'),
            (pathjoin(path, 'goodbye'), 'baz')])
        tree.add('hello')
        tree.commit(message='setup')
        tree.add('goodbye')
        tree.commit(message='setup')
        return tree

    def test_merge_reprocess(self):
        d = BzrDir.create_standalone_workingtree('.')
        d.commit('h')
        self.run_bzr('merge . --reprocess --merge-type weave')

    def test_merge(self):
        from bzrlib.branch import Branch

        a_tree = self.example_branch('a')
        ancestor = a_tree.branch.revno()
        b_tree = a_tree.bzrdir.sprout('b').open_workingtree()
        self.build_tree_contents([('b/goodbye', 'quux')])
        b_tree.commit(message="more u's are always good")

        self.build_tree_contents([('a/hello', 'quuux')])
        # We can't merge when there are in-tree changes
        os.chdir('a')
        self.run_bzr('merge ../b', retcode=3)
        a = WorkingTree.open('.')
        a_tip = a.commit("Like an epidemic of u's")
        self.run_bzr('merge ../b -r last:1..last:1 --merge-type blooof',
                    retcode=3)
        self.run_bzr('merge ../b -r last:1..last:1 --merge-type merge3')
        a_tree.revert(backups=False)
        self.run_bzr('merge ../b -r last:1..last:1 --merge-type weave')
        a_tree.revert(backups=False)
        self.run_bzr('merge ../b -r last:1..last:1 --merge-type lca')
        a_tree.revert(backups=False)
        self.run_bzr_error(['Show-base is not supported for this merge type'],
                           'merge ../b -r last:1..last:1 --merge-type weave'
                           ' --show-base')
        a_tree.revert(backups=False)
        self.run_bzr('merge ../b -r last:1..last:1 --reprocess')
        a_tree.revert(backups=False)
        self.run_bzr('merge ../b -r last:1')
        self.check_file_contents('goodbye', 'quux')
        # Merging a branch pulls its revision into the tree
        b = Branch.open('../b')
        b_tip = b.last_revision()
        self.failUnless(a.branch.repository.has_revision(b_tip))
        self.assertEqual([a_tip, b_tip], a.get_parent_ids())
        a_tree.revert(backups=False)
        out, err = self.run_bzr('merge -r revno:1:./hello', retcode=3)
        self.assertTrue("Not a branch" in err)
        self.run_bzr('merge -r revno:%d:./..revno:%d:../b'
                    %(ancestor,b.revno()))
        self.assertEquals(a.get_parent_ids(), 
                          [a.branch.last_revision(), b.last_revision()])
        self.check_file_contents('goodbye', 'quux')
        a_tree.revert(backups=False)
        self.run_bzr('merge -r revno:%d:../b'%b.revno())
        self.assertEquals(a.get_parent_ids(),
                          [a.branch.last_revision(), b.last_revision()])
        a_tip = a.commit('merged')
        self.run_bzr('merge ../b -r last:1')
        self.assertEqual([a_tip], a.get_parent_ids())

    def test_merge_with_missing_file(self):
        """Merge handles missing file conflicts"""
        self.build_tree_contents([
            ('a/',),
            ('a/sub/',),
            ('a/sub/a.txt', 'hello\n'),
            ('a/b.txt', 'hello\n'),
            ('a/sub/c.txt', 'hello\n')])
        a_tree = self.make_branch_and_tree('a')
        a_tree.add(['sub', 'b.txt', 'sub/c.txt', 'sub/a.txt'])
        a_tree.commit(message='added a')
        b_tree = a_tree.bzrdir.sprout('b').open_workingtree()
        self.build_tree_contents([
            ('a/sub/a.txt', 'hello\nthere\n'),
            ('a/b.txt', 'hello\nthere\n'),
            ('a/sub/c.txt', 'hello\nthere\n')])
        a_tree.commit(message='Added there')
        os.remove('a/sub/a.txt')
        os.remove('a/sub/c.txt')
        os.rmdir('a/sub')
        os.remove('a/b.txt')
        a_tree.commit(message='Removed a.txt')
        self.build_tree_contents([
            ('b/sub/a.txt', 'hello\nsomething\n'),
            ('b/b.txt', 'hello\nsomething\n'),
            ('b/sub/c.txt', 'hello\nsomething\n')])
        b_tree.commit(message='Modified a.txt')
        os.chdir('b')
        self.run_bzr('merge ../a/', retcode=1)
        self.failUnlessExists('sub/a.txt.THIS')
        self.failUnlessExists('sub/a.txt.BASE')
        os.chdir('../a')
        self.run_bzr('merge ../b/', retcode=1)
        self.failUnlessExists('sub/a.txt.OTHER')
        self.failUnlessExists('sub/a.txt.BASE')

    def test_merge_remember(self):
        """Merge changes from one branch to another, test submit location."""
        tree_a = self.make_branch_and_tree('branch_a')
        branch_a = tree_a.branch
        self.build_tree(['branch_a/a'])
        tree_a.add('a')
        tree_a.commit('commit a')
        branch_b = branch_a.bzrdir.sprout('branch_b').open_branch()
        tree_b = branch_b.bzrdir.open_workingtree()
        branch_c = branch_a.bzrdir.sprout('branch_c').open_branch()
        tree_c = branch_c.bzrdir.open_workingtree()
        self.build_tree(['branch_a/b'])
        tree_a.add('b')
        tree_a.commit('commit b')
        self.build_tree(['branch_c/c'])
        tree_c.add('c')
        tree_c.commit('commit c')
        # reset parent
        parent = branch_b.get_parent()
        branch_b.set_parent(None)
        self.assertEqual(None, branch_b.get_parent())
        # test merge for failure without parent set
        os.chdir('branch_b')
        out = self.run_bzr('merge', retcode=3)
        self.assertEquals(out,
                ('','bzr: ERROR: No location specified or remembered\n'))
        # test implicit --remember when no parent set, this merge conflicts
        self.build_tree(['d'])
        tree_b.add('d')
        self.run_bzr_error(['Working tree ".*" has uncommitted changes'],
                           'merge ../branch_a')
        self.assertEquals(abspath(branch_b.get_submit_branch()),
                          abspath(parent))
        # test implicit --remember after resolving conflict
        tree_b.commit('commit d')
        out, err = self.run_bzr('merge')
        
        base = urlutils.local_path_from_url(branch_a.base)
        self.assertStartsWith(err,
                          'Merging from remembered location %s\n' % (base,))
        self.assertEndsWith(err, '+N  b\nAll changes applied successfully.\n')
        self.assertEquals(abspath(branch_b.get_submit_branch()),
                          abspath(parent))
        # re-open tree as external run_bzr modified it
        tree_b = branch_b.bzrdir.open_workingtree()
        tree_b.commit('merge branch_a')
        # test explicit --remember
        out, err = self.run_bzr('merge ../branch_c --remember')
        self.assertEquals(out, '')
        self.assertEquals(err, '+N  c\nAll changes applied successfully.\n')
        self.assertEquals(abspath(branch_b.get_submit_branch()),
                          abspath(branch_c.bzrdir.root_transport.base))
        # re-open tree as external run_bzr modified it
        tree_b = branch_b.bzrdir.open_workingtree()
        tree_b.commit('merge branch_c')

    def test_merge_bundle(self):
        from bzrlib.testament import Testament
        tree_a = self.make_branch_and_tree('branch_a')
        self.build_tree_contents([('branch_a/a', 'hello')])
        tree_a.add('a')
        tree_a.commit('message')

        tree_b = tree_a.bzrdir.sprout('branch_b').open_workingtree()
        self.build_tree_contents([('branch_a/a', 'hey there')])
        tree_a.commit('message')

        self.build_tree_contents([('branch_b/a', 'goodbye')])
        tree_b.commit('message')
        os.chdir('branch_b')
        self.run_bzr('bundle ../branch_a -o ../bundle')
        os.chdir('../branch_a')
        self.run_bzr('merge ../bundle', retcode=1)
        testament_a = Testament.from_revision(tree_a.branch.repository,
                                              tree_b.get_parent_ids()[0])
        testament_b = Testament.from_revision(tree_b.branch.repository,
                                              tree_b.get_parent_ids()[0])
        self.assertEqualDiff(testament_a.as_text(),
                         testament_b.as_text())
        tree_a.set_conflicts(ConflictList())
        tree_a.commit('message')
        # it is legal to attempt to merge an already-merged bundle
        output = self.run_bzr('merge ../bundle')[1]
        # but it does nothing
        self.assertFalse(tree_a.changes_from(tree_a.basis_tree()).has_changed())
        self.assertEqual('Nothing to do.\n', output)

    def test_merge_uncommitted(self):
        """Check that merge --uncommitted behaves properly"""
        tree_a = self.make_branch_and_tree('a')
        self.build_tree(['a/file_1', 'a/file_2'])
        tree_a.add(['file_1', 'file_2'])
        tree_a.commit('commit 1')
        tree_b = tree_a.bzrdir.sprout('b').open_workingtree()
        self.failUnlessExists('b/file_1')
        tree_a.rename_one('file_1', 'file_i')
        tree_a.commit('commit 2')
        tree_a.rename_one('file_2', 'file_ii')
        ## os.chdir('b')
        self.run_bzr('merge a --uncommitted -d b')
        self.failUnlessExists('b/file_1')
        self.failUnlessExists('b/file_ii')
        tree_b.revert()
        self.run_bzr_error(('Cannot use --uncommitted and --revision',),
                           'merge /a --uncommitted -r1 -d b')

    def test_merge_uncommitted_file(self):
        """It should be possible to merge changes from a single file."""
        tree_a = self.make_branch_and_tree('tree_a')
        tree_a.commit('initial commit')
        tree_a.bzrdir.sprout('tree_b')
        self.build_tree(['tree_a/file1', 'tree_a/file2'])
        tree_a.add(['file1', 'file2'])
        os.chdir('tree_b')
        self.run_bzr(['merge', '--uncommitted', '../tree_a/file1'])
        self.failUnlessExists('file1')
        self.failIfExists('file2')

    def pullable_branch(self):
        tree_a = self.make_branch_and_tree('a')
        self.build_tree(['a/file'])
        tree_a.add(['file'])
        self.id1 = tree_a.commit('commit 1')

        tree_b = self.make_branch_and_tree('b')
        tree_b.pull(tree_a.branch)
        file('b/file', 'wb').write('foo')
        self.id2 = tree_b.commit('commit 2')

    def test_merge_pull(self):
        self.pullable_branch()
        os.chdir('a')
        (out, err) = self.run_bzr('merge --pull ../b')
        self.assertContainsRe(out, 'Now on revision 2\\.')
        tree_a = WorkingTree.open('.')
        self.assertEqual([self.id2], tree_a.get_parent_ids())

    def test_merge_kind_change(self):
        tree_a = self.make_branch_and_tree('tree_a')
        self.build_tree_contents([('tree_a/file', 'content_1')])
        tree_a.add('file', 'file-id')
        tree_a.commit('added file')
        tree_b = tree_a.bzrdir.sprout('tree_b').open_workingtree()
        os.unlink('tree_a/file')
        self.build_tree(['tree_a/file/'])
        tree_a.commit('changed file to directory')
        os.chdir('tree_b')
        self.run_bzr('merge ../tree_a')
        self.assertEqual('directory', file_kind('file'))
        tree_b.revert()
        self.assertEqual('file', file_kind('file'))
        self.build_tree_contents([('file', 'content_2')])
        tree_b.commit('content change')
        self.run_bzr('merge ../tree_a', retcode=1)
        self.assertEqual(tree_b.conflicts(),
                         [ContentsConflict('file', file_id='file-id')])

    def test_directive_cherrypick(self):
        source = self.make_branch_and_tree('source')
        self.build_tree(['source/a'])
        source.add('a')
        source.commit('Added a', rev_id='rev1')
        self.build_tree(['source/b'])
        source.add('b')
        source.commit('Added b', rev_id='rev2')
        target = self.make_branch_and_tree('target')
        target.commit('empty commit')
        self.write_directive('directive', source.branch, 'target', 'rev2',
                             'rev1')
        out, err = self.run_bzr('merge -d target directive')
        self.failIfExists('target/a')
        self.failUnlessExists('target/b')
        self.assertContainsRe(err, 'Performing cherrypick')

    def write_directive(self, filename, source, target, revision_id,
                        base_revision_id=None, mangle_patch=False):
        md = merge_directive.MergeDirective2.from_objects(
            source.repository, revision_id, 0, 0, target,
            base_revision_id=base_revision_id)
        if mangle_patch:
            md.patch = 'asdf\n'
        self.build_tree_contents([(filename, ''.join(md.to_lines()))])

    def test_directive_verify_warning(self):
        source = self.make_branch_and_tree('source')
        self.build_tree(['source/a'])
        source.add('a')
        source.commit('Added a', rev_id='rev1')
        target = self.make_branch_and_tree('target')
        target.commit('empty commit')
        self.write_directive('directive', source.branch, 'target', 'rev1')
        err = self.run_bzr('merge -d target directive')[1]
        self.assertNotContainsRe(err, 'Preview patch does not match changes')
        target.revert()
        self.write_directive('directive', source.branch, 'target', 'rev1',
                             mangle_patch=True)
        err = self.run_bzr('merge -d target directive')[1]
        self.assertContainsRe(err, 'Preview patch does not match changes')

    def test_merge_arbitrary(self):
        target = self.make_branch_and_tree('target')
        target.commit('empty')
        # We need a revision that has no integer revno
        branch_a = target.bzrdir.sprout('branch_a').open_workingtree()
        self.build_tree(['branch_a/file1'])
        branch_a.add('file1')
        branch_a.commit('added file1', rev_id='rev2a')
        branch_b = target.bzrdir.sprout('branch_b').open_workingtree()
        self.build_tree(['branch_b/file2'])
        branch_b.add('file2')
        branch_b.commit('added file2', rev_id='rev2b')
        branch_b.merge_from_branch(branch_a.branch)
        self.failUnlessExists('branch_b/file1')
        branch_b.commit('merged branch_a', rev_id='rev3b')

        # It works if the revid has an interger revno
        self.run_bzr('merge -d target -r revid:rev2a branch_a')
        self.failUnlessExists('target/file1')
        self.failIfExists('target/file2')
        target.revert()

        # It should work if the revid has no integer revno
        self.run_bzr('merge -d target -r revid:rev2a branch_b')
        self.failUnlessExists('target/file1')
        self.failIfExists('target/file2')

    def assertDirectoryContent(self, directory, entries, message=''):
        """Assert whether entries (file or directories) exist in a directory.
        
        It also checks that there are no extra entries.
        """
        ondisk = os.listdir(directory)
        if set(ondisk) == set(entries):
            return
        if message:
            message += '\n'
        raise AssertionError(
            '%s"%s" directory content is different:\na = %s\nb = %s\n'
            % (message, directory, sorted(entries), sorted(ondisk)))

    def test_cherrypicking_merge(self):
        # make source branch
        source = self.make_branch_and_tree('source')
        for f in ('a', 'b', 'c', 'd'):
            self.build_tree(['source/'+f])
            source.add(f)
            source.commit('added '+f, rev_id='rev_'+f)
        # target branch
        target = source.bzrdir.sprout('target', 'rev_a').open_workingtree()
        self.assertDirectoryContent('target', ['.bzr', 'a'])
        # pick 1 revision
        self.run_bzr('merge -d target -r revid:rev_b..revid:rev_c source')
        self.assertDirectoryContent('target', ['.bzr', 'a', 'c'])
        target.revert()
        # pick 2 revisions
        self.run_bzr('merge -d target -r revid:rev_b..revid:rev_d source')
        self.assertDirectoryContent('target', ['.bzr', 'a', 'c', 'd'])
        target.revert()
        # pick 1 revision with option --changes
        self.run_bzr('merge -d target -c revid:rev_d source')
        self.assertDirectoryContent('target', ['.bzr', 'a', 'd'])

    def test_merge_criss_cross(self):
        tree_a = self.make_branch_and_tree('a')
        tree_a.commit('', rev_id='rev1')
        tree_b = tree_a.bzrdir.sprout('b').open_workingtree()
        tree_a.commit('', rev_id='rev2a')
        tree_b.commit('', rev_id='rev2b')
        tree_a.merge_from_branch(tree_b.branch)
        tree_b.merge_from_branch(tree_a.branch)
        tree_a.commit('', rev_id='rev3a')
        tree_b.commit('', rev_id='rev3b')
        graph = tree_a.branch.repository.get_graph(tree_b.branch.repository)
        out, err = self.run_bzr(['merge', '-d', 'a', 'b'])
        self.assertContainsRe(err, 'Warning: criss-cross merge encountered.')

    def test_merge_from_submit(self):
        tree_a = self.make_branch_and_tree('a')
        tree_b = tree_a.bzrdir.sprout('b').open_workingtree()
        tree_c = tree_a.bzrdir.sprout('c').open_workingtree()
        out, err = self.run_bzr(['merge', '-d', 'c'])
        self.assertContainsRe(err, 'Merging from remembered location .*a\/')
        tree_c.branch.set_submit_branch(tree_b.bzrdir.root_transport.base)
        out, err = self.run_bzr(['merge', '-d', 'c'])
        self.assertContainsRe(err, 'Merging from remembered location .*b\/')

    def test_remember_sets_submit(self):
        tree_a = self.make_branch_and_tree('a')
        tree_b = tree_a.bzrdir.sprout('b').open_workingtree()
        self.assertIs(tree_b.branch.get_submit_branch(), None)

        # Remember should not happen if using default from parent
        out, err = self.run_bzr(['merge', '-d', 'b'])
        self.assertIs(tree_b.branch.get_submit_branch(), None)

        # Remember should happen if user supplies location
        out, err = self.run_bzr(['merge', '-d', 'b', 'a'])
        self.assertEqual(tree_b.branch.get_submit_branch(),
                         tree_a.bzrdir.root_transport.base)

    def test_weave_cherrypick(self):
        this_tree = self.make_branch_and_tree('this')
        self.build_tree_contents([('this/file', "a\n")])
        this_tree.add('file')
        this_tree.commit('rev1')
        other_tree = this_tree.bzrdir.sprout('other').open_workingtree()
        self.build_tree_contents([('other/file', "a\nb\n")])
        other_tree.commit('rev2b')
        self.build_tree_contents([('other/file', "c\na\nb\n")])
        other_tree.commit('rev3b')
        self.run_bzr('merge --weave -d this other -r -2..-1')
        self.assertFileEqual('c\na\n', 'this/file')

    def test_lca_merge_criss_cross(self):
        tree_a = self.make_branch_and_tree('a')
        self.build_tree_contents([('a/file', 'base-contents\n')])
        tree_a.add('file')
        tree_a.commit('', rev_id='rev1')
        tree_b = tree_a.bzrdir.sprout('b').open_workingtree()
        self.build_tree_contents([('a/file',
                                   'base-contents\nthis-contents\n')])
        tree_a.commit('', rev_id='rev2a')
        self.build_tree_contents([('b/file',
                                   'base-contents\nother-contents\n')])
        tree_b.commit('', rev_id='rev2b')
        tree_a.merge_from_branch(tree_b.branch)
        self.build_tree_contents([('a/file',
                                   'base-contents\nthis-contents\n')])
        tree_a.set_conflicts(ConflictList())
        tree_b.merge_from_branch(tree_a.branch)
        self.build_tree_contents([('b/file',
                                   'base-contents\nother-contents\n')])
        tree_b.set_conflicts(ConflictList())
        tree_a.commit('', rev_id='rev3a')
        tree_b.commit('', rev_id='rev3b')
        out, err = self.run_bzr(['merge', '-d', 'a', 'b', '--lca'], retcode=1)
        self.assertFileEqual('base-contents\n<<<<<<< TREE\nthis-contents\n'
                             '=======\nother-contents\n>>>>>>> MERGE-SOURCE\n',
                             'a/file')

    def test_merge_preview(self):
        this_tree = self.make_branch_and_tree('this')
        this_tree.commit('rev1')
        other_tree = this_tree.bzrdir.sprout('other').open_workingtree()
        self.build_tree_contents([('other/file', 'new line')])
        other_tree.add('file')
        other_tree.commit('rev2a')
        this_tree.commit('rev2b')
        out, err = self.run_bzr(['merge', '-d', 'this', 'other', '--preview'])
        self.assertContainsRe(out, '\+new line')
        self.assertNotContainsRe(err, '\+N  file\n')
        this_tree.lock_read()
        self.addCleanup(this_tree.unlock)
        self.assertEqual([],
                         list(this_tree.iter_changes(this_tree.basis_tree())))
