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

"""man.py - create man page from built-in brz help and static text.

Todo:
  * use usage information instead of simple "brz foo" in COMMAND OVERVIEW
  * add command aliases
"""

PLUGINS_TO_DOCUMENT = ["launchpad"]

import textwrap

import breezy
import breezy.commands
import breezy.help
import breezy.help_topics
from breezy.doc_generate import get_autodoc_datetime

from ..plugin import load_plugins

load_plugins()


def get_filename(options):
    """Provides name of manpage."""
    return f"{options.brz_name}.1"


def infogen(options, outfile):
    """Assembles a man page."""
    d = get_autodoc_datetime()
    params = {
        "brzcmd": options.brz_name,
        "datestamp": d.strftime("%Y-%m-%d"),
        "timestamp": d.strftime("%Y-%m-%d %H:%M:%S +0000"),
        "version": breezy.__version__,
    }
    outfile.write(man_preamble % params)
    outfile.write(man_escape(man_head % params))
    outfile.write(man_escape(getcommand_list(params)))
    outfile.write(man_escape(getcommand_help(params)))
    outfile.write("".join(environment_variables()))
    outfile.write(man_escape(man_foot % params))


def man_escape(string):
    """Escapes strings for man page compatibility."""
    result = string.replace("\\", "\\\\")
    result = result.replace("`", "\\'")
    result = result.replace("'", "\\*(Aq")
    result = result.replace("-", "\\-")
    return result


def command_name_list():
    """Builds a list of command names from breezy."""
    command_names = breezy.commands.builtin_command_names()
    for cmdname in breezy.commands.plugin_command_names():
        cmd_object = breezy.commands.get_cmd_object(cmdname)
        if (
            PLUGINS_TO_DOCUMENT is None
            or cmd_object.plugin_name() in PLUGINS_TO_DOCUMENT
        ):
            command_names.append(cmdname)
    command_names.sort()
    return command_names


def getcommand_list(params):
    """Builds summary help for command names in manpage format."""
    params["brzcmd"]
    output = '.SH "COMMAND OVERVIEW"\n'
    for cmd_name in command_name_list():
        cmd_object = breezy.commands.get_cmd_object(cmd_name)
        if cmd_object.hidden:
            continue
        cmd_help = cmd_object.help()
        if cmd_help:
            firstline = cmd_help.split("\n", 1)[0]
            usage = cmd_object._usage()
            tmp = f'.TP\n.B "{usage}"\n{firstline}\n'
            output = output + tmp
        else:
            raise RuntimeError(f"Command '{cmd_name}' has no help text")
    return output


def getcommand_help(params):
    """Shows individual options for a brz command."""
    output = '.SH "COMMAND REFERENCE"\n'
    formatted = {}
    for cmd_name in command_name_list():
        cmd_object = breezy.commands.get_cmd_object(cmd_name)
        if cmd_object.hidden:
            continue
        formatted[cmd_name] = format_command(params, cmd_object)
        for alias in cmd_object.aliases:
            formatted[alias] = format_alias(params, alias, cmd_name)
    for cmd_name in sorted(formatted):
        output += formatted[cmd_name]
    return output


def format_command(params, cmd):
    """Provides long help for each public command."""
    subsection_header = f'.SS "{cmd._usage()}"\n'
    doc = f"{cmd.__doc__}\n"
    doc = breezy.help_topics.help_as_plain_text(cmd.help())

    # A dot at the beginning of a line is interpreted as a macro.
    # Simply join lines that begin with a dot with the previous
    # line to work around this.
    doc = doc.replace("\n.", ".")

    option_str = ""
    options = cmd.options()
    if options:
        option_str = "\nOptions:\n"
        for _option_name, option in sorted(options.items()):
            for name, short_name, argname, help in option.iter_switches():
                if option.is_hidden(name):
                    continue
                l = "    --" + name
                if argname is not None:
                    l += " " + argname
                if short_name:
                    l += ", -" + short_name
                l += (30 - len(l)) * " " + (help or "")
                wrapped = textwrap.fill(
                    l,
                    initial_indent="",
                    subsequent_indent=30 * " ",
                    break_long_words=False,
                )
                option_str += wrapped + "\n"

    aliases_str = ""
    if cmd.aliases:
        if len(cmd.aliases) > 1:
            aliases_str += "\nAliases: "
        else:
            aliases_str += "\nAlias: "
        aliases_str += ", ".join(cmd.aliases)
        aliases_str += "\n"

    see_also_str = ""
    see_also = cmd.get_see_also()
    if see_also:
        see_also_str += "\nSee also: "
        see_also_str += ", ".join(see_also)
        see_also_str += "\n"

    return (
        subsection_header + option_str + aliases_str + see_also_str + "\n" + doc + "\n"
    )


def format_alias(params, alias, cmd_name):
    """Formats an alias entry for the man page.

    Args:
        params: Dictionary containing parameters for string formatting.
        alias: The alias name to format.
        cmd_name: The name of the command this alias points to.

    Returns:
        Formatted string containing the alias documentation for the man page.
    """
    help = f'.SS "brz {alias}"\n'
    help += f'Alias for "{cmd_name}", see "brz {cmd_name}".\n'
    return help


def environment_variables():
    """Generates the environment variables section for the man page.

    Yields:
        Formatted strings for each environment variable known to Breezy,
        including section headers and properly escaped descriptions.
    """
    yield '.SH "ENVIRONMENT"\n'

    from breezy.help_topics import known_env_variables

    for k, desc in known_env_variables():
        yield ".TP\n"
        yield f'.I "{k}"\n'
        yield man_escape(desc) + "\n"


man_preamble = """\
.\\\"Man page for Breezy (%(brzcmd)s)
.\\\"
.\\\" Large parts of this file are autogenerated from the output of
.\\\"     \"%(brzcmd)s help commands\"
.\\\"     \"%(brzcmd)s help <cmd>\"
.\\\"

.ie \\n(.g .ds Aq \\(aq
.el .ds Aq '
"""


man_head = """\
.TH brz 1 "%(datestamp)s" "%(version)s" "Breezy"
.SH "NAME"
%(brzcmd)s - Breezy next-generation distributed version control
.SH "SYNOPSIS"
.B "%(brzcmd)s"
.I "command"
[
.I "command_options"
]
.br
.B "%(brzcmd)s"
.B "help"
.br
.B "%(brzcmd)s"
.B "help"
.I "command"
.SH "DESCRIPTION"

Breezy (or %(brzcmd)s) is a distributed version control system that is powerful,
friendly, and scalable.  Breezy is a fork of the Bazaar version control system.

Breezy keeps track of changes to software source code (or similar information);
lets you explore who changed it, when, and why; merges concurrent changes; and
helps people work together in a team.
"""

man_foot = """\
.SH "FILES"
.TP
.I "~/.config/breezy/breezy.conf"
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
.UR https://www.breezy-vcs.org/
.BR https://www.breezy-vcs.org/
"""
