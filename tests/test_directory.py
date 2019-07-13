#    test_directory.py -- Testsuite for builddeb directory.py
#    Copyright (C) 2019 Jelmer Vernooĳ <jelmer@jelmer.uk>
#    
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

from __future__ import absolute_import

from ....tests import TestCase

from ..directory import (
    vcs_git_url_to_bzr_url,
    )


class VcsGitUrlToBzrUrlTests(TestCase):

    def test_preserves(self):
        self.assertEqual(
            'git://github.com/jelmer/dulwich',
            vcs_git_url_to_bzr_url('git://github.com/jelmer/dulwich'))
        self.assertEqual(
            'https://github.com/jelmer/dulwich',
            vcs_git_url_to_bzr_url('https://github.com/jelmer/dulwich'))

    def test_with_branch(self):
        self.assertEqual(
            'https://github.com/jelmer/dulwich,branch=foo',
            vcs_git_url_to_bzr_url('https://github.com/jelmer/dulwich -b foo'))
