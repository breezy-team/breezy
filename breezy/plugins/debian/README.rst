brz-debian
==========

Overview
--------

This is brz-debian, a plugin for `Breezy`_ that allows you to build `Debian`_
packages from a Breezy compatible branch, like a Git repository or a Bazaar
branch.

.. _Breezy: https://www.breezy-vcs.org/
.. _Debian: http://www.debian.org/

Note that there is a user manual available at
/usr/share/doc/brz-debian/user_manual/index.html that gives more
information than this file.

Installation
------------

This plugin requires `python-debian`_ and Breezy.

.. _python-debian: http://bzr.debian.org/pkg-python-debian/trunk/

It also requires the ``dpkg-dev`` package to be installed (for the
``dpkg-mergechangelogs`` tool)::

  apt install dpkg-dev

This plugin can be installed in two ways. As you are probably using a Debian
system you can probably just use the Debian packages. The other way is to
branch it in to ``~/.breezy/plugins/debian``, i.e::

  brz branch https://code.breezy-vcs.org/breezy-debian/trunk/ \
    ~/.config/breezy/plugins/debian

This will give you a ``brz builddeb`` command (alias ``bd``).

Help for this plugin can be found by running ``brz help builddeb``.

There is also a script named ``brz-buildpackage`` provided in /usr/bin
that provides access to the tool as well. It is just a wrapper script that
calls ``brz builddeb`` with the arguments you provide, so the rest of the
documentation applies equally well to using this script. Probably the only
difference is that help will be got with ``brz-buildpackage ---help``
(as ``brz builddeb --help`` also works and does the same as
``brz help builddeb``). The script is provided for two reasons, the first
is similarity to the other ``-buildpackage`` systems, and the second is so
that the Debian package can provide the ``brz-buildpackage`` package, and
so make it easier for people to find the package.

Configuration
-------------

There are also configuration files that can be used, these are, in the order
that values will be used if found::

  * .bzr-builddeb/local.conf (in the package directory)
  * ~/.bazaar/builddeb.conf
  * .bzr-builddeb/default.conf (in the package directory)

The last of these should be used for values that will be used by all users of
the package, for instance 'merge = True'. The others are for the user to add
or override settings that are specific to them, either globally or per package.

There is one complication to this however. As arbitrary commands can be
specified for some of the options there is a potential security hole. This
is closed by only taking these options from the configuration file in your
home directory, which can't be changed by another committer to the branch.
I apologise if this breaks your setup, and if you can't work around it please
talk to me to try to find an approach that satisfies you and does not open
any security holes.

These files must start with::

  [BUILDDEB]

Configuration Options
~~~~~~~~~~~~~~~~~~~~~

The following options are read from the configuration files. Most can also be
used as command line arguments by prepending ``--`` to the names and not using
the ``\=`` symbol. There are a few exceptions to this that are noted in the
descriptions.

Directories
###########

These change the directories that the plugin uses for various things.

  * ``build-dir = path``

    The directory in which the build takes place. (Defaults to
    ``../build-area`` relative to the branch).

  * ``result-dir = path``

    The directory the resulting files will be placed in. (Defaults to ``..``)

  * ``orig-dir = path``

    The directory to search for the ``.orig.tar.gz`` when not in native mode.
    (Defaults to ``..`` relative to the branch).

Modes
#####

These change the way in which the plugin operates. They can be set depending
on the type of package you are building.

  * ``merge = True``

    Turns on merge mode. This is where only the ``debian/`` directory is
    versioned. It uses and ``orig.tar.gz`` for the upstream and combines the
    two before building. It works with both the ``debian/`` directory in the
    branch, or the contents of ``debian/`` (e.g. ``rules``, ``control``)
    directly in the top level directory of the branch. (Defaults to ``False``).

  * ``native = True``

    If you want to build a native package from a branch then turn on this
    option. It will stop the plugin from looking for an ``orig.tar.gz`` and
    build a native package instead. This has no effect if merge mode is on,
    as I don't think it makes any sense to version the ``debian/`` separately
    for a native package. If you disagree let me know.

  * ``split = True``

    This takes a package from a branch that includes both the upstream source
    and the ``debian/`` dir and creates a non-native package from it by
    creating an ``orig.tar.gz`` from the code outside of ``debian/``. This
    is probably most useful if you are bot upstream and Debian maintainer
    of a non-native package. This has no effect if ``merge`` or ``native``
    are true, the former is for use when you don't version the full source,
    the second for when you don't need an ``orig.tar.gz`` so they make no sense
    to be used together.

  * ``export-upstream = path``

    This option takes a path (remote or local) to a brz branch that contains
    the upstream code. If this is set then the plugin will export the code
    from that branch to create the ``.orig.tar.gz``. This option only has any
    effect if ``merge`` is set.

  * ``export-upstream-revision = revision``

    This sets the revision that the upstream code will be branched at. It takes
    the same revision spec as the normal --revision parameter. Use it to
    associate an upstream version number with a particular revision of the
    upstream code. This has no effect if ``export-upstream`` is not set.

Builders
########

These configure the commands that are used to build the package in different
situations.

  * ``builder = command``

    The command to use to build the package. Defaults to ``debuild``).
    Will only be read from the file in your home directory.

  * ``quick-builder = command``

    The command used to build the package if the ``--quick`` option is used.
    (Defaults to ``fakeroot debian/rules binary``). Will only be read from
    the file in your home directory.

