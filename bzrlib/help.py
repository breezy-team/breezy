# Copyright (C) 2004, 2005, 2006 Canonical Ltd
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
import textwrap

from bzrlib import (
    commands as _mod_commands,
    errors,
    help_topics,
    osutils,
    )


def help(topic=None, outfile=None):
    """Write the help for the specific topic to outfile"""
    if outfile is None:
        outfile = sys.stdout

    if topic is None:
        topic = 'basic'

    if topic in help_topics.topic_registry:
        txt = help_topics.topic_registry.get_detail(topic)
        outfile.write(txt)
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
    cmdname = str(cmdname)
    cmd_object = _mod_commands.get_cmd_object(cmdname)

    return help_on_command_object(cmd_object, cmdname, outfile)


def help_on_command_object(cmd_object, cmdname, outfile=None):
    """Generate help on the cmd_object with a supplied name of cmdname.

    :param cmd_object: An instance of a Command.
    :param cmdname: The user supplied name. This might be an alias for example.
    :param outfile: A stream to write the help to.
    """
    if outfile is None:
        outfile = sys.stdout

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
    see_also = cmd_object.get_see_also()
    if see_also:
        outfile.write('\nSee also: ')
        outfile.write(', '.join(see_also))
        outfile.write('\n')


def help_on_command_options(cmd, outfile=None):
    from bzrlib.option import Option, get_optparser
    if outfile is None:
        outfile = sys.stdout
    options = cmd.options()
    outfile.write('\n')
    outfile.write(get_optparser(options).format_option_help())


def help_commands(outfile=None):
    """List all commands"""
    if outfile is None:
        outfile = sys.stdout
    outfile.write(_help_commands_to_text('commands'))


def _help_commands_to_text(topic):
    """Generate the help text for the list of commands"""
    out = []
    if topic == 'hidden-commands':
        hidden = True
    else:
        hidden = False
    names = set(_mod_commands.builtin_command_names()) # to eliminate duplicates
    names.update(_mod_commands.plugin_command_names())
    commands = ((n, _mod_commands.get_cmd_object(n)) for n in names)
    shown_commands = [(n, o) for n, o in commands if o.hidden == hidden]
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
            out.append(line + '\n')
    return ''.join(out)


help_topics.topic_registry.register("commands",
                                    _help_commands_to_text,
                                    "Basic help for all commands")
help_topics.topic_registry.register("hidden-commands",
                                    _help_commands_to_text,
                                    "All hidden commands")


class HelpContexts(object):
    """An object to manage help in multiple contexts."""

    def __init__(self):
        self.search_path = [
            help_topics.HelpTopicContext(),
            _mod_commands.HelpCommandContext(),
            ]

    def search(self, topic):
        """Search for topic across the help search path.
        
        :param topic: A string naming the help topic to search for.
        :raises: NoHelpTopic if none of the contexts in search_path have topic.
        :return: A list of HelpTopics which matched 'topic'.
        """
        result = []
        for context in self.search_path:
            result.extend(context.get_topics(topic))
        if not result:
            raise errors.NoHelpTopic(topic)
        else:
            return result
