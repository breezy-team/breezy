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
  bzr checkout lp:bzr-bash-completion bash_completion

To update such an installation, execute this command::

  bzr update ~/.bazaar/plugins/bash_completion

Installing using easy_install
-----------------------------

The following command should install the latest release of the plugin
on your system::

  easy_install bzr-bash-completion

To use this method, you need to have `Easy Install`_ installed and
also have write access to the required directories. So maybe you
should execute this command as root or through sudo_. Or you want to
`install to a different location`_.

.. _Easy Install: http://peak.telecommunity.com/DevCenter/EasyInstall
.. _sudo: http://linux.die.net/man/8/sudo
.. _install to a different location:
   http://peak.telecommunity.com/DevCenter/EasyInstall#non-root-installation

Installing from tarball
-----------------------

If you have grabbed a source code tarball, or want to install from a
bzr checkout in a different place than your bazaar plugins directory,
then you should use the ``setup.py`` script shipped with the code::

  ./setup.py install

If you want to install the plugin only for your own user account, you
might wish to pass the option ``--user`` or ``--home=$HOME`` to that
command. For further information please read the manuals of distutils_
as well as setuptools_ or distribute_, whatever is available on your
system, or have a look at the command line help::

  ./setup.py install --help

.. _distutils: http://docs.python.org/install/index.html
.. _setuptools: http://peak.telecommunity.com/DevCenter/setuptools#what-your-users-should-know
.. _distribute: http://packages.python.org/distribute/setuptools.html#what-your-users-should-know

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

To do so, source the file ``lazy.sh`` shipped with this package from
your ``~/.bashrc`` file or add it to your ``~/.bash_completion`` if
your setup uses such a file. On a system-wide installation, the
directory ``/usr/share/bash-completion/`` might contain such bash
completion scripts.

If you installed bzr-bash-completion from the repository or a source
tarball, you find the ``lazy.sh`` script in the root of the source
tree. If you installed the plugin using easy_install, you should grab
the script manually from the bzr repository, e.g. through the bazaar
web interface on launchpad.

Note that the full completion function is generated only once per
shell session. If you update your bzr installation or change the set
of installed plugins, then you might wish to regenerate the completion
function manually as described above in order for completion to take
these changes into account.

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

Plugin homepages
  | https://launchpad.net/bzr-bash-completion
  | http://pypi.python.org/pypi/bzr-bash-completion
Bazaar homepage
  | http://bazaar.canonical.com/



.. vim: ft=rst

.. emacs
   Local Variables:
   mode: rst
   End:
