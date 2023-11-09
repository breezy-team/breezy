#    test_directory.py -- Testsuite for builddeb directory.py
#    Copyright (C) 2019 Jelmer Vernooij <jelmer@jelmer.uk>
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

from ....tests import TestCase
from ..directory import (
    fixup_broken_git_url,
    vcs_cvs_url_to_bzr_url,
    vcs_git_url_to_bzr_url,
    vcs_hg_url_to_bzr_url,
)


class VcsGitUrlToBzrUrlTests(TestCase):
    def test_preserves(self):
        self.assertEqual(
            "git://github.com/jelmer/dulwich",
            vcs_git_url_to_bzr_url("git://github.com/jelmer/dulwich"),
        )
        self.assertEqual(
            "https://github.com/jelmer/dulwich",
            vcs_git_url_to_bzr_url("https://github.com/jelmer/dulwich"),
        )

    def test_with_branch(self):
        self.assertEqual(
            "https://github.com/jelmer/dulwich,branch=foo",
            vcs_git_url_to_bzr_url("https://github.com/jelmer/dulwich -b foo"),
        )

    def test_with_subpath(self):
        self.assertEqual(
            "https://github.com/jelmer/dulwich/path",
            vcs_git_url_to_bzr_url("https://github.com/jelmer/dulwich [path]"),
        )
        self.assertEqual(
            "https://github.com/jelmer/dulwich,branch=foo/path",
            vcs_git_url_to_bzr_url("https://github.com/jelmer/dulwich -b foo [path]"),
        )

    def test_fixup(self):
        self.assertEqual(
            "git://github.com/jelmer/dulwich",
            vcs_git_url_to_bzr_url("git://github.com:jelmer/dulwich"),
        )


class FixUpGitUrlTests(TestCase):
    def test_salsa_not_https(self):
        self.assertEqual(
            "https://salsa.debian.org/jelmer/dulwich",
            fixup_broken_git_url("git://salsa.debian.org/jelmer/dulwich"),
        )

    def test_salsa_uses_cgit(self):
        self.assertEqual(
            "https://salsa.debian.org/jelmer/dulwich",
            fixup_broken_git_url("https://salsa.debian.org/cgit/jelmer/dulwich"),
        )


class VcsHgUrlToBzrUrlTests(TestCase):
    def test_preserves(self):
        self.assertEqual(
            "https://bitbucket.org/jelmer/dulwich",
            vcs_hg_url_to_bzr_url("https://bitbucket.org/jelmer/dulwich"),
        )

    def test_with_branch(self):
        self.assertEqual(
            "https://bitbucket.org/jelmer/dulwich,branch=foo",
            vcs_hg_url_to_bzr_url("https://bitbucket.org/jelmer/dulwich -b foo"),
        )


class VcsCvsUrlToBzrUrlTests(TestCase):
    def setUp(self):
        super().setUp()
        import breezy

        if breezy.version_info < (3, 1, 1):
            self.skipTest("version of breezy too old")

    def test_pserver(self):
        self.assertEqual(
            "cvs+pserver://anonymous@cvs.savannah.nongnu.org"
            "/cvsroot/fkt?module=debian/unstable",
            vcs_cvs_url_to_bzr_url(
                ":pserver:anonymous@cvs.savannah.nongnu.org:"
                "/cvsroot/fkt debian/unstable"
            ),
        )
        self.assertEqual(
            "cvs+pserver://anonymous@cvs.savannah.nongnu.org" "/cvsroot/fkt",
            vcs_cvs_url_to_bzr_url(
                ":pserver:anonymous@cvs.savannah.nongnu.org:" "/cvsroot/fkt"
            ),
        )
