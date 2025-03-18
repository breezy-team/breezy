#!/usr/bin/env python3
# vim: expandtab

# Copyright (C) 2011 Jelmer Vernooij <jelmer@apache.org>

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


"""Remote helper for git for accessing bzr repositories."""

import optparse
import signal
import sys


def handle_sigint(signal, frame):
    sys.exit(0)


signal.signal(signal.SIGINT, handle_sigint)

import breezy

breezy.initialize()

from breezy.plugin import load_plugins

load_plugins()

from breezy.git.git_remote_helper import RemoteHelper, open_local_dir, open_remote_dir
from breezy.trace import warning


def main():
    parser = optparse.OptionParser()
    (opts, args) = parser.parse_args()
    (shortname, url) = args

    warning(
        "git-remote-bzr is experimental and has not been optimized for "
        "performance. Use 'brz fast-export' and 'git fast-import' for "
        "large repositories."
    )

    helper = RemoteHelper(open_local_dir(), shortname, open_remote_dir(url))
    helper.process(sys.stdin.buffer, sys.stdout.buffer)
