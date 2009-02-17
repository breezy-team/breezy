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
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Test FilterProcessor"""

from cStringIO import StringIO

from bzrlib import tests

from bzrlib.plugins.fastimport import (
    parser,
    )
from bzrlib.plugins.fastimport.processors.filter_processor import (
    FilterProcessor,
    )


# A sample input stream containing all (top level) import commands
_SAMPLE_ALL = \
"""blob
mark :1
data 4
foo
commit refs/heads/master
mark :2
committer Joe <joe@example.com> 1234567890 +1000
data 14
Initial import
M 644 :1 COPYING
checkpoint
progress first import done
reset refs/remote/origin/master
from :2
tag refs/tags/v0.1
from :2
tagger Joe <joe@example.com> 1234567890 +1000
data 12
release v0.1
"""


# A sample input stream creating the following tree:
#
#  NEWS
#  doc/README.txt
#  doc/index.txt
_SAMPLE_WITH_DIR = \
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


class TestCaseWithFiltering(tests.TestCase):

    def assertFiltering(self, input, params, expected):
        outf = StringIO()
        proc = FilterProcessor(None, params=params)
        proc.outf = outf
        s = StringIO(input)
        p = parser.ImportParser(s)
        proc.process(p.iter_commands)
        out = outf.getvalue()
        self.assertEqualDiff(expected, out)


class TestNoFiltering(TestCaseWithFiltering):

    def test_params_not_given(self):
        self.assertFiltering(_SAMPLE_ALL, None, _SAMPLE_ALL)

    def test_params_are_none(self):
        params = {'include_paths': None, 'exclude_paths': None}
        self.assertFiltering(_SAMPLE_ALL, params, _SAMPLE_ALL)


class TestIncludePaths(TestCaseWithFiltering):

    def test_file_in_root(self):
        # Things to note:
        # * only referenced blobs are retained
        # * from clause is dropped from the first command
        params = {'include_paths': ['NEWS']}
        self.assertFiltering(_SAMPLE_WITH_DIR, params, \
"""blob
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
M 644 :2 NEWS
""")

    def test_file_in_subdir(self):
        #  Additional things to note:
        # * new root: path is now index.txt, not doc/index.txt
        # * other files changed in matching commits are excluded
        params = {'include_paths': ['doc/index.txt']}
        self.assertFiltering(_SAMPLE_WITH_DIR, params, \
"""blob
mark :4
data 11
== Docs ==
commit refs/heads/master
mark :102
committer d <b@c> 1234798653 +0000
data 8
test
ing
M 644 :4 index.txt
""")

    def test_file_with_changes(self):
        #  Additional things to note:
        # * from updated to reference parents in the output
        params = {'include_paths': ['doc/README.txt']}
        self.assertFiltering(_SAMPLE_WITH_DIR, params, \
"""blob
mark :1
data 9
Welcome!
commit refs/heads/master
mark :100
committer a <b@c> 1234798653 +0000
data 4
test
M 644 :1 README.txt
blob
mark :3
data 19
Welcome!
my friend
commit refs/heads/master
mark :102
committer d <b@c> 1234798653 +0000
data 8
test
ing
from :100
M 644 :3 README.txt
""")

    def test_subdir(self):
        params = {'include_paths': ['doc/']}
        self.assertFiltering(_SAMPLE_WITH_DIR, params, \
"""blob
mark :1
data 9
Welcome!
commit refs/heads/master
mark :100
committer a <b@c> 1234798653 +0000
data 4
test
M 644 :1 README.txt
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
M 644 :3 README.txt
M 644 :4 index.txt
""")

    def test_multiple_files_in_subdir(self):
        # The new root should be the subdrectory
        params = {'include_paths': ['doc/README.txt', 'doc/index.txt']}
        self.assertFiltering(_SAMPLE_WITH_DIR, params, \
"""blob
mark :1
data 9
Welcome!
commit refs/heads/master
mark :100
committer a <b@c> 1234798653 +0000
data 4
test
M 644 :1 README.txt
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
M 644 :3 README.txt
M 644 :4 index.txt
""")


class TestExcludePaths(TestCaseWithFiltering):

    def test_file_in_root(self):
        params = {'exclude_paths': ['NEWS']}
        self.assertFiltering(_SAMPLE_WITH_DIR, params, \
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
""")

    def test_file_in_subdir(self):
        params = {'exclude_paths': ['doc/README.txt']}
        self.assertFiltering(_SAMPLE_WITH_DIR, params, \
"""blob
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
M 644 :2 NEWS
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
M 644 :4 doc/index.txt
""")

    def test_subdir(self):
        params = {'exclude_paths': ['doc/']}
        self.assertFiltering(_SAMPLE_WITH_DIR, params, \
"""blob
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
M 644 :2 NEWS
""")

    def test_multple_files(self):
        params = {'exclude_paths': ['doc/index.txt', 'NEWS']}
        self.assertFiltering(_SAMPLE_WITH_DIR, params, \
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
mark :3
data 19
Welcome!
my friend
commit refs/heads/master
mark :102
committer d <b@c> 1234798653 +0000
data 8
test
ing
from :100
M 644 :3 doc/README.txt
""")


class TestIncludeAndExcludePaths(TestCaseWithFiltering):

    def test_included_dir_and_excluded_file(self):
        params = {'include_paths': ['doc/'], 'exclude_paths': ['doc/index.txt']}
        self.assertFiltering(_SAMPLE_WITH_DIR, params, \
"""blob
mark :1
data 9
Welcome!
commit refs/heads/master
mark :100
committer a <b@c> 1234798653 +0000
data 4
test
M 644 :1 README.txt
blob
mark :3
data 19
Welcome!
my friend
commit refs/heads/master
mark :102
committer d <b@c> 1234798653 +0000
data 8
test
ing
from :100
M 644 :3 README.txt
""")
