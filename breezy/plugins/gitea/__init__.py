# Copyright (C) 2021 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Management of hosted branches."""

from __future__ import absolute_import

from ... import version_info  # noqa: F401
from ...commands import plugin_cmds

from ...propose import hosters
hosters.register_lazy("gitea", __name__ + '.hoster', "Gitea")


def test_suite():
    from unittest import TestSuite
    from .tests import test_suite
    result = TestSuite()
    result.addTest(test_suite())
    return result
