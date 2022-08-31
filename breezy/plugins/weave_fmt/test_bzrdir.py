# Copyright (C) 2011, 2012, 2016 Canonical Ltd
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

"""Tests for the weave-era BzrDir formats.

For interface contract tests, see tests/per_bzr_dir.
"""

import os
import sys

from ... import (
    branch,
    controldir,
    errors,
    repository,
    upgrade,
    urlutils,
    workingtree,
    )
from ...bzr import (
    bzrdir,
    )
from ...osutils import (
    getcwd,
    )
from ...bzr.tests import test_bundle
from ...tests.test_sftp_transport import TestCaseWithSFTPServer
from ...tests import (
    TestCaseWithTransport,
    )

from .branch import (
    BzrBranchFormat4,
    )
from .bzrdir import (
    BzrDirFormat5,
    BzrDirFormat6,
    )


class TestFormat5(TestCaseWithTransport):
    """Tests specific to the version 5 bzrdir format."""

    def test_same_lockfiles_between_tree_repo_branch(self):
        # this checks that only a single lockfiles instance is created
        # for format 5 objects
        dir = BzrDirFormat5().initialize(self.get_url())

        def check_dir_components_use_same_lock(dir):
            ctrl_1 = dir.open_repository().control_files
            ctrl_2 = dir.open_branch().control_files
            ctrl_3 = dir.open_workingtree()._control_files
            self.assertTrue(ctrl_1 is ctrl_2)
            self.assertTrue(ctrl_2 is ctrl_3)
        check_dir_components_use_same_lock(dir)
        # and if we open it normally.
        dir = controldir.ControlDir.open(self.get_url())
        check_dir_components_use_same_lock(dir)

    def test_can_convert(self):
        # format 5 dirs are convertable
        dir = BzrDirFormat5().initialize(self.get_url())
        self.assertTrue(dir.can_convert_format())

    def test_needs_conversion(self):
        # format 5 dirs need a conversion if they are not the default,
        # and they aren't
        dir = BzrDirFormat5().initialize(self.get_url())
        # don't need to convert it to itself
        self.assertFalse(dir.needs_format_conversion(BzrDirFormat5()))
        # do need to convert it to the current default
        self.assertTrue(dir.needs_format_conversion(
            bzrdir.BzrDirFormat.get_default_format()))


class TestFormat6(TestCaseWithTransport):
    """Tests specific to the version 6 bzrdir format."""

    def test_same_lockfiles_between_tree_repo_branch(self):
        # this checks that only a single lockfiles instance is created
        # for format 6 objects
        dir = BzrDirFormat6().initialize(self.get_url())

        def check_dir_components_use_same_lock(dir):
            ctrl_1 = dir.open_repository().control_files
            ctrl_2 = dir.open_branch().control_files
            ctrl_3 = dir.open_workingtree()._control_files
            self.assertTrue(ctrl_1 is ctrl_2)
            self.assertTrue(ctrl_2 is ctrl_3)
        check_dir_components_use_same_lock(dir)
        # and if we open it normally.
        dir = controldir.ControlDir.open(self.get_url())
        check_dir_components_use_same_lock(dir)

    def test_can_convert(self):
        # format 6 dirs are convertable
        dir = BzrDirFormat6().initialize(self.get_url())
        self.assertTrue(dir.can_convert_format())

    def test_needs_conversion(self):
        # format 6 dirs need an conversion if they are not the default.
        dir = BzrDirFormat6().initialize(self.get_url())
        self.assertTrue(dir.needs_format_conversion(
            bzrdir.BzrDirFormat.get_default_format()))


class TestBreakLockOldBranch(TestCaseWithTransport):

    def test_break_lock_format_5_bzrdir(self):
        # break lock on a format 5 bzrdir should just return
        self.make_branch_and_tree('foo', format=BzrDirFormat5())
        out, err = self.run_bzr('break-lock foo')
        self.assertEqual('', out)
        self.assertEqual('', err)


