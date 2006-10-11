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

"""Benchmarks of bzr startup time, for some simple operations."""


from bzrlib.benchmarks import Benchmark


class StartupBenchmark(Benchmark):

    def make_simple_tree(self):
        """A small, simple tree. No caching needed"""
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/', 'b/c'])
        tree.add(['a', 'b', 'b/c'])
        return tree

    def make_simple_committed_tree(self):
        tree = self.make_simple_tree()
        tree.commit('simple commit')
        return tree

    def test___version(self):
        """Test the startup overhead of plain bzr --version"""
        self.time(self.run_bzr_subprocess, '--version')

    def test_branch(self):
        """Test the time to branch this into other"""
        tree = self.make_simple_committed_tree()
        self.time(self.run_bzr_subprocess, 'branch', '.', 'other')

    def test_commit(self):
        """Test execution of simple commit"""
        tree = self.make_simple_tree()
        self.time(self.run_bzr_subprocess, 'commit', '-m', 'init simple tree')

    def test_diff(self):
        """Test simple diff time"""
        tree = self.make_simple_committed_tree()
        self.time(self.run_bzr_subprocess, 'diff')

    def test_help(self):
        """Test the startup overhead of plain bzr help"""
        self.time(self.run_bzr_subprocess, 'help')

    def test_help_commands(self):
        """startup time for bzr help commands, which has to load more"""
        self.time(self.run_bzr_subprocess, 'help', 'commands')

    def test_log(self):
        """Test simple log time"""
        tree = self.make_simple_committed_tree()
        self.time(self.run_bzr_subprocess, 'log')

    def test_missing(self):
        """Test simple missing time"""
        tree = self.make_simple_committed_tree()
        other = tree.bzrdir.sprout('other')
        self.time(self.run_bzr_subprocess, 'missing', working_dir='other')

    def test_pull(self):
        """Test simple pull time"""
        tree = self.make_simple_committed_tree()
        other = tree.bzrdir.sprout('other')
        # There should be nothing to pull, and this should be determined
        # quickly
        self.time(self.run_bzr_subprocess, 'pull', working_dir='other')

    def test_rocks(self):
        """Test the startup overhead by running a do-nothing command"""
        self.time(self.run_bzr_subprocess, 'rocks')

    def test_status(self):
        """Test simple status time"""
        tree = self.make_simple_committed_tree()
        self.time(self.run_bzr_subprocess, 'status')
