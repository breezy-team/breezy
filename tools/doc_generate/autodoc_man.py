#!/usr/bin/python

# Copyright 2005 Canonical Ltd.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""big_man.py - create man page from built-in bzr help and static text

TODO:
  * use usage information instead of simple "bzr foo" in COMMAND OVERVIEW
  * add command aliases
"""

import os, sys
import bzrlib, bzrlib.help, bzrlib.commands
import textwrap
import time


def get_filename(options):
    return "%s.1" % (options.bzr_name)


def infogen(options, outfile):
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

    outfile.write(man_escape(man_foot % params))


def man_escape(string):
    result = string.replace("\\","\\\\")
    result = result.replace("`","\\`")
    result = result.replace("'","\\'")
    result = result.replace("-","\\-")
    return result


def command_name_list():
    command_names = bzrlib.commands.builtin_command_names()
    command_names.sort()
    return command_names


def getcommand_list (params):
    bzrcmd = params["bzrcmd"]
    output = '.SH "COMMAND OVERVIEW"\n'
    for cmd_name in command_name_list():
        cmd_object = bzrlib.commands.get_cmd_object(cmd_name)
        if cmd_object.hidden:
            continue
        cmd_help = cmd_object.help()
        if cmd_help:
            firstline = cmd_help.split('\n', 1)[0]
            usage = bzrlib.help.command_usage(cmd_object)
            tmp = '.TP\n.B "%s"\n%s\n' % (usage, firstline)
            output = output + tmp
        else:
            raise RuntimeError, "Command '%s' has no help text" % (cmd_name)
    return output


def format_command (params, cmd):
    subsection_header = '.SS "%s"\n' % (bzrlib.help.command_usage(cmd))
    doc = "%s\n" % (cmd.__doc__)
    docsplit = cmd.__doc__.split('\n')
    doc = '\n'.join([docsplit[0]] + [line[4:] for line in docsplit[1:]])

    option_str = ""
    options = cmd.options()
    # option walk code stolen from bzrlib/help.py
    if options:
        option_str = "\nOptions:\n"
        for option_name, option in sorted(options.items()):
            l = '    --' + option_name
            if option.type is not None:
                l += ' ' + option.argname.upper()
            short_name = option.short_name()
            if short_name:
                assert len(short_name) == 1
                l += ', -' + short_name
            l += (30 - len(l)) * ' ' + option.help
            # TODO: split help over multiple lines with correct indenting and 
            # wrapping
            wrapped = textwrap.fill(l, initial_indent='',
                                    subsequent_indent=30*' ')
            option_str = option_str + wrapped + '\n'       
    return subsection_header + option_str + "\n" + doc + "\n"


def getcommand_help(params):
    output='.SH "COMMAND REFERENCE"\n'
    for cmd_name in command_name_list():
        cmd_object = bzrlib.commands.get_cmd_object(cmd_name)
        if cmd_object.hidden:
            continue
        output = output + format_command(params, cmd_object)
    return output


man_head = """\
.TH bzr 1 "%(datestamp)s" "%(version)s" "bazaar-ng"
.SH "NAME"
%(bzrcmd)s - bazaar-ng next-generation distributed version control
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
bazaar-ng (or
.B "%(bzrcmd)s"
) is a project of Canonical Ltd. to develop an open source distributed version control system that is powerful, friendly, and scalable. Version control means a system that keeps track of previous revisions of software source code or similar information and helps people work on it in teams.
.SS "Warning"
bazaar-ng is at an early stage of development, and the design is still changing from week to week. This man page here may be inconsistent with itself, with other documentation or with the code, and sometimes refer to features that are planned but not yet written. Comments are still very welcome; please send them to bazaar-ng@lists.canonical.com.

.SH "USAGE"
Commands for a number of common use cases.

.SS "Create a branch"
    $ cd my-project
    $ %(bzrcmd)s init

.SS "Add files to be versioned"
    $ cd my-project
    $ %(bzrcmd)s add hello-world.c Makefile

.SS "Review local changes"
    $ cd my-project
    $ %(bzrcmd)s status
    $ %(bzrcmd)s diff

.SS "Commit changes to branch"
    $ cd my-project
    $ %(bzrcmd)s commit -m \"initial import of files\"

.SS "Branching off an existing branch"
    $ %(bzrcmd)s branch http://other.com/project-foo
    $ cd project-foo

    $ %(bzrcmd)s branch http://other.com/project-foo foo-by-other
    $ cd foo-by-other
    
    $ %(bzrcmd)s branch foo-by-other foo-with-my-changes
    $ cd foo-with-my-changes

.SS "Following upstream changes"
If you have not modified anything in your local branch:
    $ cd foo-by-other
    $ %(bzrcmd)s pull

If you have modified and committed things in your local branch:
    $ cd foo-with-my-changes
    $ %(bzrcmd)s merge

.SS "Publishing your changes"
Publishing your branch for the first time:
    $ cd foo-with-my-changes
    $ %(bzrcmd)s push sftp://user@host/public_html/foo-with-my-changes

Publishing your branch subsequently is easier as %(bzrcmd)s remembers the push location:
    $ cd foo-with-my-changes
    $ %(bzrcmd)s push
    
"""


man_foot = """\
.SH "EXAMPLES"
See
.UR http://bazaar.canonical.com/IntroductionToBzr
.BR http://bazaar.canonical.com/IntroductionToBzr
.SH "ENVIRONMENT"
.TP
.I "BZR_HOME"
Per-user \'home\' directory. Default on Unix like systems is
.I "~"
.TP
.I "BZRPATH"
Path where
.B "%(bzrcmd)s"
is to look for external command.
.TP
.I "BZREMAIL"
E-Mail address of the user. Overrides settings from
.I "~/.bazaar/bazaar.conf" and
.IR "EMAIL" .
Example content:
  John Doe <john@example.com>
.TP
.I "EMAIL"
E-Mail address of the user. Overridden by the settings in the file
.I "~/.bazaar/bazaar.conf"
and of the environment variable
.IR "BZREMAIL" .
.SH "FILES"
.TP
.I "~/.bazaar/"
Directory where all the user\'s settings are stored.
.TP
.I "~/.bazaar/bazaar.conf"
Stores default settings like name and email address of the
user. Settings in this file override the content of
.I "EMAIL"
environment variable. Example content:

  [DEFAULT]
  email=John Doe <john@example.com>
  editor=/usr/bin/vim
  check_signatures=check-available
  create_signatures=when-required

.TP
.I "~/.bazaar/branches.conf"
Override settings for a specific branch in this file. The sections in this file are named after the locations of the branch, and the settings in that section look just like the ones in the
.B DEFAULT
section of the
.I "~/.bazaar/bazaar.conf"
file. Example:

  [/home/john/src/boofar.dev-john]
  email="John Doe <john@boofar.example.com>

  [http://erk.example.com/boo]
  check_signatures=always

.SH "SEE ALSO"
.UR http://www.bazaar-ng.org/
.BR http://www.bazaar-ng.org/,
.UR http://www.bazaar-ng.org/doc/
.BR http://www.bazaar-ng.org/doc/,
.UR http://bazaar.canonical.com/BzrDocumentation
.BR http://bazaar.canonical.com/BzrDocumentation
"""


man_preamble = """\
.\\\" Man page for %(bzrcmd)s (bazaar-ng)
.\\\"
.\\\" Large parts of this file are autogenerated from the output of
.\\\"     \"%(bzrcmd)s help commands\"
.\\\"     \"%(bzrcmd)s help <cmd>\"
.\\\"
.\\\" Generation time: %(timestamp)s
.\\\"
"""