_upgrade1_template = \
    [
        ('foo', b'new contents\n'),
        ('.bzr/',),
        ('.bzr/README',
         b'This is a Bazaar control directory.\n'
         b'Do not change any files in this directory.\n'
         b'See http://bazaar.canonical.com/ for more information about Bazaar.\n'),
        ('.bzr/branch-format', b'Bazaar-NG branch, format 0.0.4\n'),
        ('.bzr/revision-history',
         b'mbp@sourcefrog.net-20051004035611-176b16534b086b3c\n'
         b'mbp@sourcefrog.net-20051004035756-235f2b7dcdddd8dd\n'),
        ('.bzr/merged-patches', b''),
        ('.bzr/pending-merged-patches', b''),
        ('.bzr/branch-name', b''),
        ('.bzr/branch-lock', b''),
        ('.bzr/pending-merges', b''),
        ('.bzr/inventory',
         b'<inventory>\n'
         b'<entry file_id="foo-20051004035605-91e788d1875603ae" kind="file" name="foo" />\n'
         b'</inventory>\n'),
        ('.bzr/stat-cache',
         b'### bzr hashcache v5\n'
         b'foo// be9f309239729f69a6309e970ef24941d31e042c 13 1128398176 1128398176 303464 770\n'),
        ('.bzr/text-store/',),
        ('.bzr/text-store/foo-20051004035611-1591048e9dc7c2d4.gz',
         b'\x1f\x8b\x08\x00[\xfdAC\x02\xff\xcb\xcc\xcb,\xc9L\xccQH\xce\xcf+I\xcd+)\xe6\x02\x00\xdd\xcc\xf90\x11\x00\x00\x00'),
        ('.bzr/text-store/foo-20051004035756-4081373d897c3453.gz',
         b'\x1f\x8b\x08\x00\xc4\xfdAC\x02\xff\xcbK-WH\xce\xcf+I\xcd+)\xe6\x02\x00g\xc3\xdf\xc9\r\x00\x00\x00'),
        ('.bzr/inventory-store/',),
        ('.bzr/inventory-store/mbp@sourcefrog.net-20051004035611-176b16534b086b3c.gz',
         b'\x1f\x8b\x08\x00[\xfdAC\x02\xffm\x8f\xcd\n\xc20\x10\x84\xef>E\xc8\xbdt7?M\x02\xad\xaf"\xa1\x99`P[\xa8E\xacOo\x14\x05\x0f\xdef\xe1\xfbv\x98\xbeL7L\xeb\xbcl\xfb]_\xc3\xb2\x89\\\xce8\x944\xc8<\xcf\x8d"\xb2LdH\xdb\x8el\x13\x18\xce\xfb\xc4\xde\xd5SGHq*\xd3\x0b\xad\x8e\x14S\xbc\xe0\xadI\xb1\xe2\xbe\xfe}\xc2\xdc\xb0\rL\xc6#\xa4\xd1\x8d*\x99\x0f}=F\x1e$8G\x9d\xa0\x02\xa1rP9\x01c`FV\xda1qg\x98"\x02}\xa5\xf2\xa8\x95\xec\xa4h\xeb\x80\xf6g\xcd\x13\xb3\x01\xcc\x98\xda\x00\x00\x00'),
        ('.bzr/inventory-store/mbp@sourcefrog.net-20051004035756-235f2b7dcdddd8dd.gz',
         b'\x1f\x8b\x08\x00\xc4\xfdAC\x02\xffm\x8f\xc1\n\xc20\x10D\xef~E\xc8\xbd\xb8\x9bM\x9a,\xb4\xfe\x8a\xc4f\x83Am\xa1\x16\xb1~\xbdQ\x14<x\x9b\x81y3LW\xc6\x9b\x8c\xcb4\xaf\xbbMW\xc5\xbc\xaa\\\xce\xb2/\xa9\xd7y\x9a\x1a\x03\xe0\x10\xc0\x02\xb9\x16\\\xc3(>\x84\x84\xc1WKQ\xb4:\x95\xf1\x15\xad\x8cVc\xbc\xc8\x1b\xd3j\x91\xfb\xf2\xaf\xa4r\x8d\x85\x80\xe4)\x05\xf6\x03YG\x9f\xf4\xf5\x18\xb1\xd7\x07\xe1L\xc0\x86\xd8\x1b\xce-\xc7\xb6:a\x0f\x92\x8de\x8b\x89P\xc0\x9a\xe1\x0b\x95G\x9d\xc4\xda\xb1\xad\x07\xb6?o\x9e\xb5\xff\xf0\xf9\xda\x00\x00\x00'),
        ('.bzr/revision-store/',),
        ('.bzr/revision-store/mbp@sourcefrog.net-20051004035611-176b16534b086b3c.gz',
         b'\x1f\x8b\x08\x00[\xfdAC\x02\xff\x9d\x8eKj\xc30\x14E\xe7^\x85\xd0 \xb3$\xefI\xd1\x8f\xd8\xa6\x1b(t\x07E?\xbb\x82H\n\xb2\x1ahW\xdfB1\x14:\xeb\xf4r\xee\xbdgl\xf1\x91\xb6T\x0b\xf15\xe7\xd4{l\x13}\xb6\xad\xa7B^j\xbd\x91\xc3\xad_\xb3\xbb?m\xf5\xbd\xf9\xb8\xb4\xba\x9eJ\xec\x87\xb5_)I\xe5\x11K\xaf\xed\xe35\x85\x89\xfe\xa5\x8e\x0c@ \xc0\x05\xb8\x90\x88GT\xd2\xa1\x14\xfc\xe2@K\xc7\xfd\xef\x85\xed\xcd\xe2D\x95\x8d\x1a\xa47<\x02c2\xb0 \xbc\xd0\x8ay\xa3\xbcp\x8a\x83\x12A3\xb7XJv\xef\x7f_\xf7\x94\xe3\xd6m\xbeO\x14\x91in4*<\x812\x88\xc60\xfc\x01>k\x89\x13\xe5\x12\x00\xe8<\x8c\xdf\x8d\xcd\xaeq\xb6!\x90\xa5\xd6\xf1\xbc\x07\xc3x\xde\x85\xe6\xe1\x0b\xc8\x8a\x98\x03T\x01\x00\x00'),
        ('.bzr/revision-store/mbp@sourcefrog.net-20051004035756-235f2b7dcdddd8dd.gz',
         b'\x1f\x8b\x08\x00\xc4\xfdAC\x02\xff\x9d\x90Kj\x031\x0c\x86\xf79\xc5\xe0Ev\xe9\xc8o\x9b\xcc\x84^\xa0\xd0\x1b\x14\xbf&5d\xec`\xbb\x81\xf6\xf45\x84\xa4\x81\xaeZ\xa1\x85\x84^\xdf\xaf\xa9\x84K\xac1\xa7\xc1\xe5u\x8d\xad\x852\xa3\x17SZL\xc3k\xce\xa7a{j\xfb\xd5\x9e\x9fk\xfe(.,%\x1f\x9fRh\xdbc\xdb\xa3!\xa6KH-\x97\xcf\xb7\xe8g\xf4\xbbkG\x008\x06`@\xb9\xe4bG(_\x88\x95\xde\xf9n\xca\xfb\xc7\r\xf5\xdd\xe0\x19\xa9\x85)\x81\xf5"\xbd\x04j\xb8\x02b\xa8W\\\x0b\xc9\x14\xf4\xbc\xbb\xd7\xd6H4\xdc\xb8\xff}\xba\xc55\xd4f\xd6\xf3\x8c0&\x8ajE\xa4x\xe2@\xa5\xa6\x9a\xf3k\xc3WNaFT\x00\x00:l\xa6>Q\xcd1\x1cjp9\xf9;\xc34\xde\n\x9b\xe9lJWT{t\',a\xf9\x0b\xae\xc0x\x87\xa5\xb0Xp\xca,(a\xa9{\xd0{}\xd4\x12\x04(\xc5\xbb$\xc5$V\xceaI\x19\x01\xa2\x1dh\xed\x82d\x8c.\xccr@\xc3\xd8Q\xc6\x1f\xaa\xf1\xb6\xe8\xb0\xf9\x06QR\r\xf9\xfc\x01\x00\x00')]


