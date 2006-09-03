# Copyright (C) 2005, 2006 Canonical Ltd
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

import os
import sha
import stat
import sys
import time

from bzrlib.errors import BzrError
from bzrlib.hashcache import HashCache
from bzrlib.tests import TestCaseInTempDir, TestSkipped, TestCase


def sha1(t):
    return sha.new(t).hexdigest()


def pause():
    time.sleep(5.0)


class TestHashCache(TestCaseInTempDir):
    """Test the hashcache against a real directory"""

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
        if getattr(os, 'mkfifo', None) == None:
            raise TestSkipped('filesystem fifos not supported on this system')
        os.mkfifo('a')
        # It's possible that the system supports fifos but the filesystem
        # can't.  In that case we should skip at this point.  But in fact
        # such combinations don't usually occur for the filesystem where
        # people test bzr.
        self.assertRaises(BzrError, hc.get_sha1, 'a')


class FakeHashCache(HashCache):
    """Hashcache that consults a fake clock rather than the real one.

    This lets us examine how old or new files would be handled, without
    actually having to wait for time to pass.
    """
    def __init__(self):
        # set root and cache file name to none to make sure we won't touch the
        # real filesystem
        HashCache.__init__(self, '.', 'hashcache')
        self._files = {}
        # simulated clock running forward as operations happen
        self._clock = 0

    def put_file(self, filename, file_contents):
        abspath = './' + filename
        self._files[abspath] = (file_contents, self._clock)

    def _fingerprint(self, abspath):
        entry = self._files[abspath]
        return (len(entry[0]),
                entry[1], entry[1],
                10, 20,
                stat.S_IFREG | 0600)

    def _really_sha1_file(self, abspath):
        if abspath in self._files:
            return sha1(self._files[abspath][0])
        else:
            return None

    def _cutoff_time(self):
        return self._clock - 2

    def pretend_to_sleep(self, secs):
        self._clock += secs

    
class TestHashCacheFakeFilesystem(TestCaseInTempDir):
    """Tests the hashcache using a simulated OS.
    """

    def make_hashcache(self):
        return FakeHashCache()

    def test_hashcache_miss_new_file(self):
        """A new file gives the right sha1 but misses"""
        hc = self.make_hashcache()
        hc.put_file('foo', 'hello')
        self.assertEquals(hc.get_sha1('foo'), sha1('hello'))
        self.assertEquals(hc.miss_count, 1)
        self.assertEquals(hc.hit_count, 0)
        # if we try again it's still too new; 
        self.assertEquals(hc.get_sha1('foo'), sha1('hello'))
        self.assertEquals(hc.miss_count, 2)
        self.assertEquals(hc.hit_count, 0)

    def test_hashcache_old_file(self):
        """An old file gives the right sha1 and hits"""
        hc = self.make_hashcache()
        hc.put_file('foo', 'hello')
        hc.pretend_to_sleep(20)
        # file is new; should get the correct hash but miss
        self.assertEquals(hc.get_sha1('foo'), sha1('hello'))
        self.assertEquals(hc.miss_count, 1)
        self.assertEquals(hc.hit_count, 0)
        # and can now be hit
        self.assertEquals(hc.get_sha1('foo'), sha1('hello'))
        self.assertEquals(hc.miss_count, 1)
        self.assertEquals(hc.hit_count, 1)
        hc.pretend_to_sleep(3)
        # and again
        self.assertEquals(hc.get_sha1('foo'), sha1('hello'))
        self.assertEquals(hc.miss_count, 1)
        self.assertEquals(hc.hit_count, 2)

    def test_hashcache_invalidates(self):
        hc = self.make_hashcache()
        hc.put_file('foo', 'hello')
        hc.pretend_to_sleep(20)
        hc.get_sha1('foo')
        hc.put_file('foo', 'h1llo')
        self.assertEquals(hc.get_sha1('foo'), sha1('h1llo'))
        self.assertEquals(hc.miss_count, 2)
        self.assertEquals(hc.hit_count, 0)
