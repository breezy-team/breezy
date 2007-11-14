# Copyright (C) 2006 Canonical Ltd
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

"""Smart-server protocol, client and server.

This code is fairly complex, so it has been split up into a package of modules,
rather than being a single large module.  Refer to the individual module
docstrings for details.

Server-side request handlers are registered in the `bzrlib.smart.request`
module.

The domain logic is in `bzrlib.remote`: `RemoteBzrDir`, `RemoteBranch`,
and so on.

There is also an plain file-level transport that calls remote methods to
manipulate files on the server in `bzrlib.transport.remote`.

The protocol is described in doc/developers/network-protocol.txt.

"""

# TODO: _translate_error should be on the client, not the transport because
#     error coding is wire protocol specific.

# TODO: A plain integer from query_version is too simple; should give some
# capabilities too?

# TODO: Server should probably catch exceptions within itself and send them
# back across the network.  (But shouldn't catch KeyboardInterrupt etc)
# Also needs to somehow report protocol errors like bad requests.  Need to
# consider how we'll handle error reporting, e.g. if we get halfway through a
# bulk transfer and then something goes wrong.

# TODO: Make each request and response self-validatable, e.g. with checksums.
#
# TODO: get/put objects could be changed to gradually read back the data as it
# comes across the network
#
# TODO: What should the server do if it hits an error and has to terminate?
#
# TODO: is it useful to allow multiple chunks in the bulk data?
#
# TODO: If we get an exception during transmission of bulk data we can't just
# emit the exception because it won't be seen.
#   John proposes:  I think it would be worthwhile to have a header on each
#   chunk, that indicates it is another chunk. Then you can send an 'error'
#   chunk as long as you finish the previous chunk.
#
# TODO: Clone method on Transport; should work up towards parent directory;
# unclear how this should be stored or communicated to the server... maybe
# just pass it on all relevant requests?
#
# TODO: Better name than clone() for changing between directories.  How about
# open_dir or change_dir or chdir?
#
# TODO: Is it really good to have the notion of current directory within the
# connection?  Perhaps all Transports should factor out a common connection
# from the thing that has the directory context?
#
# TODO: The server that manages a connection should be quite small and retain
# minimum state because each of the requests are supposed to be stateless.
# Then we can write another implementation that maps to http.
#
# TODO: What to do when a client connection is garbage collected?  Maybe just
# abruptly drop the connection?
#
# TODO: Server in some cases will need to restrict access to files outside of
# a particular root directory.  LocalTransport doesn't do anything to stop you
# ascending above the base directory, so we need to prevent paths
# containing '..' in either the server or transport layers.  (Also need to
# consider what happens if someone creates a symlink pointing outside the 
# directory tree...)
#
# TODO: Server should rebase absolute paths coming across the network to put
# them under the virtual root, if one is in use.  LocalTransport currently
# doesn't do that; if you give it an absolute path it just uses it.
# 
# XXX: Arguments can't contain newlines or ascii; possibly we should e.g.
# urlescape them instead.  Indeed possibly this should just literally be
# http-over-ssh.
#
# TODO: Probably want some way for server commands to gradually produce body
# data rather than passing it as a string; they could perhaps pass an
# iterator-like callback that will gradually yield data; it probably needs a
# close() method that will always be closed to do any necessary cleanup.


# Promote some attributes from submodules into this namespace
from bzrlib.smart.request import SmartServerRequestHandler


