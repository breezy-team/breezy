# Copyright (C) 2009 Canonical Ltd
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

"""Tests for chk_bytes support on a repository with external references."""

from bzrlib import (
    errors,
    tests,
    )
from bzrlib.tests.per_repository_reference import (
    TestCaseWithExternalReferenceRepository,
    )


class TestCHKBytes(TestCaseWithExternalReferenceRepository):

    def setUp(self):
        super(TestCHKBytes, self).setUp()
        if not self.repository_format.supports_chks:
            raise tests.TestNotApplicable('No chk_bytes support')
