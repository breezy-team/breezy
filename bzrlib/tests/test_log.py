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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

import os
from cStringIO import StringIO

from bzrlib import (
    errors,
    log,
    registry,
    revision,
    revisionspec,
    tests,
    )


class TestCaseWithoutPropsHandler(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestCaseWithoutPropsHandler, self).setUp()
        # keep a reference to the "current" custom prop. handler registry
        self.properties_handler_registry = log.properties_handler_registry
        # Use a clean registry for log
        log.properties_handler_registry = registry.Registry()

        def restore():
            log.properties_handler_registry = self.properties_handler_registry
        self.addCleanup(restore)


class LogCatcher(log.LogFormatter):
    """Pull log messages into a list rather than displaying them.

    To simplify testing we save logged revisions here rather than actually
    formatting anything, so that we can precisely check the result without
    being dependent on the formatting.
    """

    supports_delta = True

    def __init__(self):
        super(LogCatcher, self).__init__(to_file=None)
        self.revisions = []

    def log_revision(self, revision):
        self.revisions.append(revision)


class TestShowLog(tests.TestCaseWithTransport):

    def checkDelta(self, delta, **kw):
        """Check the filenames touched by a delta are as expected.

        Caller only have to pass in the list of files for each part, all
        unspecified parts are considered empty (and checked as such).
        """
        for n in 'added', 'removed', 'renamed', 'modified', 'unchanged':
            # By default we expect an empty list
            expected = kw.get(n, [])
            # strip out only the path components
            got = [x[0] for x in getattr(delta, n)]
            self.assertEqual(expected, got)

    def assertInvalidRevisonNumber(self, br, start, end):
        lf = LogCatcher()
        self.assertRaises(errors.InvalidRevisionNumber,
                          log.show_log, br, lf,
                          start_revision=start, end_revision=end)

    def test_cur_revno(self):
        wt = self.make_branch_and_tree('.')
        b = wt.branch

        lf = LogCatcher()
        wt.commit('empty commit')
        log.show_log(b, lf, verbose=True, start_revision=1, end_revision=1)

        # Since there is a single revision in the branch all the combinations
        # below should fail.
        self.assertInvalidRevisonNumber(b, 2, 1)
        self.assertInvalidRevisonNumber(b, 1, 2)
        self.assertInvalidRevisonNumber(b, 0, 2)
        self.assertInvalidRevisonNumber(b, 1, 0)
        self.assertInvalidRevisonNumber(b, -1, 1)
        self.assertInvalidRevisonNumber(b, 1, -1)

    def test_empty_branch(self):
        wt = self.make_branch_and_tree('.')

        lf = LogCatcher()
        log.show_log(wt.branch, lf)
        # no entries yet
        self.assertEqual([], lf.revisions)

    def test_empty_commit(self):
        wt = self.make_branch_and_tree('.')

        wt.commit('empty commit')
        lf = LogCatcher()
        log.show_log(wt.branch, lf, verbose=True)
        revs = lf.revisions
        self.assertEqual(1, len(revs))
        self.assertEqual('1', revs[0].revno)
        self.assertEqual('empty commit', revs[0].rev.message)
        self.checkDelta(revs[0].delta)

    def test_simple_commit(self):
        wt = self.make_branch_and_tree('.')
        wt.commit('empty commit')
        self.build_tree(['hello'])
        wt.add('hello')
        wt.commit('add one file',
                  committer=u'\u013d\xf3r\xe9m \xcdp\u0161\xfam '
                            u'<test@example.com>')
        lf = LogCatcher()
        log.show_log(wt.branch, lf, verbose=True)
        self.assertEqual(2, len(lf.revisions))
        # first one is most recent
        log_entry = lf.revisions[0]
        self.assertEqual('2', log_entry.revno)
        self.assertEqual('add one file', log_entry.rev.message)
        self.checkDelta(log_entry.delta, added=['hello'])

    def test_commit_message_with_control_chars(self):
        wt = self.make_branch_and_tree('.')
        msg = u"All 8-bit chars: " +  ''.join([unichr(x) for x in range(256)])
        msg = msg.replace(u'\r', u'\n')
        wt.commit(msg)
        lf = LogCatcher()
        log.show_log(wt.branch, lf, verbose=True)
        committed_msg = lf.revisions[0].rev.message
        if wt.branch.repository._serializer.squashes_xml_invalid_characters:
            self.assertNotEqual(msg, committed_msg)
            self.assertTrue(len(committed_msg) > len(msg))
        else:
            self.assertEqual(msg, committed_msg)

    def test_commit_message_without_control_chars(self):
        wt = self.make_branch_and_tree('.')
        # escaped.  As ElementTree apparently does some kind of
        # newline conversion, neither LF (\x0A) nor CR (\x0D) are
        # included in the test commit message, even though they are
        # valid XML 1.0 characters.
        msg = "\x09" + ''.join([unichr(x) for x in range(0x20, 256)])
        wt.commit(msg)
        lf = LogCatcher()
        log.show_log(wt.branch, lf, verbose=True)
        committed_msg = lf.revisions[0].rev.message
        self.assertEqual(msg, committed_msg)

    def test_deltas_in_merge_revisions(self):
        """Check deltas created for both mainline and merge revisions"""
        wt = self.make_branch_and_tree('parent')
        self.build_tree(['parent/file1', 'parent/file2', 'parent/file3'])
        wt.add('file1')
        wt.add('file2')
        wt.commit(message='add file1 and file2')
        self.run_bzr('branch parent child')
        os.unlink('child/file1')
        file('child/file2', 'wb').write('hello\n')
        self.run_bzr(['commit', '-m', 'remove file1 and modify file2',
            'child'])
        os.chdir('parent')
        self.run_bzr('merge ../child')
        wt.commit('merge child branch')
        os.chdir('..')
        b = wt.branch
        lf = LogCatcher()
        lf.supports_merge_revisions = True
        log.show_log(b, lf, verbose=True)

        revs = lf.revisions
        self.assertEqual(3, len(revs))

        logentry = revs[0]
        self.assertEqual('2', logentry.revno)
        self.assertEqual('merge child branch', logentry.rev.message)
        self.checkDelta(logentry.delta, removed=['file1'], modified=['file2'])

        logentry = revs[1]
        self.assertEqual('1.1.1', logentry.revno)
        self.assertEqual('remove file1 and modify file2', logentry.rev.message)
        self.checkDelta(logentry.delta, removed=['file1'], modified=['file2'])

        logentry = revs[2]
        self.assertEqual('1', logentry.revno)
        self.assertEqual('add file1 and file2', logentry.rev.message)
        self.checkDelta(logentry.delta, added=['file1', 'file2'])


