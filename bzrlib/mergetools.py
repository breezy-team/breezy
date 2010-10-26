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
    trace,
    ui,
    workingtree,
)
""")

from bzrlib.commands import Command
from bzrlib.option import Option


substitution_help = {
    '%b' : 'file.BASE',
    '%t' : 'file.THIS',
    '%o' : 'file.OTHER',
    '%r' : 'file (output)',
    '%T' : 'file.THIS (temp copy, used to overwrite "file" if merge succeeds)'
}


def subprocess_invoker(executable, args, cleanup):
    retcode = subprocess.call([executable] + args)
    cleanup(retcode)
    return retcode


class MergeTool(object):
    @classmethod
    def from_executable_and_args(cls, executable, args):
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
        name = os.path.basename(self.get_executable())
        if sys.platform == 'win32' and name.lower().endswith('.exe'):
            name = name[:-4]
        return name
        
    def get_commandline(self):
        return self._commandline
    
    def get_executable(self):
        parts = cmdline.split(self._commandline)
        if len(parts) < 1:
            return ''
        return parts[0]
    
    def get_arguments(self):
        parts = cmdline.split(self._commandline)
        if len(parts) < 2:
            return ''
        return ' '.join(parts[1:])
        
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
        return os.path.exists(executable) or _find_executable(executable)
        
    def invoke(self, filename, invoker=None):
        if invoker is None:
            invoker = subprocess_invoker
        # TODO: find a cleaner way to expand into args
        commandline, tmp_file = self._expand_commandline(filename)
        args = cmdline.split(commandline)
        def cleanup(retcode):
            if tmp_file is not None:
                if retcode == 0: # on success, replace file with temp file
                    shutil.move(tmp_file, filename)
                else: # otherwise, delete temp file
                    os.remove(tmp_file)
        return invoker(args[0], args[1:], cleanup)
                
    def _expand_commandline(self, filename):
        commandline = self._commandline
        tmp_file = None
        commandline = commandline.replace('%b', _optional_quote_arg(filename +
                                                                    '.BASE'))
        commandline = commandline.replace('%t', _optional_quote_arg(filename +
                                                                    '.THIS'))
        commandline = commandline.replace('%o', _optional_quote_arg(filename +
                                                                    '.OTHER'))
        commandline = commandline.replace('%r', _optional_quote_arg(filename))
        if '%T' in commandline:
            tmp_file = tempfile.mktemp("_bzr_mergetools_%s.THIS" %
                                       os.path.basename(filename))
            shutil.copy(filename + ".THIS", tmp_file)
            commandline = commandline.replace('%T',
                                              _optional_quote_arg(tmp_file))
        return commandline, tmp_file


_KNOWN_MERGE_TOOLS = (
    'bcompare %t %o %b %r',
    'kdiff3 %b %t %o -o %r',
    'xxdiff -m -O -M %r %t %b %o',
    'meld %b %T %o',
    'opendiff %t %o -ancestor %b -merge %r',
    'winmergeu %r',
)


def detect_merge_tools():
    tools = [MergeTool(commandline) for commandline in _KNOWN_MERGE_TOOLS]
    return [tool for tool in tools if tool.is_available()]


def get_merge_tools(conf=None):
    """Returns list of MergeTool objects."""
    if conf is None:
        conf = config.GlobalConfig()
    commandlines = conf.get_user_option_as_list('mergetools')
    if commandlines is None:
        return []
    return [MergeTool(commandline) for commandline in commandlines]


def set_merge_tools(merge_tools, conf=None):
    if conf is None:
        conf = config.GlobalConfig()
    conf_value = sorted(set(merge_tool.get_commandline()
                           for merge_tool in merge_tools
                           if len(merge_tool.get_commandline()) > 0))
    conf.set_user_option("mergetools", conf_value)


def find_merge_tool(name, conf=None):
    if conf is None:
        conf = config.GlobalConfig()
    merge_tools = get_merge_tools(conf)
    for merge_tool in merge_tools:
        if merge_tool.get_name() == name:
            return merge_tool
    return None


def find_first_available_merge_tool(conf=None):
    if conf is None:
        conf = config.GlobalConfig()
    merge_tools = get_merge_tools(conf)
    for merge_tool in merge_tools:
        if merge_tool.is_available():
            return merge_tool
    return None


def get_default_merge_tool(conf=None):
    if conf is None:
        conf = config.GlobalConfig()
    name = conf.get_user_option('default_mergetool')
    if name is None:
        trace.mutter('no default merge tool defined')
        return None
    merge_tool = find_merge_tool(name, conf)
    trace.mutter('found default merge tool: %r', merge_tool)
    return merge_tool


def set_default_merge_tool(name, conf=None):
    if conf is None:
        conf = config.GlobalConfig()
    if isinstance(name, MergeTool):
        name = name.get_name()
    if find_merge_tool(name, conf) is None:
        raise errors.BzrError('invalid merge tool name: %r' % name)
    trace.mutter('setting default merge tool: %s', name)
    conf.set_user_option('default_mergetool', name)


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


# courtesy of 'techtonik' at http://snippets.dzone.com/posts/show/6313
def _find_executable(executable, path=None):
    """Try to find 'executable' in the directories listed in 'path' (a
    string listing directories separated by 'os.pathsep'; defaults to
    os.environ['PATH']).  Returns the complete filename or None if not
    found
    """
    if path is None:
        path = os.environ['PATH']
    paths = path.split(os.pathsep)
    extlist = ['']
    if sys.platform == 'win32':
        pathext = os.environ['PATHEXT'].lower().split(os.pathsep)
        (base, ext) = os.path.splitext(executable)
        if ext.lower() not in pathext:
            extlist = pathext
    for ext in extlist:
        execname = executable + ext
        if os.path.isfile(execname):
            return execname
        else:
            for p in paths:
                f = os.path.join(p, execname)
                if os.path.isfile(f):
                    return f
    else:
        return None


class cmd_mergetools(Command):
    __doc__ = """Manages external merge tools.
    
    External merge tools are defined by their command line. The executable may
    omit its path if it can be found on the PATH.
    
    When updating or removing an external merge tool, use the simple name of
    the executable, e.g. C:\Tools\kdiff3.exe -> kdiff3.
    
    If you see the warning 'External merge tool is not available' when adding
    or updating, the executable in the command-line you have supplied cannot
    be found.
    
    The following markers can be used in the external merge tool command-line
    to substitute filenames involved in the merge conflict:
    
        %b -> file.BASE
        %t -> file.THIS
        %o -> file.OTHER
        %r -> file (output)
        %T -> file.THIS (temp copy, used to overwrite "file" if merge succeeds)
    
    Examples:
        To add an external merge tool:

            bzr mergetools --add mydifftool %b %t %o %r
        
        If you need to include options in your external merge tool's
        command-line, insert '--' before the command-line to prevent bzr from
        processing them as options to the ``bzr mergetools`` command:
        
            bzr mergetools --add -- kdiff3 %b %t %o -o %r

        To update an existing external merge tool:

            bzr mergetools --update=kdiff3 -- /opt/kde/bin/kdiff3 %b %t %o -o %r

        To remove an existing external merge tool:
        
            bzr mergetools --remove=kdiff3
    """
    takes_args = ['args*']
    takes_options = [
        Option('add', help='Adds an external merge tool using ARGS as the '
               'command-line.', short_name='a'),
        Option('detect', help='Automatically detect known external merge tools '
               'on the PATH'),
        Option('list', help='Lists the currently defined external merge tools.',
               short_name='l'),
        Option('remove', help='Removes the external merge tool called ARG.',
               type=str, short_name='r'),
        Option('update', help='Updates the external merge tool called ARG '
               'using ARGS as the command-line.', type=str, short_name='u'),
    ]

    def run(self, args_list=None, add=False, detect=False, list=False,
            remove=None, update=None):
        if (not add and not detect and not list and remove is None and
            update is None):
            raise errors.BzrCommandError(
                'You must supply one of --add, --detect, --list, --remove or '
                '--update')
        if add:
            self.add_tool(args_list)
        elif detect:
            self.detect_tools()
        elif list:
            self.list_tools()
        elif remove is not None:
            self.remove_tool(remove)
        elif update is not None:
            self.update_tool(update, args_list)
    
    def add_tool(self, args):
        if args is None or len(args) == 0:
            raise errors.BzrCommandError(
                'You must supply the command-line for the external merge tool')
        new_mt = MergeTool.from_executable_and_args(args[0], args[1:])
        if find_merge_tool(new_mt.get_name()) is not None:
            raise errors.BzrCommandError(
                'External merge tool already exists: %s' % new_mt.get_name())
        merge_tools = get_merge_tools()
        merge_tools.append(new_mt)
        set_merge_tools(merge_tools)
        uif = ui.ui_factory
        uif.note('Added external merge tool: %s' % new_mt.get_name())
        if not new_mt.is_available():
            uif.show_warning(
                'External merge tool is not available: %s' % new_mt.get_name())
    
    def detect_tools(self):
        new_merge_tools = detect_merge_tools()
        merge_tools = get_merge_tools()
        for mt in merge_tools:
            for new_mt in new_merge_tools:
                if mt.get_name() == new_mt.get_name():
                    new_merge_tools.remove(new_mt)
                    break
        uif = ui.ui_factory
        if len(new_merge_tools) > 0:
            for mt in new_merge_tools:
                uif.note('Detected external merge tool: %s' % mt.get_name())
        else:
            uif.note('No external merge tools detected')
            return
        new_merge_tools.extend(merge_tools)
        set_merge_tools(new_merge_tools)

    def list_tools(self):
        s = ui.ui_factory.make_output_stream()
        merge_tools = get_merge_tools()
        for mt in merge_tools:
            s.write('%s: %s\n' % (mt.get_name(), mt.get_commandline()))

    def remove_tool(self, name):
        merge_tools = get_merge_tools()
        for mt in merge_tools:
            if mt.get_name() == name:
                merge_tools.remove(mt)
                break
        else:
            raise errors.BzrCommandError(
                'Unknown external merge tool: %s' % name)
        set_merge_tools(merge_tools)

    def update_tool(self, name, args):
        if args is None or len(args) == 0:
            raise errors.BzrCommandError(
                'You must supply the command-line for the external merge tool')
        merge_tools = get_merge_tools()
        for mt in merge_tools:
            if mt.get_name() == name:
                mt.set_executable(args[0])
                mt.set_arguments(args[1:])
                uif = ui.ui_factory
                uif.note('Updated external merge tool: %s' % name)
                if not mt.is_available():
                    uif.show_warning(
                        'External merge tool is not available: %s' %
                        mt.get_name())
                break
        else:
            raise errors.BzrCommandError(
                'Unknown external merge tool: %s' % name)
        set_merge_tools(merge_tools)
