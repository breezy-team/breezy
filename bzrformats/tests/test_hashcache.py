# Copyright (C) 2005-2011, 2016 Canonical Ltd
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

import os
import time

from breezy import osutils
from breezy.tests import TestCaseInTempDir
from breezy.tests.features import OsFifoFeature

from .. import hashcache

sha1 = osutils.sha_string


def pause():
    time.sleep(5.0)


class TestHashCache(TestCaseInTempDir):
    """Test the hashcache against a real directory."""

    def make_hashcache(self):
        # make a dummy bzr directory just to hold the cache
        os.mkdir(".bzr")
        hc = hashcache.HashCache(".", ".bzr/stat-cache")
        return hc

    def reopen_hashcache(self):
        hc = hashcache.HashCache(".", ".bzr/stat-cache")
        hc.read()
        return hc

    def test_hashcache_initial_miss(self):
        """Get correct hash from an empty hashcache."""
        hc = self.make_hashcache()
        self.build_tree_contents([("foo", b"hello")])
        self.assertEqual(
            hc.get_sha1("foo"), b"aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d"
        )
        self.assertEqual(hc.miss_count, 1)
        self.assertEqual(hc.hit_count, 0)

    def test_hashcache_new_file(self):
        hc = self.make_hashcache()
        self.build_tree_contents([("foo", b"goodbye")])
        # now read without pausing; it may not be possible to cache it as its
        # so new
        self.assertEqual(hc.get_sha1("foo"), sha1(b"goodbye"))

    def test_hashcache_nonexistent_file(self):
        hc = self.make_hashcache()
        self.assertEqual(hc.get_sha1("no-name-yet"), None)

    def test_hashcache_replaced_file(self):
        hc = self.make_hashcache()
        self.build_tree_contents([("foo", b"goodbye")])
        self.assertEqual(hc.get_sha1("foo"), sha1(b"goodbye"))
        os.remove("foo")
        self.assertEqual(hc.get_sha1("foo"), None)
        self.build_tree_contents([("foo", b"new content")])
        self.assertEqual(hc.get_sha1("foo"), sha1(b"new content"))

    def test_hashcache_not_file(self):
        hc = self.make_hashcache()
        self.build_tree(["subdir/"])
        self.assertEqual(hc.get_sha1("subdir"), None)

    def test_hashcache_load(self):
        hc = self.make_hashcache()
        self.build_tree_contents([("foo", b"contents")])
        pause()
        self.assertEqual(hc.get_sha1("foo"), sha1(b"contents"))
        hc.write()
        hc = self.reopen_hashcache()
        self.assertEqual(hc.get_sha1("foo"), sha1(b"contents"))
        self.assertEqual(hc.hit_count, 1)

    def test_hammer_hashcache(self):
        hc = self.make_hashcache()
        for i in range(10000):
            with open("foo", "wb") as f:
                last_content = b"%08x" % i
                f.write(last_content)
            last_sha1 = sha1(last_content)
            self.log("iteration %d: %r -> %r", i, last_content, last_sha1)
            got_sha1 = hc.get_sha1("foo")
            self.assertEqual(got_sha1, last_sha1)
            hc.write()
            hc = self.reopen_hashcache()

    def test_hashcache_raise(self):
        """Check that hashcache can raise BzrError."""
        self.requireFeature(OsFifoFeature)
        hc = self.make_hashcache()
        os.mkfifo("a")
        # It's possible that the system supports fifos but the filesystem
        # can't.  In that case we should skip at this point.  But in fact
        # such combinations don't usually occur for the filesystem where
        # people test bzr.
        self.assertRaises(OSError, hc.get_sha1, "a")
