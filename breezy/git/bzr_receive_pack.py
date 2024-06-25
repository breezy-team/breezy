#!/usr/bin/env python3

# Copyright (C) 2010 Jelmer Vernooĳ <jelmer@jelmer.uk>

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

import os
import sys

from dulwich.server import ReceivePackHandler, serve_command

import breezy
import breezy.bzr
import breezy.git
from breezy.git.server import BzrBackend


def main():
    if len(sys.argv) < 2:
        print("usage: {} <git-dir>".format(os.path.basename(sys.argv[0])))
        sys.exit(1)

    backend = BzrBackend(breezy.transport.get_transport("/"))
    sys.exit(serve_command(ReceivePackHandler, backend=backend))
