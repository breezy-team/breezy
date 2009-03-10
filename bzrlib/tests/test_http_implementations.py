# Copyright (C) 2007 Canonical Ltd
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

"""Tests for HTTP transports and servers implementations.

(transport, server) implementations tested here are supplied by
HTTPTestProviderAdapter. Note that a server is characterized by a request
handler class.

Transport implementations are normally tested via
test_transport_implementations. The tests here are about the variations in HTTP
protocol implementation to guarantee the robustness of our transports.
"""

import errno
import SimpleHTTPServer
import socket

import bzrlib
from bzrlib import (
    config,
    errors,
    osutils,
    tests,
    transport,
    ui,
    urlutils,
    )
from bzrlib.tests import (
    http_server,
    http_utils,
    )
from bzrlib.transport.http import (
    _urllib,
    _urllib2_wrappers,
    )


