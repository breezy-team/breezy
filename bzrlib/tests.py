#! /usr/bin/env python
# -*- coding: UTF-8 -*-

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



# XXX: We might prefer these to be in a text file rather than Python
# source, but that only works in doctest from Python 2.4 and later,
# which is not present in Warty.

r"""
Bazaar-NG test cases
********************

These are run by ``bzr.doctest``.

>>> import bzrlib, os
>>> bzrlib.commands.cmd_rocks()
it sure does!

Hey, nice place to begin.

The basic object is a Branch.  We have a special helper class
ScratchBranch that automatically makes a directory and cleans itself
up, but is in other respects identical.

ScratchBranches are initially empty:

>>> b = bzrlib.ScratchBranch()
>>> b.show_status()

New files in that directory are, it is initially unknown:

>>> file(b.base + '/hello.c', 'wt').write('int main() {}')
>>> b.show_status()
?       hello.c

That's not quite true; some files (like editor backups) are ignored by
default:

>>> file(b.base + '/hello.c~', 'wt').write('int main() {}')
>>> b.show_status()
?       hello.c
>>> list(b.unknowns())
['hello.c']

The ``add`` command marks a file to be added in the next revision:

>>> b.add('hello.c')
>>> b.show_status()
A       hello.c

You can also add files that otherwise would be ignored.  The ignore
patterns only apply to files that would be otherwise unknown, so they
have no effect once it's added.

>>> b.add('hello.c~')
>>> b.show_status()
A       hello.c
A       hello.c~

It is an error to add a file that isn't present in the working copy:

  >>> b.add('nothere')
  Traceback (most recent call last):
  ...
  BzrError: ('cannot add: not a regular file or directory: nothere', [])

If we add a file and then change our mind, we can either revert it or
remove the file.  If we revert, we are left with the working copy (in
either I or ? state).  If we remove, the working copy is gone.  Let's
do that to the backup, presumably added accidentally.

  >>> b.remove('hello.c~')
  >>> b.show_status()
  A       hello.c

Now to commit, creating a new revision.  (Fake the date and name for
reproducibility.)

  >>> b.commit('start hello world', timestamp=0, committer='foo@nowhere')
  >>> b.show_status()
  >>> b.show_status(show_all=True)
  .       hello.c
  I       hello.c~


We can look back at history

  >>> r = b.get_revision(b.lookup_revision(1))
  >>> r.message
  'start hello world'
  >>> b.write_log(show_timezone='utc')
  ----------------------------------------
  revno: 1
  committer: foo@nowhere
  timestamp: Thu 1970-01-01 00:00:00 +0000
  message:
    start hello world

(The other fields will be a bit unpredictable, depending on who ran
this test and when.)

As of 2005-02-21, we can also add subdirectories to the revision!

  >>> os.mkdir(b.base + "/lib")
  >>> b.show_status()
  ?       lib/
  >>> b.add('lib')
  >>> b.show_status()
  A       lib/
  >>> b.commit('add subdir')
  >>> b.show_status()
  >>> b.show_status(show_all=True)
  .       hello.c
  I       hello.c~
  .       lib/

and we can also add files within subdirectories:

  >>> file(b.base + '/lib/hello', 'w').write('hello!\n')
  >>> b.show_status()
  ?       lib/hello
  
  
Tests for adding subdirectories, etc.

    >>> b = bzrlib.branch.ScratchBranch()
    >>> os.mkdir(b._rel('d1'))
    >>> os.mkdir(b._rel('d2'))
    >>> os.mkdir(b._rel('d2/d3'))
    >>> list(b.working_tree().unknowns())
    ['d1', 'd2']

Create some files, but they're not seen as unknown yet:

    >>> file(b._rel('d1/f1'), 'w').close()
    >>> file(b._rel('d2/f2'), 'w').close()
    >>> file(b._rel('d2/f3'), 'w').close()
    >>> [v[0] for v in b.inventory.directories()]
    ['']
    >>> list(b.working_tree().unknowns())
    ['d1', 'd2']

Adding a directory, and we see the file underneath:
    
    >>> b.add('d1')
    >>> [v[0] for v in b.inventory.directories()]
    ['', 'd1']
    >>> list(b.working_tree().unknowns())
    ['d1/f1', 'd2']
    >>> # d2 comes first because it's in the top directory

    >>> b.add('d2')
    >>> b.commit('add some stuff')
    >>> list(b.working_tree().unknowns())
    ['d1/f1', 'd2/d3', 'd2/f2', 'd2/f3']

    >>> b.add('d1/f1')
    >>> list(b.working_tree().unknowns())
    ['d2/d3', 'd2/f2', 'd2/f3']

"""