def make_commits_with_trailing_newlines(wt):
    """Helper method for LogFormatter tests"""
    b = wt.branch
    b.nick='test'
    open('a', 'wb').write('hello moto\n')
    wt.add('a')
    wt.commit('simple log message', rev_id='a1',
              timestamp=1132586655.459960938, timezone=-6*3600,
              committer='Joe Foo <joe@foo.com>')
    open('b', 'wb').write('goodbye\n')
    wt.add('b')
    wt.commit('multiline\nlog\nmessage\n', rev_id='a2',
              timestamp=1132586842.411175966, timezone=-6*3600,
              committer='Joe Foo <joe@foo.com>',
              authors=['Joe Bar <joe@bar.com>'])

    open('c', 'wb').write('just another manic monday\n')
    wt.add('c')
    wt.commit('single line with trailing newline\n', rev_id='a3',
              timestamp=1132587176.835228920, timezone=-6*3600,
              committer = 'Joe Foo <joe@foo.com>')
    return b


def normalize_log(log):
    """Replaces the variable lines of logs with fixed lines"""
    author = 'author: Dolor Sit <test@example.com>'
    committer = 'committer: Lorem Ipsum <test@example.com>'
    lines = log.splitlines(True)
    for idx,line in enumerate(lines):
        stripped_line = line.lstrip()
        indent = ' ' * (len(line) - len(stripped_line))
        if stripped_line.startswith('author:'):
            lines[idx] = indent + author + '\n'
        elif stripped_line.startswith('committer:'):
            lines[idx] = indent + committer + '\n'
        elif stripped_line.startswith('timestamp:'):
            lines[idx] = indent + 'timestamp: Just now\n'
    return ''.join(lines)


class TestShortLogFormatter(tests.TestCaseWithTransport):

    def test_trailing_newlines(self):
        wt = self.make_branch_and_tree('.')
        b = make_commits_with_trailing_newlines(wt)
        sio = self.make_utf8_encoded_stringio()
        lf = log.ShortLogFormatter(to_file=sio)
        log.show_log(b, lf)
        self.assertEqualDiff("""\
    3 Joe Foo\t2005-11-21
      single line with trailing newline

    2 Joe Bar\t2005-11-21
      multiline
      log
      message

    1 Joe Foo\t2005-11-21
      simple log message

""",
                             sio.getvalue())

    def _prepare_tree_with_merges(self, with_tags=False):
        wt = self.make_branch_and_memory_tree('.')
        wt.lock_write()
        self.addCleanup(wt.unlock)
        wt.add('')
        wt.commit('rev-1', rev_id='rev-1',
                  timestamp=1132586655, timezone=36000,
                  committer='Joe Foo <joe@foo.com>')
        wt.commit('rev-merged', rev_id='rev-2a',
                  timestamp=1132586700, timezone=36000,
                  committer='Joe Foo <joe@foo.com>')
        wt.set_parent_ids(['rev-1', 'rev-2a'])
        wt.branch.set_last_revision_info(1, 'rev-1')
        wt.commit('rev-2', rev_id='rev-2b',
                  timestamp=1132586800, timezone=36000,
                  committer='Joe Foo <joe@foo.com>')
        if with_tags:
            branch = wt.branch
            branch.tags.set_tag('v0.2', 'rev-2b')
            wt.commit('rev-3', rev_id='rev-3',
                      timestamp=1132586900, timezone=36000,
                      committer='Jane Foo <jane@foo.com>')
            branch.tags.set_tag('v1.0rc1', 'rev-3')
            branch.tags.set_tag('v1.0', 'rev-3')
        return wt

    def test_short_log_with_merges(self):
        wt = self._prepare_tree_with_merges()
        logfile = self.make_utf8_encoded_stringio()
        formatter = log.ShortLogFormatter(to_file=logfile)
        log.show_log(wt.branch, formatter)
        self.assertEqualDiff("""\
    2 Joe Foo\t2005-11-22 [merge]
      rev-2

    1 Joe Foo\t2005-11-22
      rev-1

""",
                             logfile.getvalue())

    def test_short_log_with_merges_and_advice(self):
        wt = self._prepare_tree_with_merges()
        logfile = self.make_utf8_encoded_stringio()
        formatter = log.ShortLogFormatter(to_file=logfile,
            show_advice=True)
        log.show_log(wt.branch, formatter)
        self.assertEqualDiff("""\
    2 Joe Foo\t2005-11-22 [merge]
      rev-2

    1 Joe Foo\t2005-11-22
      rev-1

Use --include-merges or -n0 to see merged revisions.
""",
                             logfile.getvalue())

    def test_short_log_with_merges_and_range(self):
        wt = self.make_branch_and_memory_tree('.')
        wt.lock_write()
        self.addCleanup(wt.unlock)
        wt.add('')
        wt.commit('rev-1', rev_id='rev-1',
                  timestamp=1132586655, timezone=36000,
                  committer='Joe Foo <joe@foo.com>')
        wt.commit('rev-merged', rev_id='rev-2a',
                  timestamp=1132586700, timezone=36000,
                  committer='Joe Foo <joe@foo.com>')
        wt.branch.set_last_revision_info(1, 'rev-1')
        wt.set_parent_ids(['rev-1', 'rev-2a'])
        wt.commit('rev-2b', rev_id='rev-2b',
                  timestamp=1132586800, timezone=36000,
                  committer='Joe Foo <joe@foo.com>')
        wt.commit('rev-3a', rev_id='rev-3a',
                  timestamp=1132586800, timezone=36000,
                  committer='Joe Foo <joe@foo.com>')
        wt.branch.set_last_revision_info(2, 'rev-2b')
        wt.set_parent_ids(['rev-2b', 'rev-3a'])
        wt.commit('rev-3b', rev_id='rev-3b',
                  timestamp=1132586800, timezone=36000,
                  committer='Joe Foo <joe@foo.com>')
        logfile = self.make_utf8_encoded_stringio()
        formatter = log.ShortLogFormatter(to_file=logfile)
        log.show_log(wt.branch, formatter,
            start_revision=2, end_revision=3)
        self.assertEqualDiff("""\
    3 Joe Foo\t2005-11-22 [merge]
      rev-3b

    2 Joe Foo\t2005-11-22 [merge]
      rev-2b

""",
                             logfile.getvalue())

    def test_short_log_with_tags(self):
        wt = self._prepare_tree_with_merges(with_tags=True)
        logfile = self.make_utf8_encoded_stringio()
        formatter = log.ShortLogFormatter(to_file=logfile)
        log.show_log(wt.branch, formatter)
        self.assertEqualDiff("""\
    3 Jane Foo\t2005-11-22 {v1.0, v1.0rc1}
      rev-3

    2 Joe Foo\t2005-11-22 {v0.2} [merge]
      rev-2

    1 Joe Foo\t2005-11-22
      rev-1

""",
                             logfile.getvalue())

    def test_short_log_single_merge_revision(self):
        wt = self.make_branch_and_memory_tree('.')
        wt.lock_write()
        self.addCleanup(wt.unlock)
        wt.add('')
        wt.commit('rev-1', rev_id='rev-1',
                  timestamp=1132586655, timezone=36000,
                  committer='Joe Foo <joe@foo.com>')
        wt.commit('rev-merged', rev_id='rev-2a',
                  timestamp=1132586700, timezone=36000,
                  committer='Joe Foo <joe@foo.com>')
        wt.set_parent_ids(['rev-1', 'rev-2a'])
        wt.branch.set_last_revision_info(1, 'rev-1')
        wt.commit('rev-2', rev_id='rev-2b',
                  timestamp=1132586800, timezone=36000,
                  committer='Joe Foo <joe@foo.com>')
        logfile = self.make_utf8_encoded_stringio()
        formatter = log.ShortLogFormatter(to_file=logfile)
        revspec = revisionspec.RevisionSpec.from_string('1.1.1')
        wtb = wt.branch
        rev = revspec.in_history(wtb)
        log.show_log(wtb, formatter, start_revision=rev, end_revision=rev)
        self.assertEqualDiff("""\
      1.1.1 Joe Foo\t2005-11-22
            rev-merged

""",
                             logfile.getvalue())


