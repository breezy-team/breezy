# Copyright (C) 2005, 2006 Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import os
import sha
import sys
import time

from bzrlib.errors import BzrError
from bzrlib.hashcache import HashCache
from bzrlib.tests import TestCaseInTempDir, TestSkipped


def sha1(t):
    return sha.new(t).hexdigest()


def pause():
    time.sleep(5.0)


class FixThisError(Exception):
    pass
    

class TestHashCache(TestCaseInTempDir):

    def make_hashcache(self):
        # make a dummy bzr directory just to hold the cache
        os.mkdir('.bzr')
        hc = HashCache('.', '.bzr/stat-cache')
        return hc

    def reopen_hashcache(self):
        hc = HashCache('.', '.bzr/stat-cache')
        hc.read()
        return hc

    def test_hashcache_initial_miss(self):
        """Get correct hash from an empty hashcache"""
        hc = self.make_hashcache()
        self.build_tree_contents([('foo', 'hello')])
        self.assertEquals(hc.get_sha1('foo'),
                          'aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d')
        self.assertEquals(hc.miss_count, 1)
        self.assertEquals(hc.hit_count, 0)

    def test_hashcache_hit_old_file(self):
        """An old file gives a cache hit"""
        return ### this takes too long to run properly; skipped
        hc = self.make_hashcache()
        self.build_tree_contents([('foo', 'hello')])
        pause() # make sure file's old enough to cache
        self.assertEquals(hc.get_sha1('foo'),
                          'aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d')
        self.assertEquals(hc.miss_count, 1)
        self.assertEquals(hc.hit_count, 0)
        # now should hit on second try
        self.assertEquals(hc.get_sha1('foo'),
                          'aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d')
        self.assertEquals(hc.miss_count, 1)
        self.assertEquals(hc.hit_count, 1)
        # and hit again on third try
        self.assertEquals(hc.get_sha1('foo'),
                          'aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d')
        self.assertEquals(hc.miss_count, 1)
        self.assertEquals(hc.hit_count, 2)

    def test_hashcache_new_file(self):
        hc = self.make_hashcache()
        self.build_tree_contents([('foo', 'goodbye')])
        # now read without pausing; it may not be possible to cache it as its
        # so new
        self.assertEquals(hc.get_sha1('foo'), sha1('goodbye'))

    def test_hashcache_nonexistent_file(self):
        hc = self.make_hashcache()
        self.assertEquals(hc.get_sha1('no-name-yet'), None)

    def test_hashcache_replaced_file(self):
        hc = self.make_hashcache()
        self.build_tree_contents([('foo', 'goodbye')])
        self.assertEquals(hc.get_sha1('foo'), sha1('goodbye'))
        os.remove('foo')
        self.assertEquals(hc.get_sha1('foo'), None)
        self.build_tree_contents([('foo', 'new content')])
        self.assertEquals(hc.get_sha1('foo'), sha1('new content'))

    def test_hashcache_not_file(self):
        hc = self.make_hashcache()
        self.build_tree(['subdir/'])
        self.assertEquals(hc.get_sha1('subdir'), None)

    def test_hashcache_load(self):
        hc = self.make_hashcache()
        self.build_tree_contents([('foo', 'contents')])
        pause()
        self.assertEquals(hc.get_sha1('foo'), sha1('contents'))
        hc.write()
        hc = self.reopen_hashcache()
        self.assertEquals(hc.get_sha1('foo'), sha1('contents'))
        self.assertEquals(hc.hit_count, 1)

    def test_hammer_hashcache(self):
        hc = self.make_hashcache()
        for i in xrange(10000):
            self.log('start writing at %s', time.time())
            f = file('foo', 'w')
            try:
                last_content = '%08x' % i
                f.write(last_content)
            finally:
                f.close()
            last_sha1 = sha1(last_content)
            self.log("iteration %d: %r -> %r",
                     i, last_content, last_sha1)
            got_sha1 = hc.get_sha1('foo')
            self.assertEquals(got_sha1, last_sha1)
            hc.write()
            hc = self.reopen_hashcache()

    def test_hashcache_raise(self):
        """check that hashcache can raise BzrError"""
        hc = self.make_hashcache()
        if not hasattr(os, 'mkfifo'):
            raise TestSkipped('filesystem fifos not supported on this system')
        os.mkfifo('a')
        # It's possible that the system supports fifos but the filesystem
        # can't.  In that case we should skip at this point.  But in fact
        # such combinations don't usually occur for the filesystem where
        # people test bzr.
        self.assertRaises(BzrError, hc.get_sha1, 'a')