The idea is that certain options can be set in ``.bzr-builddeb/default.conf``
that apply to the package on all systems, or that there is a default that is
wanted that differs from the default provided. ``merge = True`` is a perfect
example of this.

Then the user can override this locally if they want for all of their packages
(they prefer ``builder = pdebuild``), so they can set this in
``~/.bazaar/builddeb.conf``. They can override it for the package if they want
(e.g. they have a different location for upstream tarballs of a package if
they are involved with upstream as well, so they set ``orig_dir =
/home/.../releases/``), this can be done in ``.bzr-builddeb/local.conf``).

Creating a package
------------------

Below are instructions for creating a package. These instructions differ
depending on whether you want to use merge mode or not.

First the common start create a directory to hold your work. This is not
absolutely necessary, but as you still get all the power of brz when using
this plugin, so you might want to branch etc. and so this will be useful
later on::

  $ mkdir path/to/project

If you are going to be using branches then the following is a good optimisation
you can use::

  $ brz init-repo --trees path/to/project

Now create your global config file if you want to change something like the
builder in use, or have a global result directory or similar::

  $ echo "[BUILDDEB]" > ~/.bazaar/builddeb.conf
  $ $EDITOR ~/.bazaar/builddeb.conf

and any options that you want.

I will describe creating a new project, but for existing projects you can
copy the code over and call ``brz init`` then continue in the same way.

I will also describe the setup that conforms to the default options for
directories. If you wish to use a different layout set up the options to
your liking and tweak the commands below as necessary.

Using merge mode
~~~~~~~~~~~~~~~~

Merge mode is when only the ``debian/`` directory of the package is versioned,
with the upstream version of the code living elsewhere. It allows for clear
separation of the Debian specific changes from the upstream code.

First copy the ``.orig.tar.gz`` file for the current version in to the parent
directory. If you do not have the upstream tarball for the current version,
but you do have a ``watch`` file detailing where it can be found then the
plugin will automatically retrieve the tarballs as they are needed.

Now create the branch for the ``debian/`` directory::

  $ brz init project

Now you can either create a ``project/debian/`` directory for all the files,
or add them in the ``project`` directory.

Now tell bzr-builddeb that this is a merge mode project::

  $ cd project/
  $ mkdir .bzr-builddeb/
  $ echo -e "[BUILDDEB]\nmerge = True" > .bzr-builddeb/default.conf

Now you are ready to create the project. Create the usual files, and edit them
to your satisfaction. When you have the files run::

  $ brz add
  $ brz ci

from the root of the project branch.

You are now ready to build the project. See below for instructions on doing
this.

Non-merge mode
~~~~~~~~~~~~~~

This is a little simpler to set up. Create the branch for the project::

  $ cd path/to/project
  $ brz init project

Now add all the project files to the branch, and add the to bzr::

  $ cd project
  $ brz add
  $ brz ci

There are two options when you want to build a Debian package, whether
it is a native package or not. Most packages are non-native so I will describe
that first.

To create a non-native package you need an upstream tarball to build against.
Set the ``orig-dir`` variable to the directory containing the tarball that
you want to use and the plugin will pick it up and you will have a non-native
package. If you do not have the upstream tarball corresponding to the version
of the package you are trying to build, but you have a ``watch`` file
detailing where it can be found then it will be automatically retrieved when
needed.

However sometimes you might be upstream of a package as well as Debian
maintainer, but it is not a native package. In that case you may version
the whole source including ``debian/``, but not want to have to manually
make a tarball without the ``debian/`` directory. In that case see the
``split`` variable. If you set that then the plugin will create you an
appropriately named orig.tar.gz of everything outside of ``debian/``.

If you want to have a native package you don't need to worry about
``orig-dir``, but instead set ``native = True`` in the
``.bzr-builddeb/default.conf`` file (make sure it starts with ``[BUILDDEB]``
if you create it).

Now you are ready to build using the plugin.

Building a Package
------------------

Once your package is set up then building it is easy. Run the following
command from the top-level of the project branch, after checking in all
changes::

  $ brz bd

If you used the default options this should build the package and leave the
resulting files in ``../build-area``.

Note that most of the options can be used as parameters to this command as well
by prefixing their name with ``--``. So you can do for example::

  $ brz bd --builder pdebuild

to change from what is in the configuration files. Note that there is currently
no way to set the binary options to false if they are set to true in the
configuration files. It would be possible to allow this, but it would bloat
the code and the help listings quite a lot, so I will only it if asked to.

Tips
----

If you have a slow builder defined in your configuration (for instance
``pdebuild``, you can bypass this by using the ``--quick`` option. This uses
whatever the ``quick_builder`` option is (defaults to ``fakeroot debian/rules
binary``).

If you are running in merge mode, and you have a large upstream tarball, and
you do not want to unpack it at every build you can speed things up even more.
This involves reusing the tarball each build, so saving the need to unpack it.
To do this run::

  $ brz bd --export-only

once to create a build-dir to use. (``-e`` is the short option for this). Then
on the next builds you can use the ``--reuse`` and ``--dont-purge`` options to
keep using this build directory. **N.B. This may cause build problems,
especially if files are removed**, it is advisable to run a build without
``--reuse`` after removing any files.

Workflow
--------

brz-debian is designed to fit in with the workflow that brz encourages. It
is designed as a plugin, so that it just becomes one more ``brz`` command that
you run while working on the package.

It also works fine with the frequent branching approach of brz, so that you
can branch to test something new for the package, or for a bug fix, and then
merge it back in to your main branch when it is done.
