# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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

import os
from cStringIO import StringIO

from bzrlib import log
from bzrlib.tests import BzrTestBase, TestCaseWithTransport
from bzrlib.log import (show_log, 
                        get_view_revisions, 
                        LogRevision,
                        LogFormatter, 
                        LongLogFormatter, 
                        ShortLogFormatter, 
                        LineLogFormatter)
from bzrlib.branch import Branch
from bzrlib.errors import InvalidRevisionNumber


class LogCatcher(LogFormatter):
    """Pull log messages into list rather than displaying them.

    For ease of testing we save log messages here rather than actually
    formatting them, so that we can precisely check the result without
    being too dependent on the exact formatting.

    We should also test the LogFormatter.
    """

    supports_delta = True 

    def __init__(self):
        super(LogCatcher, self).__init__(to_file=None)
        self.logs = []

    def log_revision(self, revision):
        self.logs.append(revision)


class TestShowLog(TestCaseWithTransport):

    def checkDelta(self, delta, **kw):
        """Check the filenames touched by a delta are as expected."""
        for n in 'added', 'removed', 'renamed', 'modified', 'unchanged':
            expected = kw.get(n, [])
            # strip out only the path components
            got = [x[0] for x in getattr(delta, n)]
            self.assertEquals(expected, got)

    def test_cur_revno(self):
        wt = self.make_branch_and_tree('.')
        b = wt.branch

        lf = LogCatcher()
        wt.commit('empty commit')
        show_log(b, lf, verbose=True, start_revision=1, end_revision=1)
        self.assertRaises(InvalidRevisionNumber, show_log, b, lf,
                          start_revision=2, end_revision=1) 
        self.assertRaises(InvalidRevisionNumber, show_log, b, lf,
                          start_revision=1, end_revision=2) 
        self.assertRaises(InvalidRevisionNumber, show_log, b, lf,
                          start_revision=0, end_revision=2) 
        self.assertRaises(InvalidRevisionNumber, show_log, b, lf,
                          start_revision=1, end_revision=0) 
        self.assertRaises(InvalidRevisionNumber, show_log, b, lf,
                          start_revision=-1, end_revision=1) 
        self.assertRaises(InvalidRevisionNumber, show_log, b, lf,
                          start_revision=1, end_revision=-1) 

    def test_simple_log(self):
        eq = self.assertEquals
        
        wt = self.make_branch_and_tree('.')
        b = wt.branch

        lf = LogCatcher()
        show_log(b, lf)
        # no entries yet
        eq(lf.logs, [])

        wt.commit('empty commit')
        lf = LogCatcher()
        show_log(b, lf, verbose=True)
        eq(len(lf.logs), 1)
        eq(lf.logs[0].revno, '1')
        eq(lf.logs[0].rev.message, 'empty commit')
        d = lf.logs[0].delta
        self.log('log delta: %r' % d)
        self.checkDelta(d)

        self.build_tree(['hello'])
        wt.add('hello')
        wt.commit('add one file')

        lf = StringIO()
        # log using regular thing
        show_log(b, LongLogFormatter(lf))
        lf.seek(0)
        for l in lf.readlines():
            self.log(l)

        # get log as data structure
        lf = LogCatcher()
        show_log(b, lf, verbose=True)
        eq(len(lf.logs), 2)
        self.log('log entries:')
        for logentry in lf.logs:
            self.log('%4s %s' % (logentry.revno, logentry.rev.message))
        
        # first one is most recent
        logentry = lf.logs[0]
        eq(logentry.revno, '2')
        eq(logentry.rev.message, 'add one file')
        d = logentry.delta
        self.log('log 2 delta: %r' % d)
        self.checkDelta(d, added=['hello'])
        
        # commit a log message with control characters
        msg = "All 8-bit chars: " +  ''.join([unichr(x) for x in range(256)])
        self.log("original commit message: %r", msg)
        wt.commit(msg)
        lf = LogCatcher()
        show_log(b, lf, verbose=True)
        committed_msg = lf.logs[0].rev.message
        self.log("escaped commit message: %r", committed_msg)
        self.assert_(msg != committed_msg)
        self.assert_(len(committed_msg) > len(msg))

        # Check that log message with only XML-valid characters isn't
        # escaped.  As ElementTree apparently does some kind of
        # newline conversion, neither LF (\x0A) nor CR (\x0D) are
        # included in the test commit message, even though they are
        # valid XML 1.0 characters.
        msg = "\x09" + ''.join([unichr(x) for x in range(0x20, 256)])
        self.log("original commit message: %r", msg)
        wt.commit(msg)
        lf = LogCatcher()
        show_log(b, lf, verbose=True)
        committed_msg = lf.logs[0].rev.message
        self.log("escaped commit message: %r", committed_msg)
        self.assert_(msg == committed_msg)

    def test_deltas_in_merge_revisions(self):
        """Check deltas created for both mainline and merge revisions"""
        eq = self.assertEquals
        wt = self.make_branch_and_tree('parent')
        self.build_tree(['parent/file1', 'parent/file2', 'parent/file3'])
        wt.add('file1')
        wt.add('file2')
        wt.commit(message='add file1 and file2')
        self.run_bzr('branch', 'parent', 'child')
        os.unlink('child/file1')
        print >> file('child/file2', 'wb'), 'hello'
        self.run_bzr('commit', '-m', 'remove file1 and modify file2', 'child')
        os.chdir('parent')
        self.run_bzr('merge', '../child')
        wt.commit('merge child branch')
        os.chdir('..')
        b = wt.branch
        lf = LogCatcher()
        lf.supports_merge_revisions = True
        show_log(b, lf, verbose=True)
        eq(len(lf.logs),3)
        logentry = lf.logs[0]
        eq(logentry.revno, '2')
        eq(logentry.rev.message, 'merge child branch')
        d = logentry.delta
        self.checkDelta(d, removed=['file1'], modified=['file2'])
        logentry = lf.logs[1]
        eq(logentry.revno, '1.1.1')
        eq(logentry.rev.message, 'remove file1 and modify file2')
        d = logentry.delta
        self.checkDelta(d, removed=['file1'], modified=['file2'])
        logentry = lf.logs[2]
        eq(logentry.revno, '1')
        eq(logentry.rev.message, 'add file1 and file2')
        d = logentry.delta
        self.checkDelta(d, added=['file1', 'file2'])


def make_commits_with_trailing_newlines(wt):
    """Helper method for LogFormatter tests"""    
    b = wt.branch
    b.nick='test'
    open('a', 'wb').write('hello moto\n')
    wt.add('a')
    wt.commit('simple log message', rev_id='a1'
            , timestamp=1132586655.459960938, timezone=-6*3600
            , committer='Joe Foo <joe@foo.com>')
    open('b', 'wb').write('goodbye\n')
    wt.add('b')
    wt.commit('multiline\nlog\nmessage\n', rev_id='a2'
            , timestamp=1132586842.411175966, timezone=-6*3600
            , committer='Joe Foo <joe@foo.com>')

    open('c', 'wb').write('just another manic monday\n')
    wt.add('c')
    wt.commit('single line with trailing newline\n', rev_id='a3'
            , timestamp=1132587176.835228920, timezone=-6*3600
            , committer = 'Joe Foo <joe@foo.com>')
    return b


class TestShortLogFormatter(TestCaseWithTransport):

    def test_trailing_newlines(self):
        wt = self.make_branch_and_tree('.')
        b = make_commits_with_trailing_newlines(wt)
        sio = StringIO()
        lf = ShortLogFormatter(to_file=sio)
        show_log(b, lf)
        self.assertEquals(sio.getvalue(), """\
    3 Joe Foo\t2005-11-21
      single line with trailing newline

    2 Joe Foo\t2005-11-21
      multiline
      log
      message

    1 Joe Foo\t2005-11-21
      simple log message

""")


