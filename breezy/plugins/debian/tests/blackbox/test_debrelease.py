#    test_debrelease.py -- Blackbox tests for debrelease.
#    Copyright (C) 2011 Canonical Ltd.
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


"""Blackbox tests for "bzr debrelease"."""

import os

from .....tests.blackbox import ExternalBase


class TestDebrelease(ExternalBase):
    def test_simple(self):
        wt = self.make_branch_and_tree("package")
        self.build_tree_contents(
            [
                ("package/debian/",),
                (
                    "package/debian/changelog",
                    b"""\
breezy-foo (2.8.17) UNRELEASED; urgency=medium

  * Hide the mark-uploaded command.

 -- Jelmer Vernooij <jelmer@debian.org>  Sat, 20 Oct 2018 13:05:44 +0000
""",
                ),
                (
                    "package/debian/control",
                    b"""\
Source: breezy-foo
Maintainer: none\
Standards-Version: 3.7.2
Build-Depends: debhelper (>= 9)

Package: brz-debian
Architecture: all
""",
                ),
                (
                    "package/debian/rules",
                    b"""\
#!/usr/bin/make -f

%:
\tdh $*
""",
                ),
                ("package/debian/compat", b"9\n"),
            ]
        )
        os.chmod("package/debian/rules", 0o755)  # noqa: S103
        wt.add(
            [
                "debian",
                "debian/changelog",
                "debian/control",
                "debian/rules",
                "debian/compat",
            ]
        )
        wt.commit("initial commit")
        (out, err) = self.run_bzr(
            "debrelease package --skip-upload --builder true", retcode=0
        )
        self.assertContainsRe(
            err, "Building the package in .*/breezy-foo-2.8.17, using true\n"
        )
        self.assertEqual("", out)
        self.assertEqual(2, wt.branch.revno())
        self.assertEqual(
            "releasing package breezy-foo version 2.8.17",
            wt.branch.repository.get_revision(wt.last_revision()).message,
        )

    def test_unknowns(self):
        wt = self.make_branch_and_tree("package")
        self.build_tree_contents(
            [
                ("package/debian/",),
                (
                    "package/debian/changelog",
                    b"""\
 -- Jelmer Vernooij <jelmer@debian.org>  Sat, 20 Oct 2018 13:05:44 +0000
""",
                ),
                (
                    "package/debian/control",
                    b"""\
Architecture: all
""",
                ),
            ]
        )
        wt.add(["debian", "debian/changelog"])
        (out, err) = self.run_bzr("debrelease package", retcode=3)
        self.assertEqual(
            "brz: ERROR: Build refused because there are unknown "
            "files in the tree. To "
            "list all known files, run 'bzr unknowns'.\n",
            err,
        )
        self.assertEqual("", out)
