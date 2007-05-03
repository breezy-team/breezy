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
    tests,
    )


class _CompiledDirstateHelpersFeature(tests.Feature):
    def _probe(self):
        try:
            import bzrlib.compiled.dirstate_helpers
        except ImportError:
            return False
        return True

    def feature_name(self):
        return 'compiled dirstate helpers'

CompiledDirstateHelpersFeature =_CompiledDirstateHelpersFeature()


class BenchmarkDirState(benchmarks.Benchmark):

    def build_helper(self, layout):
        """This is a helper with the common build_??_dirstate funcs.

        :param layout: [(num_dirs, files_per_dir)]
            The number of directories per level, and the number of files to put
            in it.
        :return: A DirState object with the given layout.
        """
        self.build_tree(['dir/'])
        contents = 'x'*10000
        self.build_tree_contents([('file', contents)])
        file_stat = os.lstat('file')
        dir_stat = os.lstat('dir')
        file_sha1 = osutils.sha_string(contents)

        state = dirstate.DirState.initialize('state')
        try:
            def create_entries(base, layout):
                if not layout:
                    return
                num_dirs, num_files = layout[0]
                for dnum in xrange(num_dirs):
                    if base:
                        path = '%s/%02d_directory' % (base, dnum)
                    else:
                        path = '%02d_directory' % (dnum,)
                    dir_id = generate_ids.gen_file_id(path)
                    state.add(path, dir_id, 'directory', dir_stat, '')
                    for fnum in xrange(num_files):
                        fname = '%s/%02d_filename' % (path, fnum)
                        file_id = generate_ids.gen_file_id(fname)
                        state.add(fname, file_id, 'file', file_stat, file_sha1)
                    create_entries(path, layout[1:])
            create_entries(None, layout)
            state.save()
        finally:
            state.unlock()
        return state

    def build_10k_dirstate_dirs(self):
        """Build a DirState file with 10k directories"""
        return self.build_helper([(10, 0), (10, 0), (10, 0), (10, 1)])

    def build_20k_dirstate(self):
        """Build a DirState file with 20k records.

        This approximates a kernel tree, based on the number of directories
        (1000), and number of files per directory (20) and depth (3).
        Because DirState doesn't have to have actual disk records, we just add
        random files.
        We try to have reasonable filename lengths, as well as a reasonable
        stat value, etc.
        """
        return self.build_helper([(10, 0), (10, 0), (10, 20)])

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

    def do_bisect_list(self, bisect_func):
        """Call bisect_dirblock for each path."""
        # We use self._paths and self._blocks because we expect it to be a very
        # long list. And the interface for 'self.time()' causes the parameters
        # to be printed when run with --lsprof-timed. Which is *really* ugly
        # when the list is thousands of entries.
        blocks = self._blocks
        return [bisect_func(blocks, path) for path in self._paths]

    def do_bisect_list_cached(self, bisect_func):
        """Same as do_bisect_list, but cache the split paths"""
        cache = {}
        blocks = self._blocks
        return [bisect_func(blocks, path, cache=cache) for path in self._paths]

    def setup_paths_and_offsets(self, state):
        """Get a list of paths and expected offsets.

        This will be used to check do_bisect_list*
        """
        state._read_dirblocks_if_needed()
        paths = ['']
        expected_offsets = [0]
        for offset, info in enumerate(state._dirblocks):
            dirname = info[0]
            # We already handled the empty path
            if dirname == '':
                continue
            # all paths are of the form ##_directory
            # so search for ##_director, ##_directory
            paths.extend([dirname[:-1], dirname])
            expected_offsets.extend([offset, offset])
        self._paths = paths
        self._expected_offsets = expected_offsets
        self._blocks = state._dirblocks

    def checkOffsets(self, offsets):
        """Make sure offsets matches self._expected_offsets"""
        # These are really long lists, so it is easier to compare them with
        # assertEqualDiff. So turn them into strings.
        expected_str = '\n'.join(str(x) for x in self._expected_offsets)
        offset_str = '\n'.join(str(x) for x in offsets)
        self.assertEqualDiff(expected_str, offset_str)

    def test_bisect_dirblock(self):
        state = self.build_10k_dirstate_dirs()
        state.lock_read()
        try:
            self.setup_paths_and_offsets(state)
            offsets = self.time(self.do_bisect_list, dirstate.bisect_dirblock)
            self.checkOffsets(offsets)
        finally:
            state.unlock()

    def test_bisect_dirblock_cached(self):
        state = self.build_10k_dirstate_dirs()
        state.lock_read()
        try:
            self.setup_paths_and_offsets(state)
            offsets = self.time(self.do_bisect_list_cached,
                                dirstate.bisect_dirblock)
            self.checkOffsets(offsets)
        finally:
            state.unlock()

    def test_bisect_dirblock_compiled(self):
        self.requireFeature(CompiledDirstateHelpersFeature)
        state = self.build_10k_dirstate_dirs()
        state.lock_read()
        try:
            self.setup_paths_and_offsets(state)
            offsets = self.time(self.do_bisect_list, dirstate.bisect_dirblock)
            self.checkOffsets(offsets)
        finally:
            state.unlock()

    def test_bisect_dirblock_compiled_cached(self):
        self.requireFeature(CompiledDirstateHelpersFeature)
        state = self.build_10k_dirstate_dirs()
        state.lock_read()
        try:
            self.setup_paths_and_offsets(state)
            offsets = self.time(self.do_bisect_list_cached,
                                dirstate.bisect_dirblock)
            self.checkOffsets(offsets)
        finally:
            state.unlock()
