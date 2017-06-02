.. comment

  Copyright (C) 2010 Canonical Ltd

  This file is part of bzr-bash-completion

  bzr-bash-completion free software: you can redistribute it and/or
  modify it under the terms of the GNU General Public License as
  published by the Free Software Foundation, either version 2 of the
  License, or (at your option) any later version.

  bzr-bash-completion is distributed in the hope that it will be
  useful, but WITHOUT ANY WARRANTY; without even the implied warranty
  of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
  General Public License for more details.

  You should have received a copy of the GNU General Public License
  along with this program.  If not, see <http://www.gnu.org/licenses/>.

==========================
bzr bash-completion plugin
==========================

This plugin generates a shell function which can be used by bash to
automatically complete the currently typed command when the user
presses the completion key (usually tab).

It is intended as a bzr plugin, but can be used to some extend as a
standalone python script as well.

| Copyright (C) 2009, 2010 Canonical Ltd

.. contents::

-------------------------------
Bundled and standalone versions
-------------------------------

This plugin has been merged_ into the main source tree of Bazaar.
Starting with the bzr 2.3 series, a common bzr installation will
include this plugin.

There is still a standalone version available. It makes the plugin
available for users of older bzr versions. When using both versions,
local configuration might determine which version actually gets used,
and some installations might even overwrite one another, so don't use
the standalone version if you have the bundled one, unless you know
what you are doing. Some effort will be made to keep the two versions
reasonably in sync for some time yet.

This text here documents the bundled version.

.. _merged: http://bazaar.launchpad.net/~bzr-pqm/bzr/bzr.dev/revision/5240

-----
Using
-----

Using as a plugin
-----------------

This is the preferred method of generating the completion function, as
it will ensure proper bzr initialization.

::

  eval "`bzr bash-completion`"

Lazy initialization
-------------------

Running the above command automatically from your ``~/.bashrc`` file
or similar can cause annoying delays in the startup of your shell.
To avoid this problem, you can delay the generation of the completion
function until you actually need it.

To do so, source the file ``contrib/bash/bzr`` shipped with the bzr
source distribution from your ``~/.bashrc`` file
or add it to your ``~/.bash_completion`` if
your setup uses such a file. On a system-wide installation, the
directory ``/usr/share/bash-completion/`` might contain such bash
completion scripts.

Note that the full completion function is generated only once per
shell session. If you update your bzr installation or change the set
of installed plugins, then you might wish to regenerate the completion
function manually as described above in order for completion to take
these changes into account.

--------------
Design concept
--------------

The plugin is designed to generate a completion function
containing all the required information about the possible
completions. This is usually only done once when bash
initializes. After that, no more invocations of bzr are required. This
makes the function much faster than a possible implementation talking
to bzr for each and every completion. On the other hand, this has the
effect that updates to bzr or its plugins won't show up in the
completions immediately, but only after the completion function has
been regenerated.

-------
License
-------

As this is built upon a bash completion script originally included in
the bzr source tree, and as the bzr sources are covered by the GPL 2,
this plugin here is licensed under these same terms.

If you require a more liberal license, you'll have to contact all
those who contributed code to this plugin, be it for bash or for
python.

-------
History
-------

The plugin was created by Martin von Gagern in 2009, building on a
static completion function of very limited scope distributed together
with bzr.

A version of it was merged into the bzr source tree in May 2010.

----------
References
----------

Breezy homepage
  | https://www.breezy-vcs.org/



.. vim: ft=rst

.. emacs
   Local Variables:
   mode: rst
   End:
