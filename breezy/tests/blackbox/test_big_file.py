# Copyright (C) 2009 Jelmer Vernooij <jelmer@jelmer.uk>
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
#

"""Tests with "big" files.

These are meant to ensure that Breezy never keeps full copies of files in
memory.
"""

import contextlib
import errno
import os
import resource
import sys

from breezy import tests

BIG_FILE_SIZE = 1024 * 1024 * 500
BIG_FILE_CHUNK_SIZE = 1024

RESOURCE = resource.RLIMIT_AS
LIMIT = 1024 * 1024 * 100


def make_big_file(path):
    blob_1mb = BIG_FILE_CHUNK_SIZE * b"\x0c"
    fd = os.open(path, os.O_CREAT | os.O_WRONLY)
    try:
        for _i in range(BIG_FILE_SIZE // BIG_FILE_CHUNK_SIZE):
            os.write(fd, blob_1mb)
    finally:
        os.close(fd)


@contextlib.contextmanager
def limit_memory(size):
    if sys.platform in ("win32", "darwin"):
        raise NotImplementedError
    previous = resource.getrlimit(RESOURCE)
    resource.setrlimit(RESOURCE, (LIMIT, -1))
    yield
    resource.setrlimit(RESOURCE, previous)


class TestAdd(tests.TestCaseWithTransport):
    def writeBigFile(self, path):
        self.addCleanup(os.unlink, path)
        try:
            make_big_file(path)
        except OSError as e:
            if e.errno == errno.ENOSPC:
                self.skipTest("not enough disk space for big file")

    def setUp(self):
        super().setUp()
        cm = limit_memory(LIMIT)
        try:
            cm.__enter__()
        except NotImplementedError:
            self.skipTest("memory limits not supported on this platform")
        self.addCleanup(cm.__exit__, None, None, None)

    def test_allocate(self):
        def allocate():
            # In Python 3.14+, string multiplication is optimized and may not
            # immediately allocate memory. Use bytearray which always allocates.
            bytearray(BIG_FILE_SIZE)

        self.assertRaises(MemoryError, allocate)

    def test_add(self):
        tree = self.make_branch_and_tree("tree")
        self.writeBigFile(os.path.join(tree.basedir, "testfile"))
        tree.add("testfile")

    def test_make_file_big(self):
        self.knownFailure("commit keeps entire files in memory")
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/testfile"])
        tree.add("testfile")
        tree.commit("add small file")
        self.writeBigFile(os.path.join(tree.basedir, "testfile"))
        tree.commit("small files get big")
        self.knownFailure("commit keeps entire files in memory")

    def test_commit(self):
        self.knownFailure("commit keeps entire files in memory")
        tree = self.make_branch_and_tree("tree")
        self.writeBigFile(os.path.join(tree.basedir, "testfile"))
        tree.add("testfile")
        tree.commit("foo")

    def test_clone(self):
        self.knownFailure("commit keeps entire files in memory")
        tree = self.make_branch_and_tree("tree")
        self.writeBigFile(os.path.join(tree.basedir, "testfile"))
        tree.add("testfile")
        tree.commit("foo")
        tree.clone.sprout("newtree")
