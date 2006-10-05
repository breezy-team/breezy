# Copyright (C) 2006 by Canonical Ltd
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

"""Tests for tree transform performance"""

import os
import sys

from bzrlib.benchmarks import Benchmark
from bzrlib.log import log_formatter, show_log
from bzrlib.osutils import pathjoin
from cStringIO import StringIO
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
        """Run log in a many-commit tree.""" 
        tree = self.make_many_commit_tree(hardlink=True)
        lf = log_formatter('long', to_file=StringIO())
        self.time(show_log, tree.branch, lf, direction='reverse')

    def test_merge_log(self):
        """Run log in a tree with many merges"""
        tree = self.make_heavily_merged_tree(hardlink=True)
        lf = log_formatter('short', to_file=StringIO())
        self.time(show_log, tree.branch, lf, direction='reverse')

    def test_log_screenful(self):
        """Simulate log --long|less"""
        self.screenful_tester('long')

    def test_log_screenful_line(self):
        """Simulate log --line|less"""
        self.screenful_tester('line')

    def test_log_screenful_short(self):
        """Simulate log --short|less"""
        self.screenful_tester('short')

    def screenful_tester(self, formatter):
        """Run show_log, but stop after 25 lines are generated"""
        tree = self.make_many_commit_tree(hardlink=True)
        def log_screenful():
            lf = log_formatter(formatter, to_file=LineConsumer(25))
            try:
                show_log(tree.branch, lf, direction='reverse')
            except LinesDone:
                pass
            else:
                raise Exception, "LinesDone not raised"
        self.time(log_screenful)

    def test_cmd_log(self):
        """Test execution of the log command.""" 
        tree = self.make_many_commit_tree(hardlink=True)
        self.time(self.run_bzr, 'log', '-r', '-4..')

    def test_cmd_log_subprocess(self):
        """Text startup and execution of the log command.""" 
        tree = self.make_many_commit_tree(hardlink=True)
        self.time(self.run_bzr_subprocess, 'log', '-r', '-4..')

    def test_log_verbose(self):
        """'verbose' log -- shows file changes"""
        tree = self.make_many_commit_tree(hardlink=True)
        lf = log_formatter('long', to_file=StringIO())
        self.time(show_log, tree.branch, lf, direction='reverse', verbose=True)
