# Copyright (C) 2006 by Canonical Ltd
#   Authors: Robert Collins <robert.collins@canonical.com>
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

"""Tests for the formatting and construction of errors."""

import bzrlib.bzrdir as bzrdir
import bzrlib.errors as errors
from bzrlib.tests import TestCaseWithTransport


class TestErrors(TestCaseWithTransport):

    def test_no_repo(self):
        dir = bzrdir.BzrDir.create(self.get_url())
        error = errors.NoRepositoryPresent(dir)
        self.assertNotEqual(-1, str(error).find(repr(dir.transport.clone('..').base)))
        self.assertEqual(-1, str(error).find(repr(dir.transport.base)))

    def test_up_to_date(self):
        error = errors.UpToDateFormat(bzrdir.BzrDirFormat4())
        self.assertEqualDiff("The branch format Bazaar-NG branch, "
                             "format 0.0.4 is already at the most "
                             "recent format.",
                             str(error))

    def test_corrupt_repository(self):
        repo = self.make_repository('.')
        error = errors.CorruptRepository(repo)
        self.assertEqualDiff("An error has been detected in the repository %s.\n"
                             "Please run bzr reconcile on this repository." %
                             repo.bzrdir.root_transport.base,
                             str(error))
