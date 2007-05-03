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

"""Benchmarks for bzr DirState performance."""

import os

from bzrlib import (
    benchmarks,
    dirstate,
    generate_ids,
    osutils,
    )


class BenchmarkDirState(benchmarks.Benchmark):

    def build_20k_dirstate(self):
        """Build a DirState file with 20k records.

        This approximates a kernel tree, based on the number of directories
        (1000), and number of files per directory (20) and depth (3).
        Because DirState doesn't have to have actual disk records, we just add
        random files.
        We try to have reasonable filename lengths, as well as a reasonable
        stat value, etc.
        """
        self.build_tree(['dir/'])
        self.build_tree_contents([('file', 'x'*10000)])
        file_stat = os.lstat('file')
        dir_stat = os.lstat('dir')
        file_sha1 = osutils.sha_string('testing')

        # the average filename length is 11 characters
        # find . | sed -e 's/.*\///' | wc -l
        #   22545   22545  237869
        # 237869 / 22545 = 10.6
        # average depth is 30 characters
        # find . | wc -l
        #   22545   22545  679884
        # 679884 / 22545 = 30.1
        state = dirstate.DirState.initialize('state')
        try:
            for lvl1 in xrange(10):
                dir_1 = '%2d_directory' % (lvl1,)
                dir_1_id = generate_ids.gen_file_id(dir_1)
                state.add(dir_1, dir_1_id, 'directory', dir_stat, '')
                for lvl2 in xrange(10):
                    dir_2 = '%s/%2d_directory' % (dir_1, lvl2)
                    dir_2_id = generate_ids.gen_file_id(dir_2)
                    state.add(dir_2, dir_2_id, 'directory', dir_stat, '')
                    for lvl3 in xrange(10):
                        dir_3 = '%s/%2d_directory' % (dir_2, lvl3)
                        dir_3_id = generate_ids.gen_file_id(dir_3)
                        state.add(dir_3, dir_3_id, 'directory', dir_stat, '')
                        for filenum in xrange(20):
                            fname = '%s/%2d_filename' % (dir_3, filenum)
                            file_id = generate_ids.gen_file_id(fname)
                            state.add(fname, file_id, 'directory', dir_stat, '')
            state.save()
        finally:
            state.unlock()
        return state

    def test_build_20k_dirblocks(self):
        state = self.time(self.build_20k_dirstate)
        state.lock_read()
        try:
            entries = list(state._iter_entries())
            self.assertEqual(21111, len(entries))
        finally:
            state.unlock()

    def test__read_dirblocks_20k_tree_no_parents(self):
        state = self.build_20k_dirstate()
        state.lock_read()
        try:
            self.assertEqual(dirstate.DirState.NOT_IN_MEMORY,
                             state._dirblock_state)
            self.time(state._read_dirblocks_if_needed)
        finally:
            state.unlock()