class TestShortLogFormatterWithMergeRevisions(tests.TestCaseWithTransport):

    def test_short_merge_revs_log_with_merges(self):
        wt = self.make_branch_and_memory_tree('.')
        wt.lock_write()
        self.addCleanup(wt.unlock)
        wt.add('')
        wt.commit('rev-1', rev_id='rev-1',
                  timestamp=1132586655, timezone=36000,
                  committer='Joe Foo <joe@foo.com>')
        wt.commit('rev-merged', rev_id='rev-2a',
                  timestamp=1132586700, timezone=36000,
                  committer='Joe Foo <joe@foo.com>')
        wt.set_parent_ids(['rev-1', 'rev-2a'])
        wt.branch.set_last_revision_info(1, 'rev-1')
        wt.commit('rev-2', rev_id='rev-2b',
                  timestamp=1132586800, timezone=36000,
                  committer='Joe Foo <joe@foo.com>')
        logfile = self.make_utf8_encoded_stringio()
        formatter = log.ShortLogFormatter(to_file=logfile, levels=0)
        log.show_log(wt.branch, formatter)
        # Note that the 1.1.1 indenting is in fact correct given that
        # the revision numbers are right justified within 5 characters
        # for mainline revnos and 9 characters for dotted revnos.
        self.assertEqualDiff("""\
    2 Joe Foo\t2005-11-22 [merge]
      rev-2

          1.1.1 Joe Foo\t2005-11-22
                rev-merged

    1 Joe Foo\t2005-11-22
      rev-1

""",
                             logfile.getvalue())

    def test_short_merge_revs_log_single_merge_revision(self):
        wt = self.make_branch_and_memory_tree('.')
        wt.lock_write()
        self.addCleanup(wt.unlock)
        wt.add('')
        wt.commit('rev-1', rev_id='rev-1',
                  timestamp=1132586655, timezone=36000,
                  committer='Joe Foo <joe@foo.com>')
        wt.commit('rev-merged', rev_id='rev-2a',
                  timestamp=1132586700, timezone=36000,
                  committer='Joe Foo <joe@foo.com>')
        wt.set_parent_ids(['rev-1', 'rev-2a'])
        wt.branch.set_last_revision_info(1, 'rev-1')
        wt.commit('rev-2', rev_id='rev-2b',
                  timestamp=1132586800, timezone=36000,
                  committer='Joe Foo <joe@foo.com>')
        logfile = self.make_utf8_encoded_stringio()
        formatter = log.ShortLogFormatter(to_file=logfile, levels=0)
        revspec = revisionspec.RevisionSpec.from_string('1.1.1')
        wtb = wt.branch
        rev = revspec.in_history(wtb)
        log.show_log(wtb, formatter, start_revision=rev, end_revision=rev)
        self.assertEqualDiff("""\
      1.1.1 Joe Foo\t2005-11-22
            rev-merged

""",
                             logfile.getvalue())


class TestLongLogFormatter(TestCaseWithoutPropsHandler):

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
        formatter = log.LongLogFormatter(to_file=logfile)
        log.show_log(b, formatter, verbose=True)
        logfile.flush()
        logfile.seek(0)
        log_contents = logfile.read()
        self.assertEqualDiff('''\
------------------------------------------------------------
revno: 1
committer: Lorem Ipsum <test@example.com>
branch nick: test_verbose_log
timestamp: Wed 2005-11-23 12:08:27 +1000
message:
  add a
added:
  a
''',
                             log_contents)

    def test_merges_are_indented_by_level(self):
        wt = self.make_branch_and_tree('parent')
        wt.commit('first post')
        self.run_bzr('branch parent child')
        self.run_bzr(['commit', '-m', 'branch 1', '--unchanged', 'child'])
        self.run_bzr('branch child smallerchild')
        self.run_bzr(['commit', '-m', 'branch 2', '--unchanged',
            'smallerchild'])
        os.chdir('child')
        self.run_bzr('merge ../smallerchild')
        self.run_bzr(['commit', '-m', 'merge branch 2'])
        os.chdir('../parent')
        self.run_bzr('merge ../child')
        wt.commit('merge branch 1')
        b = wt.branch
        sio = self.make_utf8_encoded_stringio()
        lf = log.LongLogFormatter(to_file=sio, levels=0)
        log.show_log(b, lf, verbose=True)
        the_log = normalize_log(sio.getvalue())
        self.assertEqualDiff("""\
------------------------------------------------------------
revno: 2 [merge]
committer: Lorem Ipsum <test@example.com>
branch nick: parent
timestamp: Just now
message:
  merge branch 1
    ------------------------------------------------------------
    revno: 1.1.2 [merge]
    committer: Lorem Ipsum <test@example.com>
    branch nick: child
    timestamp: Just now
    message:
      merge branch 2
        ------------------------------------------------------------
        revno: 1.2.1
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
""",
                             the_log)

    def test_verbose_merge_revisions_contain_deltas(self):
        wt = self.make_branch_and_tree('parent')
        self.build_tree(['parent/f1', 'parent/f2'])
        wt.add(['f1','f2'])
        wt.commit('first post')
        self.run_bzr('branch parent child')
        os.unlink('child/f1')
        file('child/f2', 'wb').write('hello\n')
        self.run_bzr(['commit', '-m', 'removed f1 and modified f2',
            'child'])
        os.chdir('parent')
        self.run_bzr('merge ../child')
        wt.commit('merge branch 1')
        b = wt.branch
        sio = self.make_utf8_encoded_stringio()
        lf = log.LongLogFormatter(to_file=sio, levels=0)
        log.show_log(b, lf, verbose=True)
        the_log = normalize_log(sio.getvalue())
        self.assertEqualDiff("""\
------------------------------------------------------------
revno: 2 [merge]
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
""",
                             the_log)

    def test_trailing_newlines(self):
        wt = self.make_branch_and_tree('.')
        b = make_commits_with_trailing_newlines(wt)
        sio = self.make_utf8_encoded_stringio()
        lf = log.LongLogFormatter(to_file=sio)
        log.show_log(b, lf)
        self.assertEqualDiff("""\
------------------------------------------------------------
revno: 3
committer: Joe Foo <joe@foo.com>
branch nick: test
timestamp: Mon 2005-11-21 09:32:56 -0600
message:
  single line with trailing newline
------------------------------------------------------------
revno: 2
author: Joe Bar <joe@bar.com>
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
""",
                             sio.getvalue())

    def test_author_in_log(self):
        """Log includes the author name if it's set in
        the revision properties
        """
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        self.build_tree(['a'])
        wt.add('a')
        b.nick = 'test_author_log'
        wt.commit(message='add a',
                  timestamp=1132711707,
                  timezone=36000,
                  committer='Lorem Ipsum <test@example.com>',
                  authors=['John Doe <jdoe@example.com>',
                           'Jane Rey <jrey@example.com>'])
        sio = StringIO()
        formatter = log.LongLogFormatter(to_file=sio)
        log.show_log(b, formatter)
        self.assertEqualDiff('''\
------------------------------------------------------------
revno: 1
author: John Doe <jdoe@example.com>, Jane Rey <jrey@example.com>
committer: Lorem Ipsum <test@example.com>
branch nick: test_author_log
timestamp: Wed 2005-11-23 12:08:27 +1000
message:
  add a
''',
                             sio.getvalue())

    def test_properties_in_log(self):
        """Log includes the custom properties returned by the registered
        handlers.
        """
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        self.build_tree(['a'])
        wt.add('a')
        b.nick = 'test_properties_in_log'
        wt.commit(message='add a',
                  timestamp=1132711707,
                  timezone=36000,
                  committer='Lorem Ipsum <test@example.com>',
                  authors=['John Doe <jdoe@example.com>'])
        sio = StringIO()
        formatter = log.LongLogFormatter(to_file=sio)
        try:
            def trivial_custom_prop_handler(revision):
                return {'test_prop':'test_value'}

            log.properties_handler_registry.register(
                'trivial_custom_prop_handler',
                trivial_custom_prop_handler)
            log.show_log(b, formatter)
        finally:
            log.properties_handler_registry.remove(
                'trivial_custom_prop_handler')
            self.assertEqualDiff('''\
------------------------------------------------------------
revno: 1
test_prop: test_value
author: John Doe <jdoe@example.com>
committer: Lorem Ipsum <test@example.com>
branch nick: test_properties_in_log
timestamp: Wed 2005-11-23 12:08:27 +1000
message:
  add a
''',
                                 sio.getvalue())

    def test_properties_in_short_log(self):
        """Log includes the custom properties returned by the registered
        handlers.
        """
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        self.build_tree(['a'])
        wt.add('a')
        b.nick = 'test_properties_in_short_log'
        wt.commit(message='add a',
                  timestamp=1132711707,
                  timezone=36000,
                  committer='Lorem Ipsum <test@example.com>',
                  authors=['John Doe <jdoe@example.com>'])
        sio = StringIO()
        formatter = log.ShortLogFormatter(to_file=sio)
        try:
            def trivial_custom_prop_handler(revision):
                return {'test_prop':'test_value'}

            log.properties_handler_registry.register(
                'trivial_custom_prop_handler',
                trivial_custom_prop_handler)
            log.show_log(b, formatter)
        finally:
            log.properties_handler_registry.remove(
                'trivial_custom_prop_handler')
            self.assertEqualDiff('''\
    1 John Doe\t2005-11-23
      test_prop: test_value
      add a

''',
                                 sio.getvalue())

    def test_error_in_properties_handler(self):
        """Log includes the custom properties returned by the registered
        handlers.
        """
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        self.build_tree(['a'])
        wt.add('a')
        b.nick = 'test_author_log'
        wt.commit(message='add a',
                  timestamp=1132711707,
                  timezone=36000,
                  committer='Lorem Ipsum <test@example.com>',
                  authors=['John Doe <jdoe@example.com>'],
                  revprops={'first_prop':'first_value'})
        sio = StringIO()
        formatter = log.LongLogFormatter(to_file=sio)
        try:
            def trivial_custom_prop_handler(revision):
                raise StandardError("a test error")

            log.properties_handler_registry.register(
                'trivial_custom_prop_handler',
                trivial_custom_prop_handler)
            self.assertRaises(StandardError, log.show_log, b, formatter,)
        finally:
            log.properties_handler_registry.remove(
                'trivial_custom_prop_handler')

    def test_properties_handler_bad_argument(self):
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        self.build_tree(['a'])
        wt.add('a')
        b.nick = 'test_author_log'
        wt.commit(message='add a',
                  timestamp=1132711707,
                  timezone=36000,
                  committer='Lorem Ipsum <test@example.com>',
                  authors=['John Doe <jdoe@example.com>'],
                  revprops={'a_prop':'test_value'})
        sio = StringIO()
        formatter = log.LongLogFormatter(to_file=sio)
        try:
            def bad_argument_prop_handler(revision):
                return {'custom_prop_name':revision.properties['a_prop']}

            log.properties_handler_registry.register(
                'bad_argument_prop_handler',
                bad_argument_prop_handler)

            self.assertRaises(AttributeError, formatter.show_properties,
                              'a revision', '')

            revision = b.repository.get_revision(b.last_revision())
            formatter.show_properties(revision, '')
            self.assertEqualDiff('''custom_prop_name: test_value\n''',
                                 sio.getvalue())
        finally:
            log.properties_handler_registry.remove(
                'bad_argument_prop_handler')


class TestLongLogFormatterWithoutMergeRevisions(TestCaseWithoutPropsHandler):

    def test_long_verbose_log(self):
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
        formatter = log.LongLogFormatter(to_file=logfile, levels=1)
        log.show_log(b, formatter, verbose=True)
        logfile.flush()
        logfile.seek(0)
        log_contents = logfile.read()
        self.assertEqualDiff('''\
------------------------------------------------------------
revno: 1
committer: Lorem Ipsum <test@example.com>
branch nick: test_verbose_log
timestamp: Wed 2005-11-23 12:08:27 +1000
message:
  add a
added:
  a
''',
                             log_contents)

    def test_long_verbose_contain_deltas(self):
        wt = self.make_branch_and_tree('parent')
        self.build_tree(['parent/f1', 'parent/f2'])
        wt.add(['f1','f2'])
        wt.commit('first post')
        self.run_bzr('branch parent child')
        os.unlink('child/f1')
        file('child/f2', 'wb').write('hello\n')
        self.run_bzr(['commit', '-m', 'removed f1 and modified f2',
            'child'])
        os.chdir('parent')
        self.run_bzr('merge ../child')
        wt.commit('merge branch 1')
        b = wt.branch
        sio = self.make_utf8_encoded_stringio()
        lf = log.LongLogFormatter(to_file=sio, levels=1)
        log.show_log(b, lf, verbose=True)
        the_log = normalize_log(sio.getvalue())
        self.assertEqualDiff("""\
------------------------------------------------------------
revno: 2 [merge]
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
revno: 1
committer: Lorem Ipsum <test@example.com>
branch nick: parent
timestamp: Just now
message:
  first post
added:
  f1
  f2
""",
                             the_log)

    def test_long_trailing_newlines(self):
        wt = self.make_branch_and_tree('.')
        b = make_commits_with_trailing_newlines(wt)
        sio = self.make_utf8_encoded_stringio()
        lf = log.LongLogFormatter(to_file=sio, levels=1)
        log.show_log(b, lf)
        self.assertEqualDiff("""\
------------------------------------------------------------
revno: 3
committer: Joe Foo <joe@foo.com>
branch nick: test
timestamp: Mon 2005-11-21 09:32:56 -0600
message:
  single line with trailing newline
------------------------------------------------------------
revno: 2
author: Joe Bar <joe@bar.com>
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
""",
                             sio.getvalue())

    def test_long_author_in_log(self):
        """Log includes the author name if it's set in
        the revision properties
        """
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        self.build_tree(['a'])
        wt.add('a')
        b.nick = 'test_author_log'
        wt.commit(message='add a',
                  timestamp=1132711707,
                  timezone=36000,
                  committer='Lorem Ipsum <test@example.com>',
                  authors=['John Doe <jdoe@example.com>'])
        sio = StringIO()
        formatter = log.LongLogFormatter(to_file=sio, levels=1)
        log.show_log(b, formatter)
        self.assertEqualDiff('''\
------------------------------------------------------------
revno: 1
author: John Doe <jdoe@example.com>
committer: Lorem Ipsum <test@example.com>
branch nick: test_author_log
timestamp: Wed 2005-11-23 12:08:27 +1000
message:
  add a
''',
                             sio.getvalue())

    def test_long_properties_in_log(self):
        """Log includes the custom properties returned by the registered
        handlers.
        """
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        self.build_tree(['a'])
        wt.add('a')
        b.nick = 'test_properties_in_log'
        wt.commit(message='add a',
                  timestamp=1132711707,
                  timezone=36000,
                  committer='Lorem Ipsum <test@example.com>',
                  authors=['John Doe <jdoe@example.com>'])
        sio = StringIO()
        formatter = log.LongLogFormatter(to_file=sio, levels=1)
        try:
            def trivial_custom_prop_handler(revision):
                return {'test_prop':'test_value'}

            log.properties_handler_registry.register(
                'trivial_custom_prop_handler',
                trivial_custom_prop_handler)
            log.show_log(b, formatter)
        finally:
            log.properties_handler_registry.remove(
                'trivial_custom_prop_handler')
            self.assertEqualDiff('''\
------------------------------------------------------------
revno: 1
test_prop: test_value
author: John Doe <jdoe@example.com>
committer: Lorem Ipsum <test@example.com>
branch nick: test_properties_in_log
timestamp: Wed 2005-11-23 12:08:27 +1000
message:
  add a
''',
                                 sio.getvalue())


class TestLineLogFormatter(tests.TestCaseWithTransport):

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
        formatter = log.LineLogFormatter(to_file=logfile)
        log.show_log(b, formatter)
        logfile.flush()
        logfile.seek(0)
        log_contents = logfile.read()
        self.assertEqualDiff('1: Line-Log-Formatte... 2005-11-23 add a\n',
                             log_contents)

    def test_trailing_newlines(self):
        wt = self.make_branch_and_tree('.')
        b = make_commits_with_trailing_newlines(wt)
        sio = self.make_utf8_encoded_stringio()
        lf = log.LineLogFormatter(to_file=sio)
        log.show_log(b, lf)
        self.assertEqualDiff("""\
3: Joe Foo 2005-11-21 single line with trailing newline
2: Joe Bar 2005-11-21 multiline
1: Joe Foo 2005-11-21 simple log message
""",
                             sio.getvalue())

    def _prepare_tree_with_merges(self, with_tags=False):
        wt = self.make_branch_and_memory_tree('.')
        wt.lock_write()
        self.addCleanup(wt.unlock)
        wt.add('')
        wt.commit('rev-1', rev_id='rev-1',
                  timestamp=1132586655, timezone=36000,
                  committer='Joe Foo <joe@foo.com>')
        wt.commit('rev-merged', rev_id='rev-2a',
                  timestamp=1132586700, timezone=36000,
                  committer='Joe Foo <joe@foo.com>')
        wt.set_parent_ids(['rev-1', 'rev-2a'])
        wt.branch.set_last_revision_info(1, 'rev-1')
        wt.commit('rev-2', rev_id='rev-2b',
                  timestamp=1132586800, timezone=36000,
                  committer='Joe Foo <joe@foo.com>')
        if with_tags:
            branch = wt.branch
            branch.tags.set_tag('v0.2', 'rev-2b')
            wt.commit('rev-3', rev_id='rev-3',
                      timestamp=1132586900, timezone=36000,
                      committer='Jane Foo <jane@foo.com>')
            branch.tags.set_tag('v1.0rc1', 'rev-3')
            branch.tags.set_tag('v1.0', 'rev-3')
        return wt

    def test_line_log_single_merge_revision(self):
        wt = self._prepare_tree_with_merges()
        logfile = self.make_utf8_encoded_stringio()
        formatter = log.LineLogFormatter(to_file=logfile)
        revspec = revisionspec.RevisionSpec.from_string('1.1.1')
        wtb = wt.branch
        rev = revspec.in_history(wtb)
        log.show_log(wtb, formatter, start_revision=rev, end_revision=rev)
        self.assertEqualDiff("""\
1.1.1: Joe Foo 2005-11-22 rev-merged
""",
                             logfile.getvalue())

    def test_line_log_with_tags(self):
        wt = self._prepare_tree_with_merges(with_tags=True)
        logfile = self.make_utf8_encoded_stringio()
        formatter = log.LineLogFormatter(to_file=logfile)
        log.show_log(wt.branch, formatter)
        self.assertEqualDiff("""\
3: Jane Foo 2005-11-22 {v1.0, v1.0rc1} rev-3
2: Joe Foo 2005-11-22 [merge] {v0.2} rev-2
1: Joe Foo 2005-11-22 rev-1
""",
                             logfile.getvalue())