class TestLongLogFormatter(TestCaseWithTransport):

    def normalize_log(self,log):
        """Replaces the variable lines of logs with fixed lines"""
        committer = 'committer: Lorem Ipsum <test@example.com>'
        lines = log.splitlines(True)
        for idx,line in enumerate(lines):
            stripped_line = line.lstrip()
            indent = ' ' * (len(line) - len(stripped_line))
            if stripped_line.startswith('committer:'):
                lines[idx] = indent + committer + '\n'
            if stripped_line.startswith('timestamp:'):
                lines[idx] = indent + 'timestamp: Just now\n'
        return ''.join(lines)

    def test_verbose_log(self):
        """Verbose log includes changed files
        
        bug #4676
        """
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        self.build_tree(['a'])
        wt.add('a')
        # XXX: why does a longer nick show up?
        b.nick = 'test_verbose_log'
        wt.commit(message='add a', 
                  timestamp=1132711707, 
                  timezone=36000,
                  committer='Lorem Ipsum <test@example.com>')
        logfile = file('out.tmp', 'w+')
        formatter = LongLogFormatter(to_file=logfile)
        show_log(b, formatter, verbose=True)
        logfile.flush()
        logfile.seek(0)
        log_contents = logfile.read()
        self.assertEqualDiff(log_contents, '''\
------------------------------------------------------------
revno: 1
committer: Lorem Ipsum <test@example.com>
branch nick: test_verbose_log
timestamp: Wed 2005-11-23 12:08:27 +1000
message:
  add a
added:
  a
''')

    def test_merges_are_indented_by_level(self):
        wt = self.make_branch_and_tree('parent')
        wt.commit('first post')
        self.run_bzr('branch', 'parent', 'child')
        self.run_bzr('commit', '-m', 'branch 1', '--unchanged', 'child')
        self.run_bzr('branch', 'child', 'smallerchild')
        self.run_bzr('commit', '-m', 'branch 2', '--unchanged', 'smallerchild')
        os.chdir('child')
        self.run_bzr('merge', '../smallerchild')
        self.run_bzr('commit', '-m', 'merge branch 2')
        os.chdir('../parent')
        self.run_bzr('merge', '../child')
        wt.commit('merge branch 1')
        b = wt.branch
        sio = StringIO()
        lf = LongLogFormatter(to_file=sio)
        show_log(b, lf, verbose=True)
        log = self.normalize_log(sio.getvalue())
        self.assertEqualDiff("""\
------------------------------------------------------------
revno: 2
committer: Lorem Ipsum <test@example.com>
branch nick: parent
timestamp: Just now
message:
  merge branch 1
    ------------------------------------------------------------
    revno: 1.1.2
    committer: Lorem Ipsum <test@example.com>
    branch nick: child
    timestamp: Just now
    message:
      merge branch 2
        ------------------------------------------------------------
        revno: 1.1.1.1.1
        committer: Lorem Ipsum <test@example.com>
        branch nick: smallerchild
        timestamp: Just now
        message:
          branch 2
    ------------------------------------------------------------
    revno: 1.1.1
    committer: Lorem Ipsum <test@example.com>
    branch nick: child
    timestamp: Just now
    message:
      branch 1
------------------------------------------------------------
revno: 1
committer: Lorem Ipsum <test@example.com>
branch nick: parent
timestamp: Just now
message:
  first post
""", log)

    def test_verbose_merge_revisions_contain_deltas(self):
        wt = self.make_branch_and_tree('parent')
        self.build_tree(['parent/f1', 'parent/f2'])
        wt.add(['f1','f2'])
        wt.commit('first post')
        self.run_bzr('branch', 'parent', 'child')
        os.unlink('child/f1')
        print >> file('child/f2', 'wb'), 'hello'
        self.run_bzr('commit', '-m', 'removed f1 and modified f2', 'child')
        os.chdir('parent')
        self.run_bzr('merge', '../child')
        wt.commit('merge branch 1')
        b = wt.branch
        sio = StringIO()
        lf = LongLogFormatter(to_file=sio)
        show_log(b, lf, verbose=True)
        log = self.normalize_log(sio.getvalue())
        self.assertEqualDiff("""\
------------------------------------------------------------
revno: 2
committer: Lorem Ipsum <test@example.com>
branch nick: parent
timestamp: Just now
message:
  merge branch 1
removed:
  f1
modified:
  f2
    ------------------------------------------------------------
    revno: 1.1.1
    committer: Lorem Ipsum <test@example.com>
    branch nick: child
    timestamp: Just now
    message:
      removed f1 and modified f2
    removed:
      f1
    modified:
      f2
------------------------------------------------------------
revno: 1
committer: Lorem Ipsum <test@example.com>
branch nick: parent
timestamp: Just now
message:
  first post
added:
  f1
  f2
""", log)

    def test_trailing_newlines(self):
        wt = self.make_branch_and_tree('.')
        b = make_commits_with_trailing_newlines(wt)
        sio = StringIO()
        lf = LongLogFormatter(to_file=sio)
        show_log(b, lf)
        self.assertEqualDiff(sio.getvalue(), """\
------------------------------------------------------------
revno: 3
committer: Joe Foo <joe@foo.com>
branch nick: test
timestamp: Mon 2005-11-21 09:32:56 -0600
message:
  single line with trailing newline
------------------------------------------------------------
revno: 2
committer: Joe Foo <joe@foo.com>
branch nick: test
timestamp: Mon 2005-11-21 09:27:22 -0600
message:
  multiline
  log
  message
------------------------------------------------------------
revno: 1
committer: Joe Foo <joe@foo.com>
branch nick: test
timestamp: Mon 2005-11-21 09:24:15 -0600
message:
  simple log message
""")


