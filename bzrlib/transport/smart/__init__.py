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

Overview
========

Requests are sent as a command and list of arguments, followed by optional
bulk body data.  Responses are similarly a response and list of arguments,
followed by bulk body data. ::

  SEP := '\001'
    Fields are separated by Ctrl-A.
  BULK_DATA := CHUNK TRAILER
    Chunks can be repeated as many times as necessary.
  CHUNK := CHUNK_LEN CHUNK_BODY
  CHUNK_LEN := DIGIT+ NEWLINE
    Gives the number of bytes in the following chunk.
  CHUNK_BODY := BYTE[chunk_len]
  TRAILER := SUCCESS_TRAILER | ERROR_TRAILER
  SUCCESS_TRAILER := 'done' NEWLINE
  ERROR_TRAILER := 

Paths are passed across the network.  The client needs to see a namespace that
includes any repository that might need to be referenced, and the client needs
to know about a root directory beyond which it cannot ascend.

Servers run over ssh will typically want to be able to access any path the user 
can access.  Public servers on the other hand (which might be over http, ssh
or tcp) will typically want to restrict access to only a particular directory 
and its children, so will want to do a software virtual root at that level.
In other words they'll want to rewrite incoming paths to be under that level
(and prevent escaping using ../ tricks.)

URLs that include ~ should probably be passed across to the server verbatim
and the server can expand them.  This will proably not be meaningful when 
limited to a directory?

At the bottom level socket, pipes, HTTP server.  For sockets, we have the idea
that you have multiple requests and get a read error because the other side did
shutdown.  For pipes we have read pipe which will have a zero read which marks
end-of-file.  For HTTP server environment there is not end-of-stream because
each request coming into the server is independent.

So we need a wrapper around pipes and sockets to seperate out requests from
substrate and this will give us a single model which is consist for HTTP,
sockets and pipes.

Server-side
-----------

 MEDIUM  (factory for protocol, reads bytes & pushes to protocol,
          uses protocol to detect end-of-request, sends written
          bytes to client) e.g. socket, pipe, HTTP request handler.
  ^
  | bytes.
  v

PROTOCOL  (serialization, deserialization)  accepts bytes for one
          request, decodes according to internal state, pushes
          structured data to handler.  accepts structured data from
          handler and encodes and writes to the medium.  factory for
          handler.
  ^
  | structured data
  v

HANDLER   (domain logic) accepts structured data, operates state
          machine until the request can be satisfied,
          sends structured data to the protocol.


Client-side
-----------

 CLIENT             domain logic, accepts domain requests, generated structured
                    data, reads structured data from responses and turns into
                    domain data.  Sends structured data to the protocol.
                    Operates state machines until the request can be delivered
                    (e.g. reading from a bundle generated in bzrlib to deliver a
                    complete request).

                    Possibly this should just be RemoteBzrDir, RemoteTransport,
                    ...
  ^
  | structured data
  v

PROTOCOL  (serialization, deserialization)  accepts structured data for one
          request, encodes and writes to the medium.  Reads bytes from the
          medium, decodes and allows the client to read structured data.
  ^
  | bytes.
  v

 MEDIUM  (accepts bytes from the protocol & delivers to the remote server.
          Allows the potocol to read bytes e.g. socket, pipe, HTTP request.
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

# TODO: Standard marker at start of request/response lines?

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
# TODO: Pull more things common to sftp and ssh to a higher level.
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
# FIXME: This transport, with several others, has imperfect handling of paths
# within urls.  It'd probably be better for ".." from a root to raise an error
# rather than return the same directory as we do at present.
#
# TODO: Rather than working at the Transport layer we want a Branch,
# Repository or BzrDir objects that talk to a server.
#
# TODO: Probably want some way for server commands to gradually produce body
# data rather than passing it as a string; they could perhaps pass an
# iterator-like callback that will gradually yield data; it probably needs a
# close() method that will always be closed to do any necessary cleanup.
#
# TODO: Split the actual smart server from the ssh encoding of it.
#
# TODO: Perhaps support file-level readwrite operations over the transport
# too.
#
# TODO: SmartBzrDir class, proxying all Branch etc methods across to another
# branch doing file-level operations.
#


# Promote some attributes from submodules into this namespace
from bzrlib.transport.smart._smart import (
    SmartSSHTransport,
    SmartTCPTransport,
    SmartTransport,
    )
from bzrlib.transport.smart.request import SmartServerRequestHandler


def get_test_permutations():
    """Return (transport, server) permutations for testing."""
    ### We may need a little more test framework support to construct an
    ### appropriate RemoteTransport in the future.
    from bzrlib.transport.smart import server
    return [(SmartTCPTransport, server.SmartTCPServer_for_testing)]
