# Copyright (C) 2005 by Canonical Ltd

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

"""Tests for upgrade of old trees.

This file contains canned versions of some old trees, which are instantiated 
and then upgraded to the new format."""

import base64
import os
import sys

from bzrlib.selftest import TestCase, TestCaseInTempDir
from bzrlib.branch import Branch
from bzrlib.revision import is_ancestor
from bzrlib.upgrade import upgrade


# TODO: Hoist these to the test utility module
# TODO: Script to write a description of a directory for testing
# TODO: Helper that compares two structures and raises a helpful error
# where they differ.

def build_tree_contents(template):
    """Reconstitute some files from a text description.

    Each element of template is a tuple.  The first element is a filename,
    with an optional ending character indicating the type.

    The template is built relative to the Python process's current
    working directory.
    """
    for tt in template:
        name = tt[0]
        if name[-1] == '/':
            os.mkdir(name)
        elif name[-1] == '@':
            raise NotImplementedError('symlinks not handled yet')
        else:
            f = file(name, 'wb')
            try:
                f.write(tt[1])
            finally:
                f.close()


def pack_tree_contents(top):
    """Make a Python datastructure description of a tree.
    
    If top is an absolute path the descriptions will be absolute."""
    for dirpath, dirnames, filenames in os.walk(top):
        yield (dirpath + '/', )
        filenames.sort()
        for fn in filenames:
            fullpath = os.path.join(dirpath, fn)
            yield (fullpath, file(fullpath, 'rb').read())
    

class TestUpgrade(TestCaseInTempDir):
    def test_build_tree(self):
        """Test tree-building test helper"""
        build_tree_contents(_upgrade1_template)
        self.assertTrue(os.path.exists('foo'))
        self.assertTrue(os.path.exists('.bzr/README'))

    def test_upgrade_simple(self):
        """Upgrade simple v0.0.4 format to v5"""
        eq = self.assertEquals
        build_tree_contents(_upgrade1_template)
        upgrade('.')
        b = Branch.open('.')
        eq(b._branch_format, 5)
        rh = b.revision_history()
        eq(rh,
           ['mbp@sourcefrog.net-20051004035611-176b16534b086b3c',
            'mbp@sourcefrog.net-20051004035756-235f2b7dcdddd8dd'])
        t = b.revision_tree(rh[0])
        foo_id = 'foo-20051004035605-91e788d1875603ae'
        eq(t.get_file_text(foo_id), 'initial contents\n')
        t = b.revision_tree(rh[1])
        eq(t.get_file_text(foo_id), 'new contents\n')


