# Copyright (C) 2004, 2005 by Canonical Ltd

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

global_help = \
"""Bazaar-NG -- a free distributed version-control tool
http://bazaar-ng.org/

WARNING: This is an unstable development version.
         Please keep backups.

Basic commands:

  bzr init      makes this branch versioned
  bzr branch    make a copy of another branch

  bzr add       make files or directories versioned
  bzr ignore    ignore a file or pattern
  bzr mv        move or rename a versioned file

  bzr status    summarize changes in working copy
  bzr diff      show detailed diffs

  bzr merge     pull in changes from another branch
  bzr commit    save some or all changes

  bzr log       show history of changes
  bzr check     validate storage

Use e.g. 'bzr help init' for more details, or
'bzr help commands' for all commands.
"""


import sys


def help(topic=None, outfile = None):
    if outfile == None:
        outfile = sys.stdout
    if topic == None:
        outfile.write(global_help)
    elif topic == 'commands':
        help_commands(outfile = outfile)
    else:
        help_on_command(topic, outfile = outfile)


def command_usage(cmdname, cmdclass):
    """Return single-line grammar for command.

    Only describes arguments, not options.
    """
    s = cmdname + ' '
    for aname in cmdclass.takes_args:
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


def help_on_command(cmdname, outfile = None):
    cmdname = str(cmdname)

    if outfile == None:
        outfile = sys.stdout

    from inspect import getdoc
    import commands
    topic, cmdclass = commands.get_cmd_class(cmdname)

    doc = getdoc(cmdclass)
    if doc == None:
        raise NotImplementedError("sorry, no detailed help yet for %r" % cmdname)

    outfile.write('usage: ' + command_usage(topic, cmdclass) + '\n')

    if cmdclass.aliases:
        outfile.write('aliases: ' + ', '.join(cmdclass.aliases) + '\n')
    
    outfile.write(doc)
    if doc[-1] != '\n':
        outfile.write('\n')
    
    help_on_option(cmdclass.takes_options, outfile = None)


def help_on_option(options, outfile = None):
    import commands
    
    if not options:
        return
    
    if outfile == None:
        outfile = sys.stdout

    outfile.write('\noptions:\n')
    for on in options:
        l = '    --' + on
        for shortname, longname in commands.SHORT_OPTIONS.items():
            if longname == on:
                l += ', -' + shortname
                break
        outfile.write(l + '\n')


def help_commands(outfile = None):
    """List all commands"""
    import inspect
    import commands

    if outfile == None:
        outfile = sys.stdout
    
    accu = []
    for cmdname, cmdclass in commands.get_all_cmds():
        accu.append((cmdname, cmdclass))
    accu.sort()
    for cmdname, cmdclass in accu:
        if cmdclass.hidden:
            continue
        outfile.write(command_usage(cmdname, cmdclass) + '\n')
        help = inspect.getdoc(cmdclass)
        if help:
            outfile.write("    " + help.split('\n', 1)[0] + '\n')

            

