# Copyright (C) 2010 Canonical Ltd.
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

"""Registry for external merge tools, e.g. kdiff3, meld, etc."""

import os
import shutil
import subprocess
import sys
import tempfile

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import (
    cmdline,
    config,
    errors,
    osutils,
    trace,
    ui,
    workingtree,
)
""")

from bzrlib.commands import Command
from bzrlib.option import Option


def subprocess_invoker(executable, args, cleanup):
    retcode = subprocess.call([executable] + args)
    cleanup(retcode)
    return retcode


_WIN32_PATH_EXT = [unicode(ext.lower())
                   for ext in os.getenv('PATHEXT', '').split(';')]


class MergeTool(object):

    def __init__(self, name, command_line):
        """Initializes the merge tool with a name and a command-line."""
        self.name = name
        self.command_line = command_line
        self._cmd_list = cmdline.split(self.command_line)

    def __repr__(self):
        return '<%s(%s, %s)>' % (self.__class__, self.name, self.command_line)

    def is_available(self):
        exe = self._cmd_list[0]
        return (os.path.exists(exe)
                or osutils.find_executable_on_path(exe) is not None)

    def invoke(self, filename, invoker=None):
        if invoker is None:
            invoker = subprocess_invoker
        args, tmp_file = self._subst_filename(self._cmd_list, filename)
        def cleanup(retcode):
            if tmp_file is not None:
                if retcode == 0: # on success, replace file with temp file
                    shutil.move(tmp_file, filename)
                else: # otherwise, delete temp file
                    os.remove(tmp_file)
        return invoker(args[0], args[1:], cleanup)

    def _subst_filename(self, args, filename):
        subst_names = {
            u'base': filename + u'.BASE',
            u'this': filename + u'.THIS',
            u'other': filename + u'.OTHER',
            u'result': filename,
        }
        tmp_file = None
        subst_args = []
        for arg in args:
            if u'{this_temp}' in arg and not 'this_temp' in subst_names:
                tmp_file = tempfile.mktemp(u"_bzr_mergetools_%s.THIS" %
                                           os.path.basename(filename))
                shutil.copy(filename + u".THIS", tmp_file)
                subst_names['this_temp'] = tmp_file
            arg = arg.format(**subst_names)
            subst_args.append(arg)
        return subst_args, tmp_file


_KNOWN_MERGE_TOOLS = (
    u'bcompare {this} {other} {base} {result}',
    u'kdiff3 {base} {this} {other} -o {result}',
    u'xxdiff -m -O -M {result} {this} {base} {other}',
    u'meld {base} {this_temp} {other}',
    u'opendiff {this} {other} -ancestor {base} -merge {result}',
    u'winmergeu {result}',
)


def detect_merge_tools():
    tools = [MergeTool(None, commandline) for commandline in _KNOWN_MERGE_TOOLS]
    return [tool for tool in tools if tool.is_available()]