_upgrade1_template = \
[
 ('foo', 'new contents\n'),
 ('.bzr/',),
 ('.bzr/README',
  'This is a Bazaar-NG control directory.\nDo not change any files in this directory.\n'),
 ('.bzr/branch-format', 'Bazaar-NG branch, format 0.0.4\n'),
 ('.bzr/revision-history',
  'mbp@sourcefrog.net-20051004035611-176b16534b086b3c\n'
  'mbp@sourcefrog.net-20051004035756-235f2b7dcdddd8dd\n'),
 ('.bzr/merged-patches', ''),
 ('.bzr/pending-merged-patches', ''),
 ('.bzr/branch-name', ''),
 ('.bzr/branch-lock', ''),
 ('.bzr/pending-merges', ''),
 ('.bzr/inventory',
  '<inventory>\n'
  '<entry file_id="foo-20051004035605-91e788d1875603ae" kind="file" name="foo" />\n'
  '</inventory>\n'),
 ('.bzr/stat-cache',
  '### bzr hashcache v5\n'
  'foo// be9f309239729f69a6309e970ef24941d31e042c 13 1128398176 1128398176 303464 770\n'),
 ('.bzr/text-store/',),
 ('.bzr/text-store/foo-20051004035611-1591048e9dc7c2d4.gz',
  '\x1f\x8b\x08\x00[\xfdAC\x02\xff\xcb\xcc\xcb,\xc9L\xccQH\xce\xcf+I\xcd+)\xe6\x02\x00\xdd\xcc\xf90\x11\x00\x00\x00'),
 ('.bzr/text-store/foo-20051004035756-4081373d897c3453.gz',
  '\x1f\x8b\x08\x00\xc4\xfdAC\x02\xff\xcbK-WH\xce\xcf+I\xcd+)\xe6\x02\x00g\xc3\xdf\xc9\r\x00\x00\x00'),
 ('.bzr/inventory-store/',),
 ('.bzr/inventory-store/mbp@sourcefrog.net-20051004035611-176b16534b086b3c.gz',
  '\x1f\x8b\x08\x00[\xfdAC\x02\xffm\x8f\xcd\n\xc20\x10\x84\xef>E\xc8\xbdt7?M\x02\xad\xaf"\xa1\x99`P[\xa8E\xacOo\x14\x05\x0f\xdef\xe1\xfbv\x98\xbeL7L\xeb\xbcl\xfb]_\xc3\xb2\x89\\\xce8\x944\xc8<\xcf\x8d"\xb2LdH\xdb\x8el\x13\x18\xce\xfb\xc4\xde\xd5SGHq*\xd3\x0b\xad\x8e\x14S\xbc\xe0\xadI\xb1\xe2\xbe\xfe}\xc2\xdc\xb0\rL\xc6#\xa4\xd1\x8d*\x99\x0f}=F\x1e$8G\x9d\xa0\x02\xa1rP9\x01c`FV\xda1qg\x98"\x02}\xa5\xf2\xa8\x95\xec\xa4h\xeb\x80\xf6g\xcd\x13\xb3\x01\xcc\x98\xda\x00\x00\x00'),
 ('.bzr/inventory-store/mbp@sourcefrog.net-20051004035756-235f2b7dcdddd8dd.gz',
  '\x1f\x8b\x08\x00\xc4\xfdAC\x02\xffm\x8f\xc1\n\xc20\x10D\xef~E\xc8\xbd\xb8\x9bM\x9a,\xb4\xfe\x8a\xc4f\x83Am\xa1\x16\xb1~\xbdQ\x14<x\x9b\x81y3LW\xc6\x9b\x8c\xcb4\xaf\xbbMW\xc5\xbc\xaa\\\xce\xb2/\xa9\xd7y\x9a\x1a\x03\xe0\x10\xc0\x02\xb9\x16\\\xc3(>\x84\x84\xc1WKQ\xb4:\x95\xf1\x15\xad\x8cVc\xbc\xc8\x1b\xd3j\x91\xfb\xf2\xaf\xa4r\x8d\x85\x80\xe4)\x05\xf6\x03YG\x9f\xf4\xf5\x18\xb1\xd7\x07\xe1L\xc0\x86\xd8\x1b\xce-\xc7\xb6:a\x0f\x92\x8de\x8b\x89P\xc0\x9a\xe1\x0b\x95G\x9d\xc4\xda\xb1\xad\x07\xb6?o\x9e\xb5\xff\xf0\xf9\xda\x00\x00\x00'),
 ('.bzr/revision-store/',),
 ('.bzr/revision-store/mbp@sourcefrog.net-20051004035611-176b16534b086b3c.gz',
  '\x1f\x8b\x08\x00[\xfdAC\x02\xff\x9d\x8eKj\xc30\x14E\xe7^\x85\xd0 \xb3$\xefI\xd1\x8f\xd8\xa6\x1b(t\x07E?\xbb\x82H\n\xb2\x1ahW\xdfB1\x14:\xeb\xf4r\xee\xbdgl\xf1\x91\xb6T\x0b\xf15\xe7\xd4{l\x13}\xb6\xad\xa7B^j\xbd\x91\xc3\xad_\xb3\xbb?m\xf5\xbd\xf9\xb8\xb4\xba\x9eJ\xec\x87\xb5_)I\xe5\x11K\xaf\xed\xe35\x85\x89\xfe\xa5\x8e\x0c@ \xc0\x05\xb8\x90\x88GT\xd2\xa1\x14\xfc\xe2@K\xc7\xfd\xef\x85\xed\xcd\xe2D\x95\x8d\x1a\xa47<\x02c2\xb0 \xbc\xd0\x8ay\xa3\xbcp\x8a\x83\x12A3\xb7XJv\xef\x7f_\xf7\x94\xe3\xd6m\xbeO\x14\x91in4*<\x812\x88\xc60\xfc\x01>k\x89\x13\xe5\x12\x00\xe8<\x8c\xdf\x8d\xcd\xaeq\xb6!\x90\xa5\xd6\xf1\xbc\x07\xc3x\xde\x85\xe6\xe1\x0b\xc8\x8a\x98\x03T\x01\x00\x00'),
 ('.bzr/revision-store/mbp@sourcefrog.net-20051004035756-235f2b7dcdddd8dd.gz',
  '\x1f\x8b\x08\x00\xc4\xfdAC\x02\xff\x9d\x90Kj\x031\x0c\x86\xf79\xc5\xe0Ev\xe9\xc8o\x9b\xcc\x84^\xa0\xd0\x1b\x14\xbf&5d\xec`\xbb\x81\xf6\xf45\x84\xa4\x81\xaeZ\xa1\x85\x84^\xdf\xaf\xa9\x84K\xac1\xa7\xc1\xe5u\x8d\xad\x852\xa3\x17SZL\xc3k\xce\xa7a{j\xfb\xd5\x9e\x9fk\xfe(.,%\x1f\x9fRh\xdbc\xdb\xa3!\xa6KH-\x97\xcf\xb7\xe8g\xf4\xbbkG\x008\x06`@\xb9\xe4bG(_\x88\x95\xde\xf9n\xca\xfb\xc7\r\xf5\xdd\xe0\x19\xa9\x85)\x81\xf5"\xbd\x04j\xb8\x02b\xa8W\\\x0b\xc9\x14\xf4\xbc\xbb\xd7\xd6H4\xdc\xb8\xff}\xba\xc55\xd4f\xd6\xf3\x8c0&\x8ajE\xa4x\xe2@\xa5\xa6\x9a\xf3k\xc3WNaFT\x00\x00:l\xa6>Q\xcd1\x1cjp9\xf9;\xc34\xde\n\x9b\xe9lJWT{t\',a\xf9\x0b\xae\xc0x\x87\xa5\xb0Xp\xca,(a\xa9{\xd0{}\xd4\x12\x04(\xc5\xbb$\xc5$V\xceaI\x19\x01\xa2\x1dh\xed\x82d\x8c.\xccr@\xc3\xd8Q\xc6\x1f\xaa\xf1\xb6\xe8\xb0\xf9\x06QR\r\xf9\xfc\x01\x00\x00')]
