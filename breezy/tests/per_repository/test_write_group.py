# Copyright (C) 2007-2011 Canonical Ltd
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

"""Tests for repository write groups."""

from breezy import (
    errors,
    )
from breezy.tests import (
    per_repository,
    test_server,
    )
from breezy.transport import memory


class TestWriteGroup(per_repository.TestCaseWithRepository):

    def test_start_write_group_unlocked_needs_write_lock(self):
        repo = self.make_repository('.')
        self.assertRaises(errors.NotWriteLocked, repo.start_write_group)

    def test_start_write_group_read_locked_needs_write_lock(self):
        repo = self.make_repository('.')
        with repo.lock_read():
            self.assertRaises(errors.NotWriteLocked, repo.start_write_group)

    def test_start_write_group_write_locked_gets_None(self):
        repo = self.make_repository('.')
        repo.lock_write()
        self.assertEqual(None, repo.start_write_group())
        repo.commit_write_group()
        repo.unlock()

    def test_start_write_group_twice_errors(self):
        repo = self.make_repository('.')
        repo.lock_write()
        repo.start_write_group()
        try:
            # don't need a specific exception for now - this is
            # really to be sure it's used right, not for signalling
            # semantic information.
            self.assertRaises(errors.BzrError, repo.start_write_group)
        finally:
            repo.commit_write_group()
            repo.unlock()

    def test_commit_write_group_does_not_error(self):
        repo = self.make_repository('.')
        repo.lock_write()
        repo.start_write_group()
        # commit_write_group can either return None (for repositories without
        # isolated transactions) or a hint for pack(). So we only check it
        # works in this interface test, because all repositories are exercised.
        repo.commit_write_group()
        repo.unlock()

    def test_unlock_in_write_group(self):
        repo = self.make_repository('.')
        repo.lock_write()
        repo.start_write_group()
        # don't need a specific exception for now - this is
        # really to be sure it's used right, not for signalling
        # semantic information.
        self.assertLogsError(errors.BzrError, repo.unlock)
        # after this error occurs, the repository is unlocked, and the write
        # group is gone.  you've had your chance, and you blew it. ;-)
        self.assertFalse(repo.is_locked())
        self.assertRaises(errors.BzrError, repo.commit_write_group)
        self.assertRaises(errors.BzrError, repo.unlock)

    def test_is_in_write_group(self):
        repo = self.make_repository('.')
        self.assertFalse(repo.is_in_write_group())
        repo.lock_write()
        repo.start_write_group()
        self.assertTrue(repo.is_in_write_group())
        repo.commit_write_group()
        self.assertFalse(repo.is_in_write_group())
        # abort also removes the in_write_group status.
        repo.start_write_group()
        self.assertTrue(repo.is_in_write_group())
        repo.abort_write_group()
        self.assertFalse(repo.is_in_write_group())
        repo.unlock()

    def test_abort_write_group_gets_None(self):
        repo = self.make_repository('.')
        repo.lock_write()
        repo.start_write_group()
        self.assertEqual(None, repo.abort_write_group())
        repo.unlock()

    def test_abort_write_group_does_not_raise_when_suppressed(self):
        if self.transport_server is test_server.LocalURLServer:
            self.transport_server = None
        self.vfs_transport_factory = memory.MemoryServer
        repo = self.make_repository('repo')
        token = repo.lock_write()
        self.addCleanup(repo.unlock)
        repo.start_write_group()
        # Damage the repository on the filesystem
        t = self.get_transport('')
        t.rename('repo', 'foo')
        self.addCleanup(t.rename, 'foo', 'repo')
        # abort_write_group will not raise an error, because either an
        # exception was not generated, or the exception was caught and
        # suppressed.  See also test_pack_repository's test of the same name.
        self.assertEqual(None, repo.abort_write_group(suppress_errors=True))
