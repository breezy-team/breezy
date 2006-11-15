# Copyright (C) 2005, 2006 Canonical Ltd
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

import sys


def shellcomplete(context=None, outfile = None):
    if outfile is None:
        outfile = sys.stdout
    if context is None:
        shellcomplete_commands(outfile = outfile)
    else:
        shellcomplete_on_command(context, outfile = outfile)

def shellcomplete_on_command(cmdname, outfile = None):
    cmdname = str(cmdname)

    if outfile is None:
        outfile = sys.stdout

    from inspect import getdoc
    import commands
    cmdobj = commands.get_cmd_object(cmdname)

    doc = getdoc(cmdobj)
    if doc is None:
        raise NotImplementedError("sorry, no detailed shellcomplete yet for %r" % cmdname)

    shellcomplete_on_option(cmdobj.takes_options, outfile = None)
    for aname in cmdobj.takes_args:
        outfile.write(aname + '\n')


def shellcomplete_on_option(options, outfile=None):
    from bzrlib.option import Option
    if not options:
        return
    if outfile is None:
        outfile = sys.stdout
    for on in options:
        for shortname, longname in Option.SHORT_OPTIONS.items():
            if longname == on:
                l = '"(--' + on + ' -' + shortname + ')"{--' + on + ',-' + shortname + '}'
                break
            else:
                l = '--' + on
        outfile.write(l + '\n')


def shellcomplete_commands(outfile = None):
    """List all commands"""
    import inspect
    import commands
    from inspect import getdoc
    
    if outfile is None:
        outfile = sys.stdout
    
    cmds = []
    for cmdname, cmdclass in commands.get_all_cmds():
        cmds.append((cmdname, cmdclass))
        for alias in cmdclass.aliases:
            cmds.append((alias, cmdclass))
    cmds.sort()
    for cmdname, cmdclass in cmds:
        if cmdclass.hidden:
            continue
        doc = getdoc(cmdclass)
        if doc is None:
            outfile.write(cmdname + '\n')
        else:
            doclines = doc.splitlines()
            firstline = doclines[0].lower()
            outfile.write(cmdname + ':' + firstline[0:-1] + '\n')