class TestLineLogFormatterWithMergeRevisions(tests.TestCaseWithTransport):

    def test_line_merge_revs_log(self):
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
        formatter = log.LineLogFormatter(to_file=logfile, levels=0)
        log.show_log(b, formatter)
        logfile.flush()
        logfile.seek(0)
        log_contents = logfile.read()
        self.assertEqualDiff('1: Line-Log-Formatte... 2005-11-23 add a\n',
                             log_contents)

    def test_line_merge_revs_log_single_merge_revision(self):
        wt = self.make_branch_and_memory_tree('.')
        wt.lock_write()
        self.addCleanup(wt.unlock)
        wt.add('')
        wt.commit('rev-1', rev_id='rev-1',
                  timestamp=1132586655, timezone=36000,
                  committer='Joe Foo <joe@foo.com>')
        wt.commit('rev-merged', rev_id='rev-2a',
                  timestamp=1132586700, timezone=36000,
                  committer='Joe Foo <joe@foo.com>')
        wt.set_parent_ids(['rev-1', 'rev-2a'])
        wt.branch.set_last_revision_info(1, 'rev-1')
        wt.commit('rev-2', rev_id='rev-2b',
                  timestamp=1132586800, timezone=36000,
                  committer='Joe Foo <joe@foo.com>')
        logfile = self.make_utf8_encoded_stringio()
        formatter = log.LineLogFormatter(to_file=logfile, levels=0)
        revspec = revisionspec.RevisionSpec.from_string('1.1.1')
        wtb = wt.branch
        rev = revspec.in_history(wtb)
        log.show_log(wtb, formatter, start_revision=rev, end_revision=rev)
        self.assertEqualDiff("""\
1.1.1: Joe Foo 2005-11-22 rev-merged
""",
                             logfile.getvalue())

    def test_line_merge_revs_log_with_merges(self):
        wt = self.make_branch_and_memory_tree('.')
        wt.lock_write()
        self.addCleanup(wt.unlock)
        wt.add('')
        wt.commit('rev-1', rev_id='rev-1',
                  timestamp=1132586655, timezone=36000,
                  committer='Joe Foo <joe@foo.com>')
        wt.commit('rev-merged', rev_id='rev-2a',
                  timestamp=1132586700, timezone=36000,
                  committer='Joe Foo <joe@foo.com>')
        wt.set_parent_ids(['rev-1', 'rev-2a'])
        wt.branch.set_last_revision_info(1, 'rev-1')
        wt.commit('rev-2', rev_id='rev-2b',
                  timestamp=1132586800, timezone=36000,
                  committer='Joe Foo <joe@foo.com>')
        logfile = self.make_utf8_encoded_stringio()
        formatter = log.LineLogFormatter(to_file=logfile, levels=0)
        log.show_log(wt.branch, formatter)
        self.assertEqualDiff("""\
2: Joe Foo 2005-11-22 [merge] rev-2
  1.1.1: Joe Foo 2005-11-22 rev-merged
1: Joe Foo 2005-11-22 rev-1
""",
                             logfile.getvalue())

class TestGetViewRevisions(tests.TestCaseWithTransport):

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

    def make_branch_with_many_merges(self):
        """Create a tree with well-known revision ids"""
        builder = self.make_branch_builder('tree1')
        builder.start_series()
        builder.build_snapshot('1', None, [
            ('add', ('', 'TREE_ROOT', 'directory', '')),
            ('add', ('f', 'f-id', 'file', '1\n'))])
        builder.build_snapshot('2', ['1'], [])
        builder.build_snapshot('3a', ['2'], [
            ('modify', ('f-id', '1\n2\n3a\n'))])
        builder.build_snapshot('3b', ['2', '3a'], [
            ('modify', ('f-id', '1\n2\n3a\n'))])
        builder.build_snapshot('3c', ['2', '3b'], [
            ('modify', ('f-id', '1\n2\n3a\n'))])
        builder.build_snapshot('4a', ['3b'], [])
        builder.build_snapshot('4b', ['3c', '4a'], [])
        builder.finish_series()

        # 1
        # |
        # 2-.
        # |\ \
        # | | 3a
        # | |/
        # | 3b
        # |/|
        # 3c4a
        # |/
        # 4b

        mainline_revs = [None, '1', '2', '3c', '4b']
        rev_nos = {'1':1, '2':2, '3c': 3, '4b':4}
        full_rev_nos_for_reference = {
            '1': '1',
            '2': '2',
            '3a': '2.1.1', #first commit tree 3
            '3b': '2.2.1', # first commit tree 2
            '3c': '3', #merges 3b to main
            '4a': '2.2.2', # second commit tree 2
            '4b': '4', # merges 4a to main
            }
        return mainline_revs, rev_nos, builder.get_branch()

    def test_get_view_revisions_forward(self):
        """Test the get_view_revisions method"""
        mainline_revs, rev_nos, wt = self.make_tree_with_commits()
        wt.lock_read()
        self.addCleanup(wt.unlock)
        revisions = list(log.get_view_revisions(
                mainline_revs, rev_nos, wt.branch, 'forward'))
        self.assertEqual([('1', '1', 0), ('2', '2', 0), ('3', '3', 0)],
                         revisions)
        revisions2 = list(log.get_view_revisions(
                mainline_revs, rev_nos, wt.branch, 'forward',
                include_merges=False))
        self.assertEqual(revisions, revisions2)

    def test_get_view_revisions_reverse(self):
        """Test the get_view_revisions with reverse"""
        mainline_revs, rev_nos, wt = self.make_tree_with_commits()
        wt.lock_read()
        self.addCleanup(wt.unlock)
        revisions = list(log.get_view_revisions(
                mainline_revs, rev_nos, wt.branch, 'reverse'))
        self.assertEqual([('3', '3', 0), ('2', '2', 0), ('1', '1', 0), ],
                         revisions)
        revisions2 = list(log.get_view_revisions(
                mainline_revs, rev_nos, wt.branch, 'reverse',
                include_merges=False))
        self.assertEqual(revisions, revisions2)

    def test_get_view_revisions_merge(self):
        """Test get_view_revisions when there are merges"""
        mainline_revs, rev_nos, wt = self.make_tree_with_merges()
        wt.lock_read()
        self.addCleanup(wt.unlock)
        revisions = list(log.get_view_revisions(
                mainline_revs, rev_nos, wt.branch, 'forward'))
        self.assertEqual([('1', '1', 0), ('2', '2', 0), ('3', '3', 0),
                          ('4b', '4', 0), ('4a', '3.1.1', 1)],
                         revisions)
        revisions = list(log.get_view_revisions(
                mainline_revs, rev_nos, wt.branch, 'forward',
                include_merges=False))
        self.assertEqual([('1', '1', 0), ('2', '2', 0), ('3', '3', 0),
                          ('4b', '4', 0)],
                         revisions)

    def test_get_view_revisions_merge_reverse(self):
        """Test get_view_revisions in reverse when there are merges"""
        mainline_revs, rev_nos, wt = self.make_tree_with_merges()
        wt.lock_read()
        self.addCleanup(wt.unlock)
        revisions = list(log.get_view_revisions(
                mainline_revs, rev_nos, wt.branch, 'reverse'))
        self.assertEqual([('4b', '4', 0), ('4a', '3.1.1', 1),
                          ('3', '3', 0), ('2', '2', 0), ('1', '1', 0)],
                         revisions)
        revisions = list(log.get_view_revisions(
                mainline_revs, rev_nos, wt.branch, 'reverse',
                include_merges=False))
        self.assertEqual([('4b', '4', 0), ('3', '3', 0), ('2', '2', 0),
                          ('1', '1', 0)],
                         revisions)

    def test_get_view_revisions_merge2(self):
        """Test get_view_revisions when there are merges"""
        mainline_revs, rev_nos, b = self.make_branch_with_many_merges()
        b.lock_read()
        self.addCleanup(b.unlock)
        revisions = list(log.get_view_revisions(
                mainline_revs, rev_nos, b, 'forward'))
        expected = [('1', '1', 0), ('2', '2', 0), ('3c', '3', 0),
                    ('3b', '2.2.1', 1), ('3a', '2.1.1', 2), ('4b', '4', 0),
                    ('4a', '2.2.2', 1)]
        self.assertEqual(expected, revisions)
        revisions = list(log.get_view_revisions(
                mainline_revs, rev_nos, b, 'forward',
                include_merges=False))
        self.assertEqual([('1', '1', 0), ('2', '2', 0), ('3c', '3', 0),
                          ('4b', '4', 0)],
                         revisions)


    def test_file_id_for_range(self):
        mainline_revs, rev_nos, b = self.make_branch_with_many_merges()
        b.lock_read()
        self.addCleanup(b.unlock)

        def rev_from_rev_id(revid, branch):
            revspec = revisionspec.RevisionSpec.from_string('revid:%s' % revid)
            return revspec.in_history(branch)

        def view_revs(start_rev, end_rev, file_id, direction):
            revs = log.calculate_view_revisions(
                b,
                start_rev, # start_revision
                end_rev, # end_revision
                direction, # direction
                file_id, # specific_fileid
                True, # generate_merge_revisions
                )
            return revs

        rev_3a = rev_from_rev_id('3a', b)
        rev_4b = rev_from_rev_id('4b', b)
        self.assertEqual([('3c', '3', 0), ('3b', '2.2.1', 1), ('3a', '2.1.1', 2)],
                          view_revs(rev_3a, rev_4b, 'f-id', 'reverse'))
        # Note: 3c still appears before 3a here because of depth-based sorting
        self.assertEqual([('3c', '3', 0), ('3b', '2.2.1', 1), ('3a', '2.1.1', 2)],
                          view_revs(rev_3a, rev_4b, 'f-id', 'forward'))


