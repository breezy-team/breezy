# Copyright (C) 2008 Canonical Ltd
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

"""Tests for repositories that support CHK indices."""

from bzrlib.versionedfile import VersionedFiles
from bzrlib.tests.per_repository_chk import TestCaseWithRepositoryCHK


class TestCHKSupport(TestCaseWithRepositoryCHK):

    def test_chk_bytes_attribute_is_VersionedFiles(self):
        repo = self.make_repository('.')
        self.assertIsInstance(repo.chk_bytes, VersionedFiles)

    def test_add_bytes_to_chk_bytes_store(self):
        repo = self.make_repository('.')
        repo.lock_write()
        try:
            repo.start_write_group()
            try:
                sha1, len, _ = repo.chk_bytes.add_lines((None,),
                    None, ["foo\n", "bar\n"], random_id=True)
                self.assertEqual('4e48e2c9a3d2ca8a708cb0cc545700544efb5021',
                    sha1)
                self.assertEqual(
                    set([('sha1:4e48e2c9a3d2ca8a708cb0cc545700544efb5021',)]),
                    repo.chk_bytes.keys())
            except:
                repo.abort_write_group()
                raise
            else:
                repo.commit_write_group()
        finally:
            repo.unlock()
        # And after an unlock/lock pair
        repo.lock_read()
        try:
            self.assertEqual(
                set([('sha1:4e48e2c9a3d2ca8a708cb0cc545700544efb5021',)]),
                repo.chk_bytes.keys())
        finally:
            repo.unlock()
        # and reopening
        repo = repo.bzrdir.open_repository()
        repo.lock_read()
        try:
            self.assertEqual(
                set([('sha1:4e48e2c9a3d2ca8a708cb0cc545700544efb5021',)]),
                repo.chk_bytes.keys())
        finally:
            repo.unlock()

    def test_pack_preserves_chk_bytes_store(self):
        repo = self.make_repository('.')
        repo.lock_write()
        try:
            repo.start_write_group()
            try:
                repo.chk_bytes.add_lines((None,), None, ["chkroot:\n"],
                    random_id=True)
            except:
                repo.abort_write_group()
                raise
            else:
                repo.commit_write_group()
            repo.start_write_group()
            try:
                repo.chk_bytes.add_lines((None,), None, ["chkvalue:\n"],
                    random_id=True)
            except:
                repo.abort_write_group()
                raise
            else:
                repo.commit_write_group()
            repo.pack()
            self.assertEqual(
                set([('sha1:062ef095245d8617d7671e50a71b529d13d93022',),
                    ('sha1:572d8da882e1ebf0f50f1e2da2d7a9cadadf4db5',)]),
                repo.chk_bytes.keys())
        finally:
            repo.unlock()
        # and reopening
        repo = repo.bzrdir.open_repository()
        repo.lock_read()
        try:
            self.assertEqual(
                set([('sha1:062ef095245d8617d7671e50a71b529d13d93022',),
                    ('sha1:572d8da882e1ebf0f50f1e2da2d7a9cadadf4db5',)]),
                repo.chk_bytes.keys())
        finally:
            repo.unlock()
