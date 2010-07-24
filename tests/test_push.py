# Copyright (C) 2010 Jelmer Vernooij <jelmer@samba.org>
# -*- coding: utf-8 -*-
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

"""Tests for pushing revisions from Bazaar into Git."""

from bzrlib.bzrdir import (
    format_registry,
    )
from bzrlib.repository import (
    InterRepository,
    )
from bzrlib.tests import (
    TestCase,
    TestCaseWithTransport,
    )

from bzrlib.plugins.git.push import (
    InterToGitRepository,
    )


class DpushTests(TestCaseWithTransport):

    def setUp(self):
        super(DpushTests, self).setUp()
        self.git_repo = self.make_repository("git",
                format=format_registry.make_bzrdir("git"))
        self.bzr_repo = self.make_repository("bzr")
        self.interrepo = InterRepository.get(self.bzr_repo, self.git_repo)

    def test_instance(self):
        self.assertIsInstance(self.interrepo, InterToGitRepository)

