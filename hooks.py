#    hooks.py -- Hook support for builddeb.
#    Copyright (C) 2006 James Westby <jw+debian@jameswestby.net>
#
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

import subprocess

from ...errors import BzrError
from ...trace import note


class HookFailedError(BzrError):
    _fmt = 'The "%(hook_name)s" hook failed.'

    def __init__(self, hook_name):
        BzrError.__init__(self, hook_name=hook_name)


def run_hook(tree, hook_name, config, wd="."):
    hook = config.get_hook(hook_name)
    if hook is None:
        return
    note("Running %s as %s hook" % (hook, hook_name))
    proc = subprocess.Popen(hook, shell=True, cwd=tree.abspath(wd))
    proc.wait()
    if proc.returncode != 0:
        raise HookFailedError(hook_name)