class TestGetRevisionsTouchingFileID(tests.TestCaseWithTransport):

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
        # We still have an addCleanup(tree.unlock) pending
        tree.unlock()
        tree.lock_read()
        return tree

    def check_delta(self, delta, **kw):
        """Check the filenames touched by a delta are as expected.

        Caller only have to pass in the list of files for each part, all
        unspecified parts are considered empty (and checked as such).
        """
        for n in 'added', 'removed', 'renamed', 'modified', 'unchanged':
            # By default we expect an empty list
            expected = kw.get(n, [])
            # strip out only the path components
            got = [x[0] for x in getattr(delta, n)]
            self.assertEqual(expected, got)

    def test_tree_with_single_merge(self):
        """Make sure the tree layout is correct."""
        tree = self.create_tree_with_single_merge()
        rev_A_tree = tree.branch.repository.revision_tree('A')
        rev_B_tree = tree.branch.repository.revision_tree('B')
        rev_C_tree = tree.branch.repository.revision_tree('C')
        rev_D_tree = tree.branch.repository.revision_tree('D')

        self.check_delta(rev_B_tree.changes_from(rev_A_tree),
                         modified=['f1', 'f3'])

        self.check_delta(rev_C_tree.changes_from(rev_A_tree),
                         modified=['f2', 'f3'])

        self.check_delta(rev_D_tree.changes_from(rev_B_tree),
                         modified=['f2', 'f3'])

        self.check_delta(rev_D_tree.changes_from(rev_C_tree),
                         modified=['f1', 'f3'])

    def assertAllRevisionsForFileID(self, tree, file_id, revisions):
        """Ensure _filter_revisions_touching_file_id returns the right values.

        Get the return value from _filter_revisions_touching_file_id and make
        sure they are correct.
        """
        # The api for _filter_revisions_touching_file_id is a little crazy.
        # So we do the setup here.
        mainline = tree.branch.revision_history()
        mainline.insert(0, None)
        revnos = dict((rev, idx+1) for idx, rev in enumerate(mainline))
        view_revs_iter = log.get_view_revisions(mainline, revnos, tree.branch,
                                                'reverse', True)
        actual_revs = log._filter_revisions_touching_file_id(
                            tree.branch,
                            file_id,
                            list(view_revs_iter))
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
        self.assertAllRevisionsForFileID(tree, 'f3-id', ['D', 'C', 'B', 'A'])

    def test_file_id_with_ghosts(self):
        # This is testing bug #209948, where having a ghost would cause
        # _filter_revisions_touching_file_id() to fail.
        tree = self.create_tree_with_single_merge()
        # We need to add a revision, so switch back to a write-locked tree
        # (still a single addCleanup(tree.unlock) pending).
        tree.unlock()
        tree.lock_write()
        first_parent = tree.last_revision()
        tree.set_parent_ids([first_parent, 'ghost-revision-id'])
        self.build_tree_contents([('tree/f1', 'A\nB\nXX\n')])
        tree.commit('commit with a ghost', rev_id='XX')
        self.assertAllRevisionsForFileID(tree, 'f1-id', ['XX', 'B', 'A'])
        self.assertAllRevisionsForFileID(tree, 'f2-id', ['D', 'C', 'A'])

    def test_unknown_file_id(self):
        tree = self.create_tree_with_single_merge()
        self.assertAllRevisionsForFileID(tree, 'unknown', [])

    def test_empty_branch_unknown_file_id(self):
        tree = self.make_branch_and_tree('tree')
        self.assertAllRevisionsForFileID(tree, 'unknown', [])


class TestShowChangedRevisions(tests.TestCaseWithTransport):

    def test_show_changed_revisions_verbose(self):
        tree = self.make_branch_and_tree('tree_a')
        self.build_tree(['tree_a/foo'])
        tree.add('foo')
        tree.commit('bar', rev_id='bar-id')
        s = self.make_utf8_encoded_stringio()
        log.show_changed_revisions(tree.branch, [], ['bar-id'], s)
        self.assertContainsRe(s.getvalue(), 'bar')
        self.assertNotContainsRe(s.getvalue(), 'foo')


