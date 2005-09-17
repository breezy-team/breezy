# Copyright (C) 2004, 2005 by Canonical Ltd

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


from bzrlib.selftest import TestCaseInTempDir
from bzrlib.selftest.HTTPTestUtil import TestCaseWithWebserver
from bzrlib.transport import NoSuchFile, FileExists

def test_transport(tester, t, readonly=False):
    """Test a transport object. Basically, it assumes that the
    Transport object is connected to the current working directory.
    So that whatever is done through the transport, should show
    up in the working directory, and vice-versa.

    This also tests to make sure that the functions work with both
    generators and lists (assuming iter(list) is effectively a generator)
    """
    import tempfile, os
    from bzrlib.transport.local import LocalTransport

    # Test has
    files = ['a', 'b', 'e', 'g']
    tester.build_tree(files)
    tester.assertEqual(t.has('a'), True)
    tester.assertEqual(t.has('c'), False)
    tester.assertEqual(list(t.has_multi(['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'])),
            [True, True, False, False, True, False, True, False])
    tester.assertEqual(list(t.has_multi(iter(['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']))),
            [True, True, False, False, True, False, True, False])

    # Test get
    tester.assertEqual(t.get('a').read(), open('a').read())
    content_f = t.get_multi(files)
    for path,f in zip(files, content_f):
        tester.assertEqual(open(path).read(), f.read())

    content_f = t.get_multi(iter(files))
    for path,f in zip(files, content_f):
        tester.assertEqual(open(path).read(), f.read())

    tester.assertRaises(NoSuchFile, t.get, 'c')
    try:
        files = list(t.get_multi(['a', 'b', 'c']))
    except NoSuchFile:
        pass
    else:
        tester.fail('Failed to raise NoSuchFile for missing file in get_multi')
    try:
        files = list(t.get_multi(iter(['a', 'b', 'c', 'e'])))
    except NoSuchFile:
        pass
    else:
        tester.fail('Failed to raise NoSuchFile for missing file in get_multi')

    # Test put
    if readonly:
        open('c', 'wb').write('some text for c\n')
    else:
        t.put('c', 'some text for c\n')
    tester.assert_(os.path.exists('c'))
    tester.assertEqual(open('c').read(), 'some text for c\n')
    tester.assertEqual(t.get('c').read(), 'some text for c\n')
    # Make sure 'has' is updated
    tester.assertEqual(list(t.has_multi(['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'])),
            [True, True, True, False, True, False, True, False])
    if readonly:
        open('a', 'wb').write('new\ncontents for\na\n')
        open('d', 'wb').write('contents\nfor d\n')
    else:
        # Put also replaces contents
        tester.assertEqual(t.put_multi([('a', 'new\ncontents for\na\n'),
                                      ('d', 'contents\nfor d\n')]),
                         2)
    tester.assertEqual(list(t.has_multi(['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'])),
            [True, True, True, True, True, False, True, False])
    tester.assertEqual(open('a').read(), 'new\ncontents for\na\n')
    tester.assertEqual(open('d').read(), 'contents\nfor d\n')

    if readonly:
        open('a', 'wb').write('diff\ncontents for\na\n')
        open('d', 'wb').write('another contents\nfor d\n')
    else:
        tester.assertEqual(
            t.put_multi(iter([('a', 'diff\ncontents for\na\n'),
                              ('d', 'another contents\nfor d\n')]))
                         , 2)
    tester.assertEqual(open('a').read(), 'diff\ncontents for\na\n')
    tester.assertEqual(open('d').read(), 'another contents\nfor d\n')

    if not readonly:
        tester.assertRaises(NoSuchFile, t.put, 'path/doesnt/exist/c', 'contents')

    # Test mkdir
    os.mkdir('dir_a')
    tester.assertEqual(t.has('dir_a'), True)
    tester.assertEqual(t.has('dir_b'), False)

    if readonly:
        os.mkdir('dir_b')
    else:
        t.mkdir('dir_b')
    tester.assertEqual(t.has('dir_b'), True)
    tester.assert_(os.path.isdir('dir_b'))

    if readonly:
        os.mkdir('dir_c')
        os.mkdir('dir_d')
    else:
        t.mkdir_multi(['dir_c', 'dir_d'])
    tester.assertEqual(list(t.has_multi(['dir_a', 'dir_b', 'dir_c', 'dir_d', 'dir_e', 'dir_b'])),
            [True, True, True, True, False, True])
    for d in ['dir_a', 'dir_b', 'dir_c', 'dir_d']:
        tester.assert_(os.path.isdir(d))

    if not readonly:
        tester.assertRaises(NoSuchFile, t.mkdir, 'path/doesnt/exist')
        tester.assertRaises(FileExists, t.mkdir, 'dir_a') # Creating a directory again should fail

    # Make sure the transport recognizes when a
    # directory is created by other means
    # Caching Transports will fail, because dir_e was already seen not
    # to exist. So instead, we will search for a new directory
    #os.mkdir('dir_e')
    #if not readonly:
    #    tester.assertRaises(FileExists, t.mkdir, 'dir_e')

    os.mkdir('dir_f')
    if not readonly:
        tester.assertRaises(FileExists, t.mkdir, 'dir_f')

    # Test get/put in sub-directories
    if readonly:
        open('dir_a/a', 'wb').write('contents of dir_a/a')
        open('dir_b/b', 'wb').write('contents of dir_b/b')
    else:
        tester.assertEqual(
            t.put_multi([('dir_a/a', 'contents of dir_a/a'),
                         ('dir_b/b', 'contents of dir_b/b')])
                      , 2)
    for f in ('dir_a/a', 'dir_b/b'):
        tester.assertEqual(t.get(f).read(), open(f).read())

    # Test copy_to
    dtmp = tempfile.mkdtemp(dir='.', prefix='test-transport-')
    dtmp_base = os.path.basename(dtmp)
    local_t = LocalTransport(dtmp)

    files = ['a', 'b', 'c', 'd']
    t.copy_to(files, local_t)
    for f in files:
        tester.assertEquals(open(f).read(), open(os.path.join(dtmp_base, f)).read())

    # TODO: Test append
    # TODO: Make sure all entries support file-like objects as well as strings.
    # TODO: Test get_partial()

class LocalTransportTest(TestCaseInTempDir):
    def test_local_transport(self):
        from bzrlib.transport.local import LocalTransport

        t = LocalTransport('.')
        test_transport(self, t)

class HttpTransportTest(TestCaseWithWebserver):
    def test_http_transport(self):
        from bzrlib.transport.http import HttpTransport

        t = HttpTransport(self.get_remote_url('.'))
        test_transport(self, t, readonly=True)