class TestLineLogFormatter(TestCaseWithTransport):

    def test_line_log(self):
        """Line log should show revno
        
        bug #5162
        """
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        self.build_tree(['a'])
        wt.add('a')
        b.nick = 'test-line-log'
        wt.commit(message='add a', 
                  timestamp=1132711707, 
                  timezone=36000,
                  committer='Line-Log-Formatter Tester <test@line.log>')
        logfile = file('out.tmp', 'w+')
        formatter = LineLogFormatter(to_file=logfile)
        show_log(b, formatter)
        logfile.flush()
        logfile.seek(0)
        log_contents = logfile.read()
        self.assertEqualDiff(log_contents, '1: Line-Log-Formatte... 2005-11-23 add a\n')

    def test_trailing_newlines(self):
        wt = self.make_branch_and_tree('.')
        b = make_commits_with_trailing_newlines(wt)
        sio = StringIO()
        lf = LineLogFormatter(to_file=sio)
        show_log(b, lf)
        self.assertEqualDiff(sio.getvalue(), """\
3: Joe Foo 2005-11-21 single line with trailing newline
2: Joe Foo 2005-11-21 multiline
1: Joe Foo 2005-11-21 simple log message
""")


class TestGetViewRevisions(TestCaseWithTransport):

    def make_tree_with_commits(self):
        """Create a tree with well-known revision ids"""
        wt = self.make_branch_and_tree('tree1')
        wt.commit('commit one', rev_id='1')
        wt.commit('commit two', rev_id='2')
        wt.commit('commit three', rev_id='3')
        mainline_revs = [None, '1', '2', '3']
        rev_nos = {'1': 1, '2': 2, '3': 3}
        return mainline_revs, rev_nos, wt

    def make_tree_with_merges(self):
        """Create a tree with well-known revision ids and a merge"""
        mainline_revs, rev_nos, wt = self.make_tree_with_commits()
        tree2 = wt.bzrdir.sprout('tree2').open_workingtree()
        tree2.commit('four-a', rev_id='4a')
        wt.merge_from_branch(tree2.branch)
        wt.commit('four-b', rev_id='4b')
        mainline_revs.append('4b')
        rev_nos['4b'] = 4
        # 4a: 3.1.1
        return mainline_revs, rev_nos, wt

    def make_tree_with_many_merges(self):
        """Create a tree with well-known revision ids"""
        wt = self.make_branch_and_tree('tree1')
        wt.commit('commit one', rev_id='1')
        wt.commit('commit two', rev_id='2')
        tree3 = wt.bzrdir.sprout('tree3').open_workingtree()
        tree3.commit('commit three a', rev_id='3a')
        tree2 = wt.bzrdir.sprout('tree2').open_workingtree()
        tree2.merge_from_branch(tree3.branch)
        tree2.commit('commit three b', rev_id='3b')
        wt.merge_from_branch(tree2.branch)
        wt.commit('commit three c', rev_id='3c')
        tree2.commit('four-a', rev_id='4a')
        wt.merge_from_branch(tree2.branch)
        wt.commit('four-b', rev_id='4b')
        mainline_revs = [None, '1', '2', '3c', '4b']
        rev_nos = {'1':1, '2':2, '3c': 3, '4b':4}
        full_rev_nos_for_reference = {
            '1': '1',
            '2': '2',
            '3a': '2.2.1', #first commit tree 3
            '3b': '2.1.1', # first commit tree 2
            '3c': '3', #merges 3b to main
            '4a': '2.1.2', # second commit tree 2
            '4b': '4', # merges 4a to main
            }
        return mainline_revs, rev_nos, wt

    def test_get_view_revisions_forward(self):
        """Test the get_view_revisions method"""
        mainline_revs, rev_nos, wt = self.make_tree_with_commits()
        revisions = list(get_view_revisions(mainline_revs, rev_nos, wt.branch,
                                            'forward'))
        self.assertEqual([('1', '1', 0), ('2', '2', 0), ('3', '3', 0)],
            revisions)
        revisions2 = list(get_view_revisions(mainline_revs, rev_nos, wt.branch,
                                             'forward', include_merges=False))
        self.assertEqual(revisions, revisions2)

    def test_get_view_revisions_reverse(self):
        """Test the get_view_revisions with reverse"""
        mainline_revs, rev_nos, wt = self.make_tree_with_commits()
        revisions = list(get_view_revisions(mainline_revs, rev_nos, wt.branch,
                                            'reverse'))
        self.assertEqual([('3', '3', 0), ('2', '2', 0), ('1', '1', 0), ],
            revisions)
        revisions2 = list(get_view_revisions(mainline_revs, rev_nos, wt.branch,
                                             'reverse', include_merges=False))
        self.assertEqual(revisions, revisions2)

    def test_get_view_revisions_merge(self):
        """Test get_view_revisions when there are merges"""
        mainline_revs, rev_nos, wt = self.make_tree_with_merges()
        revisions = list(get_view_revisions(mainline_revs, rev_nos, wt.branch,
                                            'forward'))
        self.assertEqual([('1', '1', 0), ('2', '2', 0), ('3', '3', 0),
            ('4b', '4', 0), ('4a', '3.1.1', 1)],
            revisions)
        revisions = list(get_view_revisions(mainline_revs, rev_nos, wt.branch,
                                             'forward', include_merges=False))
        self.assertEqual([('1', '1', 0), ('2', '2', 0), ('3', '3', 0),
            ('4b', '4', 0)],
            revisions)

    def test_get_view_revisions_merge_reverse(self):
        """Test get_view_revisions in reverse when there are merges"""
        mainline_revs, rev_nos, wt = self.make_tree_with_merges()
        revisions = list(get_view_revisions(mainline_revs, rev_nos, wt.branch,
                                            'reverse'))
        self.assertEqual([('4b', '4', 0), ('4a', '3.1.1', 1),
            ('3', '3', 0), ('2', '2', 0), ('1', '1', 0)],
            revisions)
        revisions = list(get_view_revisions(mainline_revs, rev_nos, wt.branch,
                                             'reverse', include_merges=False))
        self.assertEqual([('4b', '4', 0), ('3', '3', 0), ('2', '2', 0),
            ('1', '1', 0)],
            revisions)

    def test_get_view_revisions_merge2(self):
        """Test get_view_revisions when there are merges"""
        mainline_revs, rev_nos, wt = self.make_tree_with_many_merges()
        revisions = list(get_view_revisions(mainline_revs, rev_nos, wt.branch,
                                            'forward'))
        expected = [('1', '1', 0), ('2', '2', 0), ('3c', '3', 0),
            ('3a', '2.2.1', 1), ('3b', '2.1.1', 1), ('4b', '4', 0),
            ('4a', '2.1.2', 1)]
        self.assertEqual(expected, revisions)
        revisions = list(get_view_revisions(mainline_revs, rev_nos, wt.branch,
                                             'forward', include_merges=False))
        self.assertEqual([('1', '1', 0), ('2', '2', 0), ('3c', '3', 0),
            ('4b', '4', 0)],
            revisions)


