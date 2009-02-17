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


class TestCaseWithFiltering(tests.TestCase):

    def assertFiltering(self, input, params, expected):
        outf = StringIO()
        proc = FilterProcessor(None, params=params)
        proc.outf = outf
        s = StringIO(input)
        p = parser.ImportParser(s)
        proc.process(p.iter_commands)
        out = outf.getvalue()
        self.assertEqualDiff(out, expected)


class TestNoFiltering(TestCaseWithFiltering):

    def test_params_not_given(self):
        self.assertFiltering(_SAMPLE_ALL, None, _SAMPLE_ALL)

    def test_params_are_none(self):
        params = {'include_paths': None, 'exclude_paths': None}
        self.assertFiltering(_SAMPLE_ALL, params, _SAMPLE_ALL)
