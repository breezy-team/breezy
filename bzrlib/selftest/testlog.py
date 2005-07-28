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

from bzrlib.selftest import BzrTestBase
from bzrlib.log import LogFormatter, show_log
from bzrlib.branch import Branch

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
        le = _LogEntry
        le.revno = revno
        le.rev = rev
        le.delta = delta
        self.logs.append(le)


class SimpleLogTest(BzrTestBase):
    def runTest(self):
        eq = self.assertEquals
        ass = self.assert_
        
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
        ass(not d.added)
        ass(not d.removed)
        ass(not d.renamed)
        ass(not d.modified)
        ass(not d.unchanged)

        
