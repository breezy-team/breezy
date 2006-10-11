# Copyright (C) 2004, 2005, 2006 by Canonical Ltd
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

# TODO: Some way to get a list of external commands (defined by shell
# scripts) so that they can be included in the help listing as well.
# It should be enough to just list the plugin directory and look for
# executable files with reasonable names.

# TODO: `help commands --all` should show hidden commands

import sys
from bzrlib import help_topics
from bzrlib import osutils
import textwrap

help_topics.add_topic("commands",
                      (lambda name, outfile: help_commands(outfile)),
                      "Basic help for all commands")

def help(topic=None, outfile = None):
    if outfile is None:
        outfile = sys.stdout
    if topic is None:
        help_topics.write_topic("basic", outfile)
    elif help_topics.is_topic(topic):
        help_topics.write_topic(topic, outfile)
    else:
        help_on_command(topic, outfile=outfile)


def command_usage(cmd_object):
    """Return single-line grammar for command.

    Only describes arguments, not options.
    """
    s = 'bzr ' + cmd_object.name() + ' '
    for aname in cmd_object.takes_args:
        aname = aname.upper()
        if aname[-1] in ['$', '+']:
            aname = aname[:-1] + '...'
        elif aname[-1] == '?':
            aname = '[' + aname[:-1] + ']'
        elif aname[-1] == '*':
            aname = '[' + aname[:-1] + '...]'
        s += aname + ' '
            
    assert s[-1] == ' '
    s = s[:-1]
    
    return s


def print_command_plugin(cmd_object, outfile, format):
    """Print the plugin that provides a command object, if any.

    If the cmd_object is provided by a plugin, prints the plugin name to
    outfile using the provided format string.
    """
    plugin_name = cmd_object.plugin_name()
    if plugin_name is not None:
        out_str = '(From plugin "%s")' % plugin_name
        outfile.write(format % out_str)


def help_on_command(cmdname, outfile=None):
    from bzrlib.commands import get_cmd_object

    cmdname = str(cmdname)

    if outfile is None:
        outfile = sys.stdout

    cmd_object = get_cmd_object(cmdname)

    doc = cmd_object.help()
    if doc is None:
        raise NotImplementedError("sorry, no detailed help yet for %r" % cmdname)

    print >>outfile, 'usage:', command_usage(cmd_object) 

    if cmd_object.aliases:
        print >>outfile, 'aliases:',
        print >>outfile, ', '.join(cmd_object.aliases)

    print >>outfile

    print_command_plugin(cmd_object, outfile, '%s\n\n')

    outfile.write(doc)
    if doc[-1] != '\n':
        outfile.write('\n')
    help_on_command_options(cmd_object, outfile)


def help_on_command_options(cmd, outfile=None):
    from bzrlib.option import Option, get_optparser
    if outfile is None:
        outfile = sys.stdout
    options = cmd.options()
    outfile.write('\n')
    outfile.write(get_optparser(options).format_option_help())


def help_commands(outfile=None):
    """List all commands"""
    from bzrlib.commands import (builtin_command_names,
                                 plugin_command_names,
                                 get_cmd_object)
    if outfile is None:
        outfile = sys.stdout
    names = set(builtin_command_names()) # to eliminate duplicates
    names.update(plugin_command_names())
    commands = ((n, get_cmd_object(n)) for n in names)
    shown_commands = [(n, o) for n, o in commands if not o.hidden]
    max_name = max(len(n) for n, o in shown_commands)
    indent = ' ' * (max_name + 1)
    width = osutils.terminal_width() - 1
    for cmd_name, cmd_object in sorted(shown_commands):
        plugin_name = cmd_object.plugin_name()
        if plugin_name is None:
            plugin_name = ''
        else:
            plugin_name = ' [%s]' % plugin_name

        cmd_help = cmd_object.help()
        if cmd_help:
            firstline = cmd_help.split('\n', 1)[0]
        else:
            firstline = ''
        helpstring = '%-*s %s%s' % (max_name, cmd_name, firstline, plugin_name)
        lines = textwrap.wrap(helpstring, subsequent_indent=indent,
                              width=width)
        for line in lines:
            outfile.write(line + '\n')
