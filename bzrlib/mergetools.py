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
import tempfile

from bzrlib import (
    cmdline,
    config,
    errors,
)


substitution_help = {
    '%b' : 'file.BASE',
    '%t' : 'file.THIS',
    '%o' : 'file.OTHER',
    '%r' : 'file (output)',
    '%T' : 'file.THIS (temp copy, used to overwrite "file" if merge succeeds)'
}


class MergeTool(object):
    @staticmethod
    def from_executable_and_args(executable, args):
        executable = _optional_quote_arg(executable)
        if not isinstance(args, str) and not isinstance(args, unicode):
            args = ' '.join([_optional_quote_arg(arg) for arg in args])
        return MergeTool(executable + ' ' + args)
    
    def __init__(self, commandline):
        """commandline: Command line of merge tool, including executable and
                        args with filename substitution markers.
        """
        self._commandline = commandline
        
    def __repr__(self):
        return '<MergeTool %r>' % self._commandline
        
    def __str__(self):
        return self._commandline
        
    def get_name(self):
        return os.path.basename(self.get_executable())
        
    def get_commandline(self):
        return self._commandline
    
    def get_executable(self):
        return cmdline.split(self._commandline)[0]
    
    def get_arguments(self):
        return ' '.join(cmdline.split(self._commandline)[1:])
        
    def set_executable(self, executable):
        split_cmdline = cmdline.split(self._commandline)
        split_cmdline[0] = _optional_quote_arg(executable)
        self._commandline = ' '.join(split_cmdline)
    
    def set_arguments(self, args):
        if not isinstance(args, str) and not isinstance(args, unicode):
            args = ' '.join([_optional_quote_arg(arg) for arg in args])
        self._commandline = self.get_executable() + ' ' + args
    
    def set_commandline(self, commandline):
        self._commandline = commandline

    def is_available(self):
        executable = self.get_executable()
        if os.path.isabs(executable):
            return os.path.exists(executable)
        else:
            # Assume non-absolute path is resolvable on PATH
            # TODO: Search PATH for executable
            return True
        
    def invoke(self, filename):
        commandline, tmp_file = self._expand_commandline(filename)
        retcode = subprocess.call(commandline, shell=True)
        if tmp_file is not None:
            if retcode == 0: # on success, replace file with temp file
                shutil.move(tmp_file, filename)
            else: # otherwise, delete temp file
                os.remove(tmp_file)
                
    def _expand_commandline(self, filename):
        commandline = self._commandline
        tmp_file = None
        commandline = commandline.replace('%b', _optional_quote_arg(filename + '.BASE'))
        commandline = commandline.replace('%t', _optional_quote_arg(filename + '.THIS'))
        commandline = commandline.replace('%o', _optional_quote_arg(filename + '.OTHER'))
        commandline = commandline.replace('%r', _optional_quote_arg(filename))
        if '%T' in commandline:
            tmp_file = tempfile.mktemp("_bzr_mergetools_%s.THIS" % os.path.basename(filename))
            shutil.copy(filename + ".THIS", tmp_file)
            commandline = commandline.replace('%T', _optional_quote_arg(tmp_file))
        return commandline, tmp_file


_DEFAULT_MERGE_TOOLS = (
    'bcompare %t %o %b %r',
    'kdiff3 %b %t %o -o %r',
    'xxdiff -m -O -M %r %t %b %o',
    'meld %b %T %o',
    'opendiff %t %o -ancestor %b -merge %r',
    'winmergeu %r',
)


def get_default_merge_tools():
    return [MergeTool(commandline) for commandline in _DEFAULT_MERGE_TOOLS]


def get_merge_tools(conf=config.GlobalConfig()):
    """Returns list of MergeTool objects."""
    commandlines = conf.get_user_option_as_list('mergetools')
    if commandlines is None:
        commandlines = _DEFAULT_MERGE_TOOLS
    return [MergeTool(commandline) for commandline in commandlines]


def set_merge_tools(merge_tools, conf=config.GlobalConfig()):
    conf.set_user_option("mergetools", tuple(merge_tool.get_commandline()
                                             for merge_tool in merge_tools))


def find_merge_tool(name, conf=config.GlobalConfig()):
    merge_tools = get_merge_tools(conf)
    for merge_tool in merge_tools:
        if merge_tool.get_name() == name:
            return merge_tool
    return None


def get_user_selected_merge_tool(conf=config.GlobalConfig()):
    name = conf.get_user_option('selected_mergetool')
    if name is None:
        return None
    return find_merge_tool(name, conf)


def set_user_selected_merge_tool(name, conf=config.GlobalConfig()):
    if isinstance(name, MergeTool):
        name = name.get_name()
    if find_merge_tool(name, conf) is None:
        raise errors.BzrError('invalid merge tool name: %r' % name)
    conf.set_user_option('selected_mergetool', name)


def _optional_quote_arg(arg):
    if ' ' in arg and not _is_arg_quoted(arg):
        return '"%s"' % _escape_quotes(arg)
    else:
        return arg


def _is_arg_quoted(arg):
    return (arg[0] == "'" and arg[-1] == "'") or \
           (arg[0] == '"' and arg[-1] == '"')


def _escape_quotes(arg):
    return arg.replace('"', '\\"')
