# Copyright (C) 2006, 2011 Canonical Ltd
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

"""Smart-server protocol, client and server.

This code is fairly complex, so it has been split up into a package of modules,
rather than being a single large module.  Refer to the individual module
docstrings for details.

Server-side request handlers are registered in the `breezy.bzr.smart.request`
module.

The domain logic is in `breezy.bzr.remote`: `RemoteBzrDir`, `RemoteBranch`,
and so on.

There is also an plain file-level transport that calls remote methods to
manipulate files on the server in `breezy.transport.remote`.

The protocol is described in doc/developers/network-protocol.txt.

"""

# TODO: A plain integer from query_version is too simple; should give some
# capabilities too?

# TODO: Make each request and response self-validatable, e.g. with checksums.
#
# TODO: is it useful to allow multiple chunks in the bulk data?
#
# TODO: If we get an exception during transmission of bulk data we can't just
# emit the exception because it won't be seen.
#   John proposes:  I think it would be worthwhile to have a header on each
#   chunk, that indicates it is another chunk. Then you can send an 'error'
#   chunk as long as you finish the previous chunk.
#

# Promote some attributes from submodules into this namespace
from .request import SmartServerRequestHandler  # noqa: F401
