# Copyright (C) 2007, 2009, 2010 Canonical Ltd
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
#

"""Tests of the 'bzr pack' command."""
import os

from bzrlib import tests


class TestPack(tests.TestCaseWithTransport):

    def _make_versioned_file(self, path, line_prefix='line', total_lines=10):
        self._make_file(path, line_prefix, total_lines, versioned=True)

    def _make_file(self, path, line_prefix, total_lines, versioned):
        text=''
        for i in range(total_lines):
            text += line_prefix + str(i+1) + "\n"

        open(path, 'w').write(text)
        if versioned:
            self.run_bzr(['add', path])
            self.run_bzr(['ci', '-m', '"' + path + '"'])

    def _update_file(self, path, text, checkin=True):
        """append text to file 'path' and check it in"""
        open(path, 'a').write(text)
        if checkin:
            self.run_bzr(['ci', path, '-m', '"' + path + '"'])

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

    def test_pack_clean_obsolete_packs(self):
        """Ensure --clean-obsolete-packs removes obsolete pack files
        """
        wd = 'foobar0'
        wt = self.make_branch_and_tree(wd)
        transport = wt.branch.repository.bzrdir.transport
        os.chdir(wd)

        # do multiple commits to ensure that obsolete packs are created
        # by 'bzr pack'
        self._make_versioned_file('file0.txt')
        for i in range(5):
            self._update_file('file0.txt', 'HELLO %d\n' % i)

        out, err = self.run_bzr(['pack', '--clean-obsolete-packs'])

        pack_names = transport.list_dir('repository/obsolete_packs')
        self.assertTrue(len(pack_names) == 0)
