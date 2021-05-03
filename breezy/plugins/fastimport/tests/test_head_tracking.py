# Copyright (C) 2009 Canonical Ltd
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
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Test tracking of heads"""

from io import StringIO

from fastimport import (
    commands,
    parser,
    )

import testtools

from fastimport.reftracker import (
    RefTracker,
    )


# A sample input stream that only adds files to a branch
_SAMPLE_MAINLINE = \
    """blob
mark :1
data 9
Welcome!
commit refs/heads/master
mark :100
committer a <b@c> 1234798653 +0000
data 4
test
M 644 :1 doc/README.txt
blob
mark :2
data 17
Life
is
good ...
commit refs/heads/master
mark :101
committer a <b@c> 1234798653 +0000
data 8
test
ing
from :100
M 644 :2 NEWS
blob
mark :3
data 19
Welcome!
my friend
blob
mark :4
data 11
== Docs ==
commit refs/heads/master
mark :102
committer d <b@c> 1234798653 +0000
data 8
test
ing
from :101
M 644 :3 doc/README.txt
M 644 :4 doc/index.txt
"""

# A sample input stream that adds files to two branches
_SAMPLE_TWO_HEADS = \
    """blob
mark :1
data 9
Welcome!
commit refs/heads/master
mark :100
committer a <b@c> 1234798653 +0000
data 4
test
M 644 :1 doc/README.txt
blob
mark :2
data 17
Life
is
good ...
commit refs/heads/mybranch
mark :101
committer a <b@c> 1234798653 +0000
data 8
test
ing
from :100
M 644 :2 NEWS
blob
mark :3
data 19
Welcome!
my friend
blob
mark :4
data 11
== Docs ==
commit refs/heads/master
mark :102
committer d <b@c> 1234798653 +0000
data 8
test
ing
from :100
M 644 :3 doc/README.txt
M 644 :4 doc/index.txt
"""

# A sample input stream that adds files to two branches
_SAMPLE_TWO_BRANCHES_MERGED = \
    """blob
mark :1
data 9
Welcome!
commit refs/heads/master
mark :100
committer a <b@c> 1234798653 +0000
data 4
test
M 644 :1 doc/README.txt
blob
mark :2
data 17
Life
is
good ...
commit refs/heads/mybranch
mark :101
committer a <b@c> 1234798653 +0000
data 8
test
ing
from :100
M 644 :2 NEWS
blob
mark :3
data 19
Welcome!
my friend
blob
mark :4
data 11
== Docs ==
commit refs/heads/master
mark :102
committer d <b@c> 1234798653 +0000
data 8
test
ing
from :100
M 644 :3 doc/README.txt
M 644 :4 doc/index.txt
commit refs/heads/master
mark :103
committer d <b@c> 1234798653 +0000
data 8
test
ing
from :102
merge :101
D doc/index.txt
"""

# A sample input stream that contains a reset
_SAMPLE_RESET = \
    """blob
mark :1
data 9
Welcome!
commit refs/heads/master
mark :100
committer a <b@c> 1234798653 +0000
data 4
test
M 644 :1 doc/README.txt
reset refs/remotes/origin/master
from :100
"""

# A sample input stream that contains a reset and more commits
_SAMPLE_RESET_WITH_MORE_COMMITS = \
    """blob
mark :1
data 9
Welcome!
commit refs/heads/master
mark :100
committer a <b@c> 1234798653 +0000
data 4
test
M 644 :1 doc/README.txt
reset refs/remotes/origin/master
from :100
commit refs/remotes/origin/master
mark :101
committer d <b@c> 1234798653 +0000
data 8
test
ing
from :100
D doc/README.txt
"""


class TestHeadTracking(testtools.TestCase):

    def assertHeads(self, input, expected):
        s = StringIO(input)
        p = parser.ImportParser(s)
        reftracker = RefTracker()
        for cmd in p.iter_commands():
            if isinstance(cmd, commands.CommitCommand):
                reftracker.track_heads(cmd)
                # eat the file commands
                list(cmd.iter_files())
            elif isinstance(cmd, commands.ResetCommand):
                if cmd.from_ is not None:
                    reftracker.track_heads_for_ref(cmd.ref, cmd.from_)
        self.assertEqual(reftracker.heads, expected)

    def test_mainline(self):
        self.assertHeads(_SAMPLE_MAINLINE, {
            ':102': set(['refs/heads/master']),
            })

    def test_two_heads(self):
        self.assertHeads(_SAMPLE_TWO_HEADS, {
            ':101': set(['refs/heads/mybranch']),
            ':102': set(['refs/heads/master']),
            })

    def test_two_branches_merged(self):
        self.assertHeads(_SAMPLE_TWO_BRANCHES_MERGED, {
            ':103': set(['refs/heads/master']),
            })

    def test_reset(self):
        self.assertHeads(_SAMPLE_RESET, {
            ':100': set(['refs/heads/master', 'refs/remotes/origin/master']),
            })

    def test_reset_with_more_commits(self):
        self.assertHeads(_SAMPLE_RESET_WITH_MORE_COMMITS, {
            ':101': set(['refs/remotes/origin/master']),
            })