class TestGetRevisionsTouchingFileID(TestCaseWithTransport):

    def create_tree_with_single_merge(self):
        """Create a branch with a moderate layout.

        The revision graph looks like:

           A
           |\
           B C
           |/
           D

        In this graph, A introduced files f1 and f2 and f3.
        B modifies f1 and f3, and C modifies f2 and f3.
        D merges the changes from B and C and resolves the conflict for f3.
        """
        # TODO: jam 20070218 This seems like it could really be done
        #       with make_branch_and_memory_tree() if we could just
        #       create the content of those files.
        # TODO: jam 20070218 Another alternative is that we would really
        #       like to only create this tree 1 time for all tests that
        #       use it. Since 'log' only uses the tree in a readonly
        #       fashion, it seems a shame to regenerate an identical
        #       tree for each test.
        tree = self.make_branch_and_tree('tree')
        tree.lock_write()
        self.addCleanup(tree.unlock)

        self.build_tree_contents([('tree/f1', 'A\n'),
                                  ('tree/f2', 'A\n'),
                                  ('tree/f3', 'A\n'),
                                 ])
        tree.add(['f1', 'f2', 'f3'], ['f1-id', 'f2-id', 'f3-id'])
        tree.commit('A', rev_id='A')

        self.build_tree_contents([('tree/f2', 'A\nC\n'),
                                  ('tree/f3', 'A\nC\n'),
                                 ])
        tree.commit('C', rev_id='C')
        # Revert back to A to build the other history.
        tree.set_last_revision('A')
        tree.branch.set_last_revision_info(1, 'A')
        self.build_tree_contents([('tree/f1', 'A\nB\n'),
                                  ('tree/f2', 'A\n'),
                                  ('tree/f3', 'A\nB\n'),
                                 ])
        tree.commit('B', rev_id='B')
        tree.set_parent_ids(['B', 'C'])
        self.build_tree_contents([('tree/f1', 'A\nB\n'),
                                  ('tree/f2', 'A\nC\n'),
                                  ('tree/f3', 'A\nB\nC\n'),
                                 ])
        tree.commit('D', rev_id='D')

        # Switch to a read lock for this tree.
        # We still have addCleanup(unlock)
        tree.unlock()
        tree.lock_read()
        return tree

    def test_tree_with_single_merge(self):
        """Make sure the tree layout is correct."""
        tree = self.create_tree_with_single_merge()
        rev_A_tree = tree.branch.repository.revision_tree('A')
        rev_B_tree = tree.branch.repository.revision_tree('B')

        f1_changed = (u'f1', 'f1-id', 'file', True, False)
        f2_changed = (u'f2', 'f2-id', 'file', True, False)
        f3_changed = (u'f3', 'f3-id', 'file', True, False)

        delta = rev_B_tree.changes_from(rev_A_tree)
        self.assertEqual([f1_changed, f3_changed], delta.modified)
        self.assertEqual([], delta.renamed)
        self.assertEqual([], delta.added)
        self.assertEqual([], delta.removed)

        rev_C_tree = tree.branch.repository.revision_tree('C')
        delta = rev_C_tree.changes_from(rev_A_tree)
        self.assertEqual([f2_changed, f3_changed], delta.modified)
        self.assertEqual([], delta.renamed)
        self.assertEqual([], delta.added)
        self.assertEqual([], delta.removed)

        rev_D_tree = tree.branch.repository.revision_tree('D')
        delta = rev_D_tree.changes_from(rev_B_tree)
        self.assertEqual([f2_changed, f3_changed], delta.modified)
        self.assertEqual([], delta.renamed)
        self.assertEqual([], delta.added)
        self.assertEqual([], delta.removed)

        delta = rev_D_tree.changes_from(rev_C_tree)
        self.assertEqual([f1_changed, f3_changed], delta.modified)
        self.assertEqual([], delta.renamed)
        self.assertEqual([], delta.added)
        self.assertEqual([], delta.removed)

    def assertAllRevisionsForFileID(self, tree, file_id, revisions):
        """Make sure _get_revisions_touching_file_id returns the right values.

        Get the return value from _get_revisions_touching_file_id and make
        sure they are correct.
        """
        # The api for _get_revisions_touching_file_id is a little crazy,
        # So we do the setup here.
        mainline = tree.branch.revision_history()
        mainline.insert(0, None)
        revnos = dict((rev, idx+1) for idx, rev in enumerate(mainline))
        view_revs_iter = log.get_view_revisions(mainline, revnos, tree.branch,
                                                'reverse', True)
        actual_revs = log._get_revisions_touching_file_id(tree.branch, file_id,
                                                          mainline,
                                                          view_revs_iter)
        self.assertEqual(revisions, [r for r, revno, depth in actual_revs])

    def test_file_id_f1(self):
        tree = self.create_tree_with_single_merge()
        # f1 should be marked as modified by revisions A and B
        self.assertAllRevisionsForFileID(tree, 'f1-id', ['B', 'A'])

    def test_file_id_f2(self):
        tree = self.create_tree_with_single_merge()
        # f2 should be marked as modified by revisions A, C, and D
        # because D merged the changes from C.
        self.assertAllRevisionsForFileID(tree, 'f2-id', ['D', 'C', 'A'])

    def test_file_id_f3(self):
        tree = self.create_tree_with_single_merge()
        # f3 should be marked as modified by revisions A, B, C, and D
        self.assertAllRevisionsForFileID(tree, 'f2-id', ['D', 'C', 'A'])
