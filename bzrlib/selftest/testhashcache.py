# (C) 2005 Canonical Ltd

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

from bzrlib.selftest import InTempDir



def sha1(t):
    import sha
    return sha.new(t).hexdigest()


def pause():
    import time
    # allow it to stabilize
    start = int(time.time())
    while int(time.time()) == start:
        time.sleep(0.2)
    


class TestHashCache(InTempDir):
    """Functional tests for statcache"""
    def runTest(self):
        from bzrlib.hashcache import HashCache
        import os
        import time

        hc = HashCache('.')

        file('foo', 'wb').write('hello')
        os.mkdir('subdir')
        pause()

        self.assertEquals(hc.get_sha1('foo'),
                          'aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d')
        self.assertEquals(hc.miss_count, 1)
        self.assertEquals(hc.hit_count, 0)

        # check we hit without re-reading
        self.assertEquals(hc.get_sha1('foo'),
                          'aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d')
        self.assertEquals(hc.miss_count, 1)
        self.assertEquals(hc.hit_count, 1)

        # check again without re-reading
        self.assertEquals(hc.get_sha1('foo'),
                          'aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d')
        self.assertEquals(hc.miss_count, 1)
        self.assertEquals(hc.hit_count, 2)

        # write new file and make sure it is seen
        file('foo', 'wb').write('goodbye')
        pause()
        self.assertEquals(hc.get_sha1('foo'),
                          '3c8ec4874488f6090a157b014ce3397ca8e06d4f')
        self.assertEquals(hc.miss_count, 2)

        # quickly write new file of same size and make sure it is seen
        # this may rely on detection of timestamps that are too close
        # together to be safe
        file('foo', 'wb').write('g00dbye')
        self.assertEquals(hc.get_sha1('foo'),
                          sha1('g00dbye'))
        
        # this is not quite guaranteed to be true; we might have
        # crossed a 1s boundary before
        self.assertEquals(hc.danger_count, 1)
        self.assertEquals(len(hc._cache), 0)

        self.assertEquals(hc.get_sha1('subdir'), None)

        pause()

        # should now be safe to cache it
        self.assertEquals(hc.get_sha1('foo'),
                          sha1('g00dbye'))
        self.assertEquals(len(hc._cache), 1)

        # write out, read back in and check that we don't need to
        # re-read any files
        hc.write('stat-cache')
        del hc

        hc = HashCache('.')
        # hc.read('stat-cache')
        

        

