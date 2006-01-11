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

import os
import sys
import time
from bzrlib.tests import TestCaseInTempDir



def sha1(t):
    import sha
    return sha.new(t).hexdigest()


def pause():
    if False:
        return
    if sys.platform in ('win32', 'cygwin'):
        time.sleep(3)
        return
    # allow it to stabilize
    start = int(time.time())
    while int(time.time()) == start:
        time.sleep(0.2)
    

class TestHashCache(TestCaseInTempDir):

    def test_hashcache(self):
        """Functional tests for hashcache"""
        from bzrlib.hashcache import HashCache
        import os

        # make a dummy bzr directory just to hold the cache
        os.mkdir('.bzr')
        hc = HashCache(u'.')

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

        file('foo2', 'wb').write('other file')
        self.assertEquals(hc.get_sha1('foo2'), sha1('other file'))

        os.remove('foo2')
        self.assertEquals(hc.get_sha1('foo2'), None)

        file('foo2', 'wb').write('new content')
        self.assertEquals(hc.get_sha1('foo2'), sha1('new content'))

        self.assertEquals(hc.get_sha1('subdir'), None)

        # it's likely neither are cached at the moment because they 
        # changed recently, but we can't be sure
        pause()

        # should now be safe to cache it if we reread them
        self.assertEquals(hc.get_sha1('foo'), sha1('g00dbye'))
        self.assertEquals(len(hc._cache), 1)
        self.assertEquals(hc.get_sha1('foo2'), sha1('new content'))
        self.assertEquals(len(hc._cache), 2)

        # write out, read back in and check that we don't need to
        # re-read any files
        hc.write()
        del hc

        hc = HashCache(u'.')
        hc.read()

        self.assertEquals(len(hc._cache), 2)
        self.assertEquals(hc.get_sha1('foo'), sha1('g00dbye'))
        self.assertEquals(hc.hit_count, 1)
        self.assertEquals(hc.miss_count, 0)
        self.assertEquals(hc.get_sha1('foo2'), sha1('new content'))

    def test_hashcache_raise(self):
        """check that hashcache can raise BzrError"""
        from bzrlib.hashcache import HashCache
        import os

        os.mkdir('.bzr')
        hc = HashCache(u'.')
        ok = False
        # make a best effort to create a weird kind of file
        try:
            os.mkfifo('a')
            ok=True
        except OSError:
            try:
                os.mknod('a')
                ok=True
            except OSError:
                try:
                    os.mkdev('a')
                    ok=True
                except OSError:
                    pass
        
        from bzrlib.errors import BzrError
        if ok:
            self.assertRaises(BzrError, hc.get_sha1, 'a')
        else:
            raise BzrError("no weird file type could be created: extend this test case for your os")
