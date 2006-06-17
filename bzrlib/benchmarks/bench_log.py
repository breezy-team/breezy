# Copyright (C) 2006 by Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as published by
# the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for tree transform performance"""

import os
import sys

from bzrlib.benchmarks import Benchmark
from bzrlib.log import log_formatter, show_log
from bzrlib.osutils import pathjoin
from StringIO import StringIO
from bzrlib.transform import TreeTransform
from bzrlib.workingtree import WorkingTree

class LinesDone(Exception):
    pass

class LineConsumer(object):

    def __init__(self, required_lines):
        self.required_lines = required_lines

    def write(self, text):
        self.required_lines -= text.count('\n')
        if self.required_lines < 0:
            raise LinesDone()
        

class LogBenchmark(Benchmark):

    def test_log(self):
        """Canonicalizing paths should be fast.""" 
        tree = self.make_many_commit_tree()
        lf = log_formatter('long', to_file=StringIO())
        self.time(show_log, tree.branch, lf, direction='reverse')

    def test_log_screenful(self):
        tree = self.make_many_commit_tree()
        def log_screenful():
            lf = log_formatter('long', to_file=LineConsumer(25))
            try:
                show_log(tree.branch, lf, direction='reverse')
            except LinesDone:
                pass
            else:
                raise Exception, "LinesDone not raised"
        self.time(log_screenful)
