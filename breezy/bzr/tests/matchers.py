# Copyright (C) 2010 Canonical Ltd
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

"""Matchers for breezy.

Primarily test support, Matchers are used by self.assertThat in the breezy
test suite. A matcher is a stateful test helper which can be used to determine
if a passed object 'matches', much like a regex. If the object does not match
the mismatch can be described in a human readable fashion. assertThat then
raises if a mismatch occurs, showing the description as the assertion error.

Matchers are designed to be more reusable and composable than layered
assertions in Test Case objects, so they are recommended for new testing work.
"""

__all__ = [
    "ContainsNoVfsCalls",
]

from testtools.matchers import Matcher, Mismatch

from breezy.bzr.smart import vfs
from breezy.bzr.smart.request import request_handlers as smart_request_handlers


class _NoVfsCallsMismatch(Mismatch):
    """Mismatch describing a list of HPSS calls which includes VFS requests."""

    def __init__(self, vfs_calls):
        self.vfs_calls = vfs_calls

    def describe(self):
        return "no VFS calls expected, got: {}".format(
            ",".join(
                [
                    "{}({})".format(c.method, ", ".join([repr(a) for a in c.args]))
                    for c in self.vfs_calls
                ]
            )
        )


class ContainsNoVfsCalls(Matcher):
    """Ensure that none of the specified calls are HPSS calls."""

    def __str__(self):
        return "ContainsNoVfsCalls()"

    @classmethod
    def match(cls, hpss_calls):
        vfs_calls = []
        for call in hpss_calls:
            try:
                request_method = smart_request_handlers.get(call.call.method)
            except KeyError:
                # A method we don't know about doesn't count as a VFS method.
                continue
            if issubclass(request_method, vfs.VfsRequest):
                vfs_calls.append(call.call)
        if len(vfs_calls) == 0:
            return None
        return _NoVfsCallsMismatch(vfs_calls)
