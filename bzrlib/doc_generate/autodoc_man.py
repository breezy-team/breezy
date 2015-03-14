# Copyright (C) 2005-2010 Canonical Ltd

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

"""man.py - create man page from built-in bzr help and static text

TODO:
  * use usage information instead of simple "bzr foo" in COMMAND OVERVIEW
  * add command aliases
"""

from __future__ import absolute_import

PLUGINS_TO_DOCUMENT = ["launchpad"]

import textwrap
import time

import bzrlib
import bzrlib.help
import bzrlib.help_topics
import bzrlib.commands

from bzrlib.plugin import load_plugins
load_plugins()


def get_filename(options):
    """Provides name of manpage"""
    return "%s.1" % (options.bzr_name)


def infogen(options, outfile):
    """Assembles a man page"""
    t = time.time()
    tt = time.gmtime(t)
    params = \
           { "bzrcmd": options.bzr_name,
             "datestamp": time.strftime("%Y-%m-%d",tt),
             "timestamp": time.strftime("%Y-%m-%d %H:%M:%S +0000",tt),
             "version": bzrlib.__version__,
             }
    outfile.write(man_preamble % params)
    outfile.write(man_escape(man_head % params))
    outfile.write(man_escape(getcommand_list(params)))
    outfile.write(man_escape(getcommand_help(params)))
    outfile.write("".join(environment_variables()))
    outfile.write(man_escape(man_foot % params))


def man_escape(string):
    """Escapes strings for man page compatibility"""
    result = string.replace("\\","\\\\")
    result = result.replace("`","\\'")
    result = result.replace("'","\\*(Aq")
    result = result.replace("-","\\-")
    return result


def command_name_list():
    """Builds a list of command names from bzrlib"""
    command_names = bzrlib.commands.builtin_command_names()
    for cmdname in bzrlib.commands.plugin_command_names():
        cmd_object = bzrlib.commands.get_cmd_object(cmdname)
        if (PLUGINS_TO_DOCUMENT is None or
            cmd_object.plugin_name() in PLUGINS_TO_DOCUMENT):
            command_names.append(cmdname)
    command_names.sort()
    return command_names


def getcommand_list (params):
    """Builds summary help for command names in manpage format"""
    bzrcmd = params["bzrcmd"]
    output = '.SH "COMMAND OVERVIEW"\n'
    for cmd_name in command_name_list():
        cmd_object = bzrlib.commands.get_cmd_object(cmd_name)
        if cmd_object.hidden:
            continue
        cmd_help = cmd_object.help()
        if cmd_help:
            firstline = cmd_help.split('\n', 1)[0]
            usage = cmd_object._usage()
            tmp = '.TP\n.B "%s"\n%s\n' % (usage, firstline)
            output = output + tmp
        else:
            raise RuntimeError, "Command '%s' has no help text" % (cmd_name)
    return output


def getcommand_help(params):
    """Shows individual options for a bzr command"""
    output='.SH "COMMAND REFERENCE"\n'
    formatted = {}
    for cmd_name in command_name_list():
        cmd_object = bzrlib.commands.get_cmd_object(cmd_name)
        if cmd_object.hidden:
            continue
        formatted[cmd_name] = format_command(params, cmd_object)
        for alias in cmd_object.aliases:
            formatted[alias] = format_alias(params, alias, cmd_name)
    for cmd_name in sorted(formatted):
        output += formatted[cmd_name]
    return output


def format_command(params, cmd):
    """Provides long help for each public command"""
    subsection_header = '.SS "%s"\n' % (cmd._usage())
    doc = "%s\n" % (cmd.__doc__)
    doc = bzrlib.help_topics.help_as_plain_text(cmd.help())

    # A dot at the beginning of a line is interpreted as a macro.
    # Simply join lines that begin with a dot with the previous
    # line to work around this.
    doc = doc.replace("\n.", ".")

    option_str = ""
    options = cmd.options()
    if options:
        option_str = "\nOptions:\n"
        for option_name, option in sorted(options.items()):
            for name, short_name, argname, help in option.iter_switches():
                if option.is_hidden(name):
                    continue
                l = '    --' + name
                if argname is not None:
                    l += ' ' + argname
                if short_name:
                    l += ', -' + short_name
                l += (30 - len(l)) * ' ' + (help or '')
                wrapped = textwrap.fill(l, initial_indent='',
                    subsequent_indent=30*' ',
                    break_long_words=False,
                    )
                option_str += wrapped + '\n'

    aliases_str = ""
    if cmd.aliases:
        if len(cmd.aliases) > 1:
            aliases_str += '\nAliases: '
        else:
            aliases_str += '\nAlias: '
        aliases_str += ', '.join(cmd.aliases)
        aliases_str += '\n'

    see_also_str = ""
    see_also = cmd.get_see_also()
    if see_also:
        see_also_str += '\nSee also: '
        see_also_str += ', '.join(see_also)
        see_also_str += '\n'

    return subsection_header + option_str + aliases_str + see_also_str + "\n" + doc + "\n"


def format_alias(params, alias, cmd_name):
    help = '.SS "bzr %s"\n' % alias
    help += 'Alias for "%s", see "bzr %s".\n' % (cmd_name, cmd_name)
    return help


def environment_variables():
    yield ".SH \"ENVIRONMENT\"\n"

    from bzrlib.help_topics import known_env_variables
    for k, desc in known_env_variables:
        yield ".TP\n"
        yield ".I \"%s\"\n" % k
        yield man_escape(desc) + "\n"


man_preamble = """\
.\\\"Man page for Bazaar (%(bzrcmd)s)
.\\\"
.\\\" Large parts of this file are autogenerated from the output of
.\\\"     \"%(bzrcmd)s help commands\"
.\\\"     \"%(bzrcmd)s help <cmd>\"
.\\\"

.ie \\n(.g .ds Aq \\(aq
.el .ds Aq '
"""


man_head = """\
.TH bzr 1 "%(datestamp)s" "%(version)s" "Bazaar"
.SH "NAME"
%(bzrcmd)s - Bazaar next-generation distributed version control
.SH "SYNOPSIS"
.B "%(bzrcmd)s"
.I "command"
[
.I "command_options"
]
.br
.B "%(bzrcmd)s"
.B "help"
.br
.B "%(bzrcmd)s"
.B "help"
.I "command"
.SH "DESCRIPTION"

Bazaar (or %(bzrcmd)s) is a distributed version control system that is powerful, 
friendly, and scalable.  Bazaar is a project of Canonical Ltd and part of 
the GNU Project to develop a free operating system.

Bazaar keeps track of changes to software source code (or similar information);
lets you explore who changed it, when, and why; merges concurrent changes; and
helps people work together in a team.
"""

man_foot = """\
.SH "FILES"
.TP
.I "~/.bazaar/bazaar.conf"
Contains the user's default configuration. The section
.B [DEFAULT]
is used to define general configuration that will be applied everywhere.
The section
.B [ALIASES]
can be used to create command aliases for
commonly used options.

A typical config file might look something like:

.br
[DEFAULT]
.br
email=John Doe <jdoe@isp.com>
.br
[ALIASES]
.br
commit = commit --strict
.br
log10 = log --short -r -10..-1
.SH "SEE ALSO"
.UR http://bazaar.canonical.com/
.BR http://bazaar.canonical.com/
"""