class TestLogFormatter(tests.TestCase):

    def test_short_committer(self):
        rev = revision.Revision('a-id')
        rev.committer = 'John Doe <jdoe@example.com>'
        lf = log.LogFormatter(None)
        self.assertEqual('John Doe', lf.short_committer(rev))
        rev.committer = 'John Smith <jsmith@example.com>'
        self.assertEqual('John Smith', lf.short_committer(rev))
        rev.committer = 'John Smith'
        self.assertEqual('John Smith', lf.short_committer(rev))
        rev.committer = 'jsmith@example.com'
        self.assertEqual('jsmith@example.com', lf.short_committer(rev))
        rev.committer = '<jsmith@example.com>'
        self.assertEqual('jsmith@example.com', lf.short_committer(rev))
        rev.committer = 'John Smith jsmith@example.com'
        self.assertEqual('John Smith', lf.short_committer(rev))

    def test_short_author(self):
        rev = revision.Revision('a-id')
        rev.committer = 'John Doe <jdoe@example.com>'
        lf = log.LogFormatter(None)
        self.assertEqual('John Doe', lf.short_author(rev))
        rev.properties['author'] = 'John Smith <jsmith@example.com>'
        self.assertEqual('John Smith', lf.short_author(rev))
        rev.properties['author'] = 'John Smith'
        self.assertEqual('John Smith', lf.short_author(rev))
        rev.properties['author'] = 'jsmith@example.com'
        self.assertEqual('jsmith@example.com', lf.short_author(rev))
        rev.properties['author'] = '<jsmith@example.com>'
        self.assertEqual('jsmith@example.com', lf.short_author(rev))
        rev.properties['author'] = 'John Smith jsmith@example.com'
        self.assertEqual('John Smith', lf.short_author(rev))
        del rev.properties['author']
        rev.properties['authors'] = ('John Smith <jsmith@example.com>\n'
                'Jane Rey <jrey@example.com>')
        self.assertEqual('John Smith', lf.short_author(rev))


class TestReverseByDepth(tests.TestCase):
    """Test reverse_by_depth behavior.

    This is used to present revisions in forward (oldest first) order in a nice
    layout.

    The tests use lighter revision description to ease reading.
    """

    def assertReversed(self, forward, backward):
        # Transform the descriptions to suit the API: tests use (revno, depth),
        # while the API expects (revid, revno, depth)
        def complete_revisions(l):
            """Transform the description to suit the API.

            Tests use (revno, depth) whil the API expects (revid, revno, depth).
            Since the revid is arbitrary, we just duplicate revno
            """
            return [ (r, r, d) for r, d in l]
        forward = complete_revisions(forward)
        backward= complete_revisions(backward)
        self.assertEqual(forward, log.reverse_by_depth(backward))


    def test_mainline_revisions(self):
        self.assertReversed([( '1', 0), ('2', 0)],
                            [('2', 0), ('1', 0)])

    def test_merged_revisions(self):
        self.assertReversed([('1', 0), ('2', 0), ('2.2', 1), ('2.1', 1),],
                            [('2', 0), ('2.1', 1), ('2.2', 1), ('1', 0),])
    def test_shifted_merged_revisions(self):
        """Test irregular layout.

        Requesting revisions touching a file can produce "holes" in the depths.
        """
        self.assertReversed([('1', 0), ('2', 0), ('1.1', 2), ('1.2', 2),],
                            [('2', 0), ('1.2', 2), ('1.1', 2), ('1', 0),])

    def test_merged_without_child_revisions(self):
        """Test irregular layout.

        Revision ranges can produce "holes" in the depths.
        """
        # When a revision of higher depth doesn't follow one of lower depth, we
        # assume a lower depth one is virtually there
        self.assertReversed([('1', 2), ('2', 2), ('3', 3), ('4', 4)],
                            [('4', 4), ('3', 3), ('2', 2), ('1', 2),])
        # So we get the same order after reversing below even if the original
        # revisions are not in the same order.
        self.assertReversed([('1', 2), ('2', 2), ('3', 3), ('4', 4)],
                            [('3', 3), ('4', 4), ('2', 2), ('1', 2),])


class TestHistoryChange(tests.TestCaseWithTransport):

    def setup_a_tree(self):
        tree = self.make_branch_and_tree('tree')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.commit('1a', rev_id='1a')
        tree.commit('2a', rev_id='2a')
        tree.commit('3a', rev_id='3a')
        return tree

    def setup_ab_tree(self):
        tree = self.setup_a_tree()
        tree.set_last_revision('1a')
        tree.branch.set_last_revision_info(1, '1a')
        tree.commit('2b', rev_id='2b')
        tree.commit('3b', rev_id='3b')
        return tree

    def setup_ac_tree(self):
        tree = self.setup_a_tree()
        tree.set_last_revision(revision.NULL_REVISION)
        tree.branch.set_last_revision_info(0, revision.NULL_REVISION)
        tree.commit('1c', rev_id='1c')
        tree.commit('2c', rev_id='2c')
        tree.commit('3c', rev_id='3c')
        return tree

    def test_all_new(self):
        tree = self.setup_ab_tree()
        old, new = log.get_history_change('1a', '3a', tree.branch.repository)
        self.assertEqual([], old)
        self.assertEqual(['2a', '3a'], new)

    def test_all_old(self):
        tree = self.setup_ab_tree()
        old, new = log.get_history_change('3a', '1a', tree.branch.repository)
        self.assertEqual([], new)
        self.assertEqual(['2a', '3a'], old)

    def test_null_old(self):
        tree = self.setup_ab_tree()
        old, new = log.get_history_change(revision.NULL_REVISION,
                                          '3a', tree.branch.repository)
        self.assertEqual([], old)
        self.assertEqual(['1a', '2a', '3a'], new)

    def test_null_new(self):
        tree = self.setup_ab_tree()
        old, new = log.get_history_change('3a', revision.NULL_REVISION,
                                          tree.branch.repository)
        self.assertEqual([], new)
        self.assertEqual(['1a', '2a', '3a'], old)

    def test_diverged(self):
        tree = self.setup_ab_tree()
        old, new = log.get_history_change('3a', '3b', tree.branch.repository)
        self.assertEqual(old, ['2a', '3a'])
        self.assertEqual(new, ['2b', '3b'])

    def test_unrelated(self):
        tree = self.setup_ac_tree()
        old, new = log.get_history_change('3a', '3c', tree.branch.repository)
        self.assertEqual(old, ['1a', '2a', '3a'])
        self.assertEqual(new, ['1c', '2c', '3c'])

    def test_show_branch_change(self):
        tree = self.setup_ab_tree()
        s = StringIO()
        log.show_branch_change(tree.branch, s, 3, '3a')
        self.assertContainsRe(s.getvalue(),
            '[*]{60}\nRemoved Revisions:\n(.|\n)*2a(.|\n)*3a(.|\n)*'
            '[*]{60}\n\nAdded Revisions:\n(.|\n)*2b(.|\n)*3b')

    def test_show_branch_change_no_change(self):
        tree = self.setup_ab_tree()
        s = StringIO()
        log.show_branch_change(tree.branch, s, 3, '3b')
        self.assertEqual(s.getvalue(),
            'Nothing seems to have changed\n')

    def test_show_branch_change_no_old(self):
        tree = self.setup_ab_tree()
        s = StringIO()
        log.show_branch_change(tree.branch, s, 2, '2b')
        self.assertContainsRe(s.getvalue(), 'Added Revisions:')
        self.assertNotContainsRe(s.getvalue(), 'Removed Revisions:')

    def test_show_branch_change_no_new(self):
        tree = self.setup_ab_tree()
        tree.branch.set_last_revision_info(2, '2b')
        s = StringIO()
        log.show_branch_change(tree.branch, s, 3, '3b')
        self.assertContainsRe(s.getvalue(), 'Removed Revisions:')
        self.assertNotContainsRe(s.getvalue(), 'Added Revisions:')
