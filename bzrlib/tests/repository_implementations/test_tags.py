# Copyright (C) 2007 Canonical Ltd
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

"""Tags stored within a repository"""

import os
import re
import sys

import bzrlib
from bzrlib import bzrdir, errors, repository
from bzrlib.branch import Branch, needs_read_lock, needs_write_lock
from bzrlib.tests import TestCase, TestCaseWithTransport, TestSkipped
from bzrlib.trace import mutter
from bzrlib.workingtree import WorkingTree
from bzrlib.tests.repository_implementations.test_repository \
        import TestCaseWithRepository


class TestRepositoryTags(TestCaseWithRepository):

    def setUp(self):
        # formats that don't support tags can skip the rest of these 
        # tests...
        fmt = self.repository_format
        f = getattr(fmt, 'supports_tags')
        if f is None:
            raise TestSkipped("format %s doesn't declare whether it "
                "supports tags, assuming not" % fmt)
        if not f():
            raise TestSkipped("format %s doesn't support tags" % fmt)
        TestCaseWithRepository.setUp(self)

    def test_foo_tags(self):
        repo = self.make_repository('repo')
        tags = repo.get_tags()