_ghost_template = [
    ('./foo',
        b'hello\n'
     ),
    ('./.bzr/', ),
    ('./.bzr/README',
     b'This is a Bazaar control directory.\n'
     b'Do not change any files in this directory.\n'
     b'See http://bazaar.canonical.com/ for more information about Bazaar.\n'
     ),
    ('./.bzr/branch-format',
        b'Bazaar-NG branch, format 0.0.4\n'
     ),
    ('./.bzr/branch-lock',
        b''
     ),
    ('./.bzr/branch-name',
        b''
     ),
    ('./.bzr/inventory',
        b'<inventory>\n'
        b'<entry file_id="foo-20051004104918-0379cb7c76354cde" kind="file" name="foo" />\n'
        b'</inventory>\n'
     ),
    ('./.bzr/merged-patches',
        b''
     ),
    ('./.bzr/pending-merged-patches',
        b''
     ),
    ('./.bzr/pending-merges',
        b''
     ),
    ('./.bzr/revision-history',
        b'mbp@sourcefrog.net-20051004104921-a98be2278dd30b7b\n'
        b'mbp@sourcefrog.net-20051004104937-c9b7a7bfcc0bb22d\n'
     ),
    ('./.bzr/stat-cache',
        b'### bzr hashcache v5\n'
        b'foo// f572d396fae9206628714fb2ce00f72e94f2258f 6 1128422956 1128422956 306900 770\n'
     ),
    ('./.bzr/text-store/', ),
    ('./.bzr/text-store/foo-20051004104921-8de8118a71be45ba.gz',
        b'\x1f\x8b\x08\x081^BC\x00\x03foo-20051004104921-8de8118a71be45ba\x00\xcbH\xcd\xc9\xc9\xe7\x02\x00 0:6\x06\x00\x00\x00'
     ),
    ('./.bzr/inventory-store/', ),
    ('./.bzr/inventory-store/mbp@sourcefrog.net-20051004104921-a98be2278dd30b7b.gz',
        b'\x1f\x8b\x08\x081^BC\x00\x03mbp@sourcefrog.net-20051004104921-a98be2278dd30b7b\x00m\x8f\xcb\n'
        b'\xc20\x10E\xf7~E\xc8\xbe83\xcd\x13\xaa\xbf"yL0\xa8-\xd4"\xd6\xaf7\x8a\x82\x0bw\xb38\xe7\xde;C\x1do<.\xd3\xbc\xee7C;\xe6U\x94z\xe6C\xcd;Y\xa6\xa9#\x00\x8d\x00\n'
        b'Ayt\x1d\xf4\xd6\xa7h\x935\xbdV)\xb3\x14\xa7:\xbe\xd0\xe6H1\x86\x0b\xbf5)\x16\xbe/\x7fC\x08;\x97\xd9!\xba`1\xb2\xd21|\xe8\xeb1`\xe3\xb5\xa5\xdc{S\x02{\x02c\xc8YT%Rb\x80b\x89\xbd*D\xda\x95\xafT\x1f\xad\xd2H\xb1m\xfb\xb7?\xcf<\x01W}\xb5\x8b\xd9\x00\x00\x00'
     ),
    ('./.bzr/inventory-store/mbp@sourcefrog.net-20051004104937-c9b7a7bfcc0bb22d.gz',
        b'\x1f\x8b\x08\x08A^BC\x00\x03mbp@sourcefrog.net-20051004104937-c9b7a7bfcc0bb22d\x00m\x8f\xcb\n'
        b'\xc20\x10E\xf7~E\xc8\xbe83\xcd\x13\xaa\xbf"yL0\xa8-\xd4"\xd6\xaf7\x8a\x82\x0bw\xb38\xe7\xde;C\x1do<.\xd3\xbc\xee7C;\xe6U\x94z\xe6C\xcd;Y\xa6\xa9#\x00\x8d\x00\n'
        b'Ayt\x1d\xf4\xd6\xa7h\x935\xbdV)\xb3\x14\xa7:\xbe\xd0\xe6H1\x86\x0b\xbf5)\x16\xbe/\x7fC\x08;\x97\xd9!\xba`1\xb2\xd21|\xe8\xeb1`\xe3\xb5\xa5\xdc{S\x02{\x02c\xc8YT%Rb\x80b\x89\xbd*D\xda\x95\xafT\x1f\xad\xd2H\xb1m\xfb\xb7?\xcf<\x01W}\xb5\x8b\xd9\x00\x00\x00'
     ),
    ('./.bzr/revision-store/', ),
    ('./.bzr/revision-store/mbp@sourcefrog.net-20051004104921-a98be2278dd30b7b.gz',
        b'\x1f\x8b\x08\x081^BC\x00\x03mbp@sourcefrog.net-20051004104921-a98be2278dd30b7b\x00\x9d\x8eMj\xc30\x14\x84\xf7>\x85\xd0"\xbb$\xef\xc9\xb6,\x11\xdb\xf4\x02\x85\xde\xa0\xe8\xe7\xd9\x11\xc4R\x90\xd4@{\xfa\x06\x8a\xa1\xd0]\x97\x03\xdf\xcc|c\xa6G(!E\xe6\xd2\xb6\x85Z)O\xfc\xd5\xe4\x1a"{K\xe9\xc6\x0e\xb7z\xd9\xec\xfd\xa5\xa4\x8f\xech\xc9i=E\xaa\x87\xb5^8\x0b\xf1A\xb1\xa6\xfc\xf9\x1e\xfc\xc4\xffRG\x01\xd0#@\x87\xd0i\x81G\xa3\x95%!\x06\xe5}\x0bv\xb0\xbf\x17\xca\xd5\xe0\xc4-\xa0\xb1\x8b\xb6`\xc0I\xa4\xc5\xf4\x9el\xef\x95v [\x94\xcf\x8e\xd5\xcay\xe4l\xf7\xfe\xf7u\r'
        b'\x1b\x95j\xb6\xfb\xc4\x11\x85\xea\x84\xd0\x12O\x03t\x83D\xad\xc4\x0f\xf0\x95"M\xbc\x95\x00\xc0\xe7f|6\x8aYi^B.u<\xef\xb1\x19\xcf\xbb\xce\xdc|\x038=\xc7\xe6R\x01\x00\x00'
     ),
    ('./.bzr/revision-store/mbp@sourcefrog.net-20051004104937-c9b7a7bfcc0bb22d.gz',
        b'\x1f\x8b\x08\x08A^BC\x00\x03mbp@sourcefrog.net-20051004104937-c9b7a7bfcc0bb22d\x00\x9d\x90\xc1j\xc30\x0c\x86\xef}\n'
        b"\xe3Coie'\xb1c\x9a\x94\xbe\xc0`o0,[N\x03M\\\x1c\xafe{\xfae\x94n\x85\xc1`;Y\x88O\xd2\xff\xb9Mt\x19\xe6!N\xcc\xc5q\x1cr\xa6\xd4\xf1'\x9b\xf20\xb1\xe7\x18Ol}\xca\xbb\x11\xcf\x879\xbe&G!\xc5~3Q^\xf7y\xc7\xd90]h\xca1\xbd\xbd\x0c\xbe\xe3?\xa9B\x02\xd4\x02\xa0\x12P\x99R\x17\xce\xa0\xb6\x1a\x83s\x80(\xa5\x7f\xdc0\x1f\xad\xe88\x82\xb0\x18\x0c\x82\x05\xa7\x04\x05[{\xc2\xda7\xc6\x81*\x85B\x8dh\x1a\xe7\x05g\xf7\xdc\xff>\x9d\x87\x91\xe6l\xc7s\xc7\x85\x90M%\xa5\xd1z#\x85\xa8\x9b\x1a\xaa\xfa\x06\xbc\xc7\x89:^*\x00\xe0\xfbU\xbbL\xcc\xb6\xa7\xfdH\xa9'\x16\x03\xeb\x8fq\xce\xed\xf6\xde_\xb5g\x9b\x16\xa1y\xa9\xbe\x02&\n"
        b'\x7fJ+EaM\x83$\xa5n\xbc/a\x91~\xd0\xbd\xfd\x135\n'
        b'\xd0\x9a`\x0c*W\x1aR\xc1\x94du\x08(\t\xb0\x91\xdeZ\xa3\x9cU\x9cm\x7f\x8dr\x1d\x10Ot\xb8\xc6\xcf\xa7\x907|\xfb-\xb1\xbd\xd3\xfb\xd5\x07\xeeD\xee\x08*\x02\x00\x00'
     ),
]

