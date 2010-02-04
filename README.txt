.. comment

  Copyright (C) 2010  Martin von Gagern

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

=====================================
bzr bash-completion script and plugin
=====================================

This script generates a shell function which can be used by bash to
automatically complete the currently typed command when the user
presses the completion key (usually tab).

It is intended as a bzr plugin, but can be used to some extend as a
standalone python script as well.

| Copyright (C) 2009, 2010 Martin von Gagern <Martin.vGagern@gmx.net>

.. contents::

----------
Installing
----------

You only need to do this if you want to use the script as a bzr
plugin.  Otherwise simply grab the bashcomp.py and place it wherever
you want.

Installing from bzr repository
------------------------------

To check out the current code from launchpad, use the following commands::

  mkdir -p ~/.bazaar/plugins
  cd ~/.bazaar/plugins
  bzr co lp:bzr-bash-completion bash_completion

Installing using easy_install
-----------------------------

The following command should install the latest release of the plugin
on your system::

  easy_install bzr-bash-completion

-----
Using
-----

Using as a plugin
-----------------

This is the preferred method of generating initializing the
completion, as it will ensure proper bzr initialization.

::

  eval "`bzr bash-completion`"


Using as a script
-----------------

As an alternative, if bzrlib is available to python scripts, the
following invocation should yield the same results without requiring
you to add a plugin::

  eval "`./bashcomp.py`"

This approach might have some issues, though, and provides less
options than the bzr plugin. Therefore if you have the choice, go for
the plugin setup.

--------------
Design concept
--------------

The plugin (or script) is designed to generate a completion function
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
this script here is licensed under these same terms.

If you require a more liberal license, you'll have to contact all
those who contributed code to this plugin, be it for bash or for
python.

.. cut long_description here

-------
History
-------

The plugin was created by Martin von Gagern in 2009, building on a
static completion function of very limited scope distributed together
with bzr.

----------
References
----------

Plugin homepage
  https://launchpad.net/bzr-bash-completion
Bazaar homepage
  http://bazaar.canonical.com/



.. vim: ft=rst

.. emacs
   Local Variables:
   mode: rst
   End:
