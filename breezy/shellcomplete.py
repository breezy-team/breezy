# Copyright (C) 2005, 2006, 2007, 2009, 2010 Canonical Ltd
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

import sys


def shellcomplete(context=None, outfile=None):
    if outfile is None:
        outfile = sys.stdout
    if context is None:
        shellcomplete_commands(outfile=outfile)
    else:
        shellcomplete_on_command(context, outfile=outfile)


def shellcomplete_on_command(cmdname, outfile=None):
    cmdname = str(cmdname)

    if outfile is None:
        outfile = sys.stdout

    from inspect import getdoc

    from . import commands

    cmdobj = commands.get_cmd_object(cmdname)

    doc = getdoc(cmdobj)
    if doc is None:
        raise NotImplementedError(
            "sorry, no detailed shellcomplete yet for {!r}".format(cmdname)
        )

    shellcomplete_on_options(cmdobj.options().values(), outfile=outfile)
    for aname in cmdobj.takes_args:
        outfile.write(aname + "\n")


def shellcomplete_on_options(options, outfile=None):
    for opt in options:
        short_name = opt.short_name()
        if short_name:
            outfile.write(
                '"(--{} -{})"{{--{},-{}}}\n'.format(
                    opt.name, short_name, opt.name, short_name
                )
            )
        else:
            outfile.write("--{}\n".format(opt.name))


def shellcomplete_commands(outfile=None):
    """List all commands."""
    from inspect import getdoc

    from . import commands

    commands.install_bzr_command_hooks()

    if outfile is None:
        outfile = sys.stdout

    cmds = []
    for cmdname in commands.all_command_names():
        cmd = commands.get_cmd_object(cmdname)
        cmds.append((cmdname, cmd))
        for alias in cmd.aliases:
            cmds.append((alias, cmd))
    cmds.sort()
    for cmdname, cmd in cmds:
        if cmd.hidden:
            continue
        doc = getdoc(cmd)
        if doc is None:
            outfile.write(cmdname + "\n")
        else:
            doclines = doc.splitlines()
            firstline = doclines[0].lower()
            outfile.write(cmdname + ":" + firstline[0:-1] + "\n")