_upgrade_dir_template = [
    ('./.bzr/', ),
    ('./.bzr/README',
     b'This is a Bazaar control directory.\n'
     b'Do not change any files in this directory.\n'
     b'See http://bazaar.canonical.com/ for more information about Bazaar.\n'
     ),
    ('./.bzr/branch-format',
        b'Bazaar-NG branch, format 0.0.4\n'
     ),
    ('./.bzr/branch-lock',
        b''
     ),
    ('./.bzr/branch-name',
        b''
     ),
    ('./.bzr/inventory',
        b'<inventory>\n'
        b'<entry file_id="dir-20051005095101-da1441ea3fa6917a" kind="directory" name="dir" />\n'
        b'</inventory>\n'
     ),
    ('./.bzr/merged-patches',
        b''
     ),
    ('./.bzr/pending-merged-patches',
        b''
     ),
    ('./.bzr/pending-merges',
        b''
     ),
    ('./.bzr/revision-history',
        b'robertc@robertcollins.net-20051005095108-6065fbd8e7d8617e\n'
     ),
    ('./.bzr/stat-cache',
        b'### bzr hashcache v5\n'
     ),
    ('./.bzr/text-store/', ),
    ('./.bzr/inventory-store/', ),
    ('./.bzr/inventory-store/robertc@robertcollins.net-20051005095108-6065fbd8e7d8617e.gz',
        b'\x1f\x8b\x08\x00\x0c\xa2CC\x02\xff\xb3\xc9\xcc+K\xcd+\xc9/\xaa\xb4\xe3\xb2\x012\x8a*\x15\xd22sR\xe33Sl\x95R2\x8bt\x8d\x0c\x0cL\r'
        b"\x81\xd8\xc0\x12H\x19\xea\xa6$\x1a\x9a\x98\x18\xa6&\x1a\xa7%\x9aY\x1a\x9a'*)dg\xe6A\x94\xa6&\x83LQR\xc8K\xccM\x05\x0b()\xe8\x03\xcd\xd4G\xb2\x00\x00\xc2<\x94\xb1m\x00\x00\x00"
     ),
    ('./.bzr/revision-store/', ),
    ('./.bzr/revision-store/robertc@robertcollins.net-20051005095108-6065fbd8e7d8617e.gz',
        b'\x1f\x8b\x08\x00\x0c\xa2CC\x02\xff\xa5OKj\xc30\x14\xdc\xfb\x14B\x8b\xec\x92<I\xd6\xc7\xc42\x85\xde\xa0\x17(\xb6\xf4\x9c\n'
        b'l\xa9H"\x90\x9c\xbe\xa6\xa9\xa1\x9b\xae\xbax\x0c\xcc\xe71\xd3g\xbc\x85\x12R$.\xadk\xa8\x15\xb3\xa5oi\xc2\\\xc9kZ\x96\x10\x0b9,\xf5\x92\xbf)\xf7\xf2\x83O\xe5\x14\xb1\x1e\xae\xf5BI\x887\x8c5\xe5\xfb{\xf0\x96\xfei>r\x00\xc9\xb6\x83n\x03sT\xa0\xe4<y\x83\xda\x1b\xc54\xfe~T>Ff\xe9\xcc:\xdd\x8e\xa6E\xc7@\xa2\x82I\xaaNL\xbas\\313)\x00\xb9\xe6\xe0(\xd9\x87\xfc\xb7A\r'
        b"+\x96:\xae\x9f\x962\xc6\x8d\x04i\x949\x01\x97R\xb7\x1d\x17O\xc3#E\xb4T(\x00\xa0C\xd3o\x892^q\x18\xbd'>\xe4\xfe\xbc\x13M\x7f\xde{\r"
        b'\xcd\x17\x85\xea\xba\x03l\x01\x00\x00'
     ),
    ('./dir/', ),
]


class TestUpgrade(TestCaseWithTransport):

    def test_upgrade_v6_to_meta_no_workingtree(self):
        # Some format6 branches do not have checkout files. Upgrading
        # such a branch to metadir must not setup a working tree.
        self.build_tree_contents(_upgrade1_template)
        upgrade.upgrade('.', BzrDirFormat6())
        t = self.get_transport('.')
        t.delete('.bzr/pending-merges')
        t.delete('.bzr/inventory')
        self.assertFalse(t.has('.bzr/stat-cache'))
        t.delete_tree('backup.bzr.~1~')
        # At this point, we have a format6 branch without checkout files.
        upgrade.upgrade('.', bzrdir.BzrDirMetaFormat1())
        # The upgrade should not have set up a working tree.
        control = controldir.ControlDir.open('.')
        self.assertFalse(control.has_workingtree())
        # We have covered the scope of this test, we may as well check that
        # upgrade has not eaten our data, even if it's a bit redundant with
        # other tests.
        self.assertIsInstance(control._format, bzrdir.BzrDirMetaFormat1)
        b = control.open_branch()
        self.addCleanup(b.lock_read().unlock)
        self.assertEqual(b._revision_history(),
                         [b'mbp@sourcefrog.net-20051004035611-176b16534b086b3c',
                          b'mbp@sourcefrog.net-20051004035756-235f2b7dcdddd8dd'])

    def test_upgrade_simple(self):
        """Upgrade simple v0.0.4 format to latest format"""
        eq = self.assertEqual
        self.build_tree_contents(_upgrade1_template)
        upgrade.upgrade(u'.')
        control = controldir.ControlDir.open('.')
        b = control.open_branch()
        # tsk, peeking under the covers.
        self.assertIsInstance(
            control._format,
            bzrdir.BzrDirFormat.get_default_format().__class__)
        self.addCleanup(b.lock_read().unlock)
        rh = b._revision_history()
        eq(rh,
           [b'mbp@sourcefrog.net-20051004035611-176b16534b086b3c',
            b'mbp@sourcefrog.net-20051004035756-235f2b7dcdddd8dd'])
        rt = b.repository.revision_tree(rh[0])
        foo_id = b'foo-20051004035605-91e788d1875603ae'
        with rt.lock_read():
            eq(rt.get_file_text('foo'), b'initial contents\n')
        rt = b.repository.revision_tree(rh[1])
        with rt.lock_read():
            eq(rt.get_file_text('foo'), b'new contents\n')
        # check a backup was made:
        backup_dir = 'backup.bzr.~1~'
        t = self.get_transport('.')
        t.stat(backup_dir)
        t.stat(backup_dir + '/README')
        t.stat(backup_dir + '/branch-format')
        t.stat(backup_dir + '/revision-history')
        t.stat(backup_dir + '/merged-patches')
        t.stat(backup_dir + '/pending-merged-patches')
        t.stat(backup_dir + '/pending-merges')
        t.stat(backup_dir + '/branch-name')
        t.stat(backup_dir + '/branch-lock')
        t.stat(backup_dir + '/inventory')
        t.stat(backup_dir + '/stat-cache')
        t.stat(backup_dir + '/text-store')
        t.stat(backup_dir + '/text-store/foo-20051004035611-1591048e9dc7c2d4.gz')
        t.stat(backup_dir + '/text-store/foo-20051004035756-4081373d897c3453.gz')
        t.stat(backup_dir + '/inventory-store/')
        t.stat(
            backup_dir + '/inventory-store/mbp@sourcefrog.net-20051004035611-176b16534b086b3c.gz')
        t.stat(
            backup_dir + '/inventory-store/mbp@sourcefrog.net-20051004035756-235f2b7dcdddd8dd.gz')
        t.stat(backup_dir + '/revision-store/')
        t.stat(
            backup_dir + '/revision-store/mbp@sourcefrog.net-20051004035611-176b16534b086b3c.gz')
        t.stat(
            backup_dir + '/revision-store/mbp@sourcefrog.net-20051004035756-235f2b7dcdddd8dd.gz')

    def test_upgrade_with_ghosts(self):
        """Upgrade v0.0.4 tree containing ghost references.

        That is, some of the parents of revisions mentioned in the branch
        aren't present in the branch's storage.

        This shouldn't normally happen in branches created entirely in
        bzr, but can happen in branches imported from baz and arch, or from
        other systems, where the importer knows about a revision but not
        its contents."""
        eq = self.assertEqual
        self.build_tree_contents(_ghost_template)
        upgrade.upgrade(u'.')
        b = branch.Branch.open(u'.')
        self.addCleanup(b.lock_read().unlock)
        revision_id = b._revision_history()[1]
        rev = b.repository.get_revision(revision_id)
        eq(len(rev.parent_ids), 2)
        eq(rev.parent_ids[1], b'wibble@wobble-2')

    def test_upgrade_makes_dir_weaves(self):
        self.build_tree_contents(_upgrade_dir_template)
        old_repodir = controldir.ControlDir.open_unsupported('.')
        old_repo_format = old_repodir.open_repository()._format
        upgrade.upgrade('.')
        # this is the path to the literal file. As format changes
        # occur it needs to be updated. FIXME: ask the store for the
        # path.
        repo = repository.Repository.open('.')
        # it should have changed the format
        self.assertNotEqual(old_repo_format.__class__, repo._format.__class__)
        # and we should be able to read the names for the file id
        # 'dir-20051005095101-da1441ea3fa6917a'
        repo.lock_read()
        self.addCleanup(repo.unlock)
        text_keys = repo.texts.keys()
        dir_keys = [key for key in text_keys if key[0] ==
                    b'dir-20051005095101-da1441ea3fa6917a']
        self.assertNotEqual([], dir_keys)

    def test_upgrade_to_meta_sets_workingtree_last_revision(self):
        self.build_tree_contents(_upgrade_dir_template)
        upgrade.upgrade('.', bzrdir.BzrDirMetaFormat1())
        tree = workingtree.WorkingTree.open('.')
        self.addCleanup(tree.lock_read().unlock)
        self.assertEqual([tree.branch._revision_history()[-1]],
                         tree.get_parent_ids())


class SFTPBranchTest(TestCaseWithSFTPServer):
    """Test some stuff when accessing a bzr Branch over sftp"""

    def test_lock_file(self):
        # old format branches use a special lock file on sftp.
        b = self.make_branch('', format=BzrDirFormat6())
        b = branch.Branch.open(self.get_url())
        self.assertPathExists('.bzr/')
        self.assertPathExists('.bzr/branch-format')
        self.assertPathExists('.bzr/branch-lock')

        self.assertPathDoesNotExist('.bzr/branch-lock.write-lock')
        b.lock_write()
        self.assertPathExists('.bzr/branch-lock.write-lock')
        b.unlock()
        self.assertPathDoesNotExist('.bzr/branch-lock.write-lock')


class TestInfo(TestCaseWithTransport):

    def test_info_locking_oslocks(self):
        if sys.platform == "win32":
            self.skip("don't use oslocks on win32 in unix manner")
        # This test tests old (all-in-one, OS lock using) behaviour which
        # simply cannot work on windows (and is indeed why we changed our
        # design. As such, don't try to remove the thisFailsStrictLockCheck
        # call here.
        self.thisFailsStrictLockCheck()

        tree = self.make_branch_and_tree('branch',
                                         format=BzrDirFormat6())

        # Test all permutations of locking the working tree, branch and repository
        # XXX: Well not yet, as we can't query oslocks yet. Currently, it's
        # implemented by raising NotImplementedError and get_physical_lock_status()
        # always returns false. This makes bzr info hide the lock status.  (Olaf)
        # W B R

        # U U U
        out, err = self.run_bzr('info -v branch')
        self.assertEqualDiff(
            """Standalone tree (format: weave)
Location:
  branch root: %s

Format:
       control: All-in-one format 6
  working tree: Working tree format 2
        branch: Branch format 4
    repository: %s

In the working tree:
         0 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 copied
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         0 revisions

Repository:
         0 revisions
""" % ('branch', tree.branch.repository._format.get_format_description(),
       ), out)
        self.assertEqual('', err)
        # L L L
        tree.lock_write()
        out, err = self.run_bzr('info -v branch')
        self.assertEqualDiff(
            """Standalone tree (format: weave)
Location:
  branch root: %s

Format:
       control: All-in-one format 6
  working tree: Working tree format 2
        branch: Branch format 4
    repository: %s

In the working tree:
         0 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 copied
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         0 revisions

Repository:
         0 revisions
""" % ('branch', tree.branch.repository._format.get_format_description(),
       ), out)
        self.assertEqual('', err)
        tree.unlock()


class TestBranchFormat4(TestCaseWithTransport):
    """Tests specific to branch format 4"""

    def test_no_metadir_support(self):
        url = self.get_url()
        bdir = bzrdir.BzrDirMetaFormat1().initialize(url)
        bdir.create_repository()
        self.assertRaises(errors.IncompatibleFormat,
                          BzrBranchFormat4().initialize, bdir)

    def test_supports_bzrdir_6(self):
        url = self.get_url()
        bdir = BzrDirFormat6().initialize(url)
        bdir.create_repository()
        BzrBranchFormat4().initialize(bdir)


class TestBoundBranch(TestCaseWithTransport):

    def setUp(self):
        super(TestBoundBranch, self).setUp()
        self.build_tree(['master/', 'child/'])
        self.make_branch_and_tree('master')
        self.make_branch_and_tree('child',
                                  format=controldir.format_registry.make_controldir('weave'))
        os.chdir('child')

    def test_bind_format_6_bzrdir(self):
        # bind on a format 6 bzrdir should error
        out, err = self.run_bzr('bind ../master', retcode=3)
        self.assertEqual('', out)
        # TODO: jam 20060427 Probably something like this really should
        #       print out the actual path, rather than the URL
        cwd = urlutils.local_path_to_url(getcwd())
        self.assertEqual(
            'brz: ERROR: Branch at %s/ does not support binding.\n' % cwd, err)

    def test_unbind_format_6_bzrdir(self):
        # bind on a format 6 bzrdir should error
        out, err = self.run_bzr('unbind', retcode=3)
        self.assertEqual('', out)
        cwd = urlutils.local_path_to_url(getcwd())
        self.assertEqual('brz: ERROR: To use this feature you must '
                         'upgrade your branch at %s/.\n' % cwd, err)


class TestInit(TestCaseWithTransport):

    def test_init_weave(self):
        # --format=weave should be accepted to allow interoperation with
        # old releases when desired.
        out, err = self.run_bzr('init --format=weave')
        self.assertEqual("""Created a standalone tree (format: weave)\n""",
                         out)
        self.assertEqual('', err)


class V4WeaveBundleTester(test_bundle.V4BundleTester):

    def bzrdir_format(self):
        return 'metaweave'
