# Copyright (C) 2007 Canonical Ltd
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
#

"""Tests of the 'bzr pack' command."""

from bzrlib.tests.blackbox import ExternalBase


class TestPack(ExternalBase):
        
    def test_pack_silent(self):
        """pack command has no intrinsic output."""
        self.make_branch('.')
        out, err = self.run_bzr('pack')
        self.assertEqual('', out)
        self.assertEqual('', err)

    def test_pack_accepts_branch_url(self):
        """pack command accepts the url to a branch."""
        self.make_branch('branch')
        out, err = self.run_bzr('pack branch')
        self.assertEqual('', out)
        self.assertEqual('', err)

    def test_pack_accepts_repo_url(self):
        """pack command accepts the url to a branch."""
        self.make_repository('repository')
        out, err = self.run_bzr('pack repository')
        self.assertEqual('', out)
        self.assertEqual('', err)
