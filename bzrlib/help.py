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

**WARNING: THIS IS AN UNSTABLE DEVELOPMENT VERSION**

* Metadata format is not stable yet -- you may need to
  discard history in the future.

* Many commands unimplemented or partially implemented.

* Space-inefficient storage.

* No merge operators yet.


To make a branch, use 'bzr init' in an existing directory, then 'bzr
add' to make files versioned.  'bzr add .' will recursively add all
non-ignored files.

'bzr status' describes files that are unknown, ignored, or modified.
'bzr diff' shows the text changes to the tree or named files.
'bzr commit -m <MESSAGE>' commits all changes in that branch.

'bzr move' and 'bzr rename' allow you to rename files or directories.
'bzr remove' makes a file unversioned but keeps the working copy;
to delete that too simply delete the file.

'bzr log' shows a history of changes, and
'bzr info' gives summary statistical information.
'bzr check' validates all files are stored safely.

Files can be ignored by giving a path or a glob in .bzrignore at the
top of the tree.  Use 'bzr ignored' to see what files are ignored and
why, and 'bzr unknowns' to see files that are neither versioned or
ignored.

For more help on any command, type 'bzr help COMMAND', or 'bzr help
commands' for a list.
"""



def help(topic=None):
    if topic == None:
        print global_help
    elif topic == 'commands':
        help_commands()
    else:
        help_on_command(topic)


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


def help_on_command(cmdname):
    cmdname = str(cmdname)

    from inspect import getdoc
    import commands
    topic, cmdclass = commands.get_cmd_class(cmdname)

    doc = getdoc(cmdclass)
    if doc == None:
        raise NotImplementedError("sorry, no detailed help yet for %r" % cmdname)

    if '\n' in doc:
        short, rest = doc.split('\n', 1)
    else:
        short = doc
        rest = ''

    print 'usage:', command_usage(topic, cmdclass)

    if cmdclass.aliases:
        print 'aliases: ' + ', '.join(cmdclass.aliases)
    
    if rest:
        print rest

    help_on_option(cmdclass.takes_options)


def help_on_option(options):
    import commands
    
    if not options:
        return
    
    print
    print 'options:'
    for on in options:
        l = '    --' + on
        for shortname, longname in commands.SHORT_OPTIONS.items():
            if longname == on:
                l += ', -' + shortname
                break
        print l


def help_commands():
    """List all commands"""
    import inspect
    import commands
    
    accu = []
    for cmdname, cmdclass in commands.get_all_cmds():
        accu.append((cmdname, cmdclass))
    accu.sort()
    for cmdname, cmdclass in accu:
        if cmdclass.hidden:
            continue
        print command_usage(cmdname, cmdclass)
        help = inspect.getdoc(cmdclass)
        if help:
            print "    " + help.split('\n', 1)[0]
            

