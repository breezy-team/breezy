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

Interesting commands:

  bzr help [COMMAND]
      Show help screen
  bzr version
      Show software version/licence/non-warranty.
  bzr init
      Start versioning the current directory
  bzr add FILE...
      Make files versioned.
  bzr log
      Show revision history.
  bzr rename FROM TO
      Rename one file.
  bzr move FROM... DESTDIR
      Move one or more files to a different directory.
  bzr diff [FILE...]
      Show changes from last revision to working copy.
  bzr commit -m 'MESSAGE'
      Store current state as new revision.
  bzr export [-r REVNO] DESTINATION
      Export the branch state at a previous version.
  bzr status
      Show summary of pending changes.
  bzr remove FILE...
      Make a file not versioned.
  bzr info
      Show statistics about this branch.
  bzr check
      Verify history is stored safely. 
  (for more type 'bzr help commands')
"""


def help(topic=None):
    if topic == None:
        print global_help
    elif topic == 'commands':
        help_commands()
    else:
        help_on_command(topic)


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

    print 'usage: bzr ' + topic,
    for aname in cmdclass.takes_args:
        aname = aname.upper()
        if aname[-1] in ['$', '+']:
            aname = aname[:-1] + '...'
        elif aname[-1] == '?':
            aname = '[' + aname[:-1] + ']'
        elif aname[-1] == '*':
            aname = '[' + aname[:-1] + '...]'
        print aname,
    print 
    print short

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
        print cmdname
        help = inspect.getdoc(cmdclass)
        if help:
            print "    " + help.split('\n', 1)[0]
            

