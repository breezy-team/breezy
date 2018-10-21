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

from __future__ import absolute_import

from .....tests.blackbox import ExternalBase

import os


class TestDebrelease(ExternalBase):

    def test_simple(self):
        wt = self.make_branch_and_tree('package')
        self.build_tree_contents([
            ('package/debian/', ),
            ('package/debian/changelog', b"""\
breezy-debian (2.8.17) UNRELEASED; urgency=medium

  * Hide the mark-uploaded command.

 -- Jelmer Vernooij <jelmer@debian.org>  Sat, 20 Oct 2018 13:05:44 +0000
"""),
            ('package/debian/control', b"""\
Source: breezy-debian
Maintainer: none\
Standards-Version: 3.7.2

Package: brz-debian
Architecture: all
"""),
            ])
        wt.add(["debian", "debian/changelog", "debian/control"])
        (out, err) = self.run_bzr("debrelease package", retcode=0)
        self.assertEquals("brz: ERROR: No unmerged revisions\n", err)
        self.assertEquals("", out)

    def test_unknowns(self):
        wt = self.make_branch_and_tree('package')
        self.build_tree_contents([
            ('package/debian/', ),
            ('package/debian/changelog', b"""\
 -- Jelmer Vernooij <jelmer@debian.org>  Sat, 20 Oct 2018 13:05:44 +0000
"""),
            ('package/debian/control', b"""\
Architecture: all
"""),
            ])
        wt.add(["debian", "debian/changelog"])
        (out, err) = self.run_bzr("debrelease package", retcode=3)
        self.assertEquals(
            'brz: ERROR: Build refused because there are unknown files in the tree. To '
            "list all known files, run 'bzr unknowns'.\n", err)
        self.assertEquals("", out)
