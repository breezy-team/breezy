# Copyright (C) 2005 by Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import os
from cStringIO import StringIO

from bzrlib.selftest import BzrTestBase, TestCaseInTempDir
from bzrlib.log import LogFormatter, show_log, LongLogFormatter
from bzrlib.branch import Branch
from bzrlib.errors import InvalidRevisionNumber

class _LogEntry(object):
    # should probably move into bzrlib.log?
    pass


class LogCatcher(LogFormatter):
    """Pull log messages into list rather than displaying them.

    For ease of testing we save log messages here rather than actually
    formatting them, so that we can precisely check the result without
    being too dependent on the exact formatting.

    We should also test the LogFormatter.
    """
    def __init__(self):
        super(LogCatcher, self).__init__(to_file=None)
        self.logs = []
        
        
    def show(self, revno, rev, delta):
        le = _LogEntry()
        le.revno = revno
        le.rev = rev
        le.delta = delta
        self.logs.append(le)


class SimpleLogTest(TestCaseInTempDir):

    def checkDelta(self, delta, **kw):
        """Check the filenames touched by a delta are as expected."""
        for n in 'added', 'removed', 'renamed', 'modified', 'unchanged':
            expected = kw.get(n, [])

            # tests are written with unix paths; fix them up for windows
            if os.sep != '/':
                expected = [x.replace('/', os.sep) for x in expected]

            # strip out only the path components
            got = [x[0] for x in getattr(delta, n)]
            self.assertEquals(expected, got)

    def test_cur_revno(self):
        b = Branch('.', init=True)

        lf = LogCatcher()
        b.commit('empty commit')
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
        
        b = Branch('.', init=True)

        lf = LogCatcher()
        show_log(b, lf)
        # no entries yet
        eq(lf.logs, [])


        b.commit('empty commit')
        lf = LogCatcher()
        show_log(b, lf, verbose=True)
        eq(len(lf.logs), 1)
        eq(lf.logs[0].revno, 1)
        eq(lf.logs[0].rev.message, 'empty commit')
        d = lf.logs[0].delta
        self.log('log delta: %r' % d)
        self.checkDelta(d)


        self.build_tree(['hello'])
        b.add('hello')
        b.commit('add one file')

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
            self.log('%4d %s' % (logentry.revno, logentry.rev.message))
        
        # first one is most recent
        logentry = lf.logs[0]
        eq(logentry.revno, 2)
        eq(logentry.rev.message, 'add one file')
        d = logentry.delta
        self.log('log 2 delta: %r' % d)
        # self.checkDelta(d, added=['hello'])
        
