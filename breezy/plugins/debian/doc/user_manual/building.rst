Building a package
------------------

When you are ready to build the package you can issue the simple command

::

  $ bzr builddeb

This will build the package and place it in ``../build-area/``. There is
also an alias of ``bd`` provided for this, so that

:: 

  $ bzr bd

will do the same thing.

By default it uses ``debuild`` to build the package. If you would prefer
to use something else then you can use the ``--builder`` option to control
this. For instance to build in a pbuilder chroot you can run

::

  $ bzr builddeb --builder pdebuild

If you would like to always build with a different command you can save
yourself from having to type it every time by changing your preferences.
See the `Configuration Files`_ section for how to do this.

.. _Configuration Files: configuration.html

If you wish to pass extra options to the builder, such as ``-v`` then you
can do it by specifying them after ``--`` on the command line, e.g.

::

  $ bzr builddeb -- -v0.1-1

At this point you should specify the ``-S`` option before the ``--`` so that
the tool knows that you are building a source package.

If you have a slow builder defined in your configuration (see `Configuration
Files`_) then you may want to bypass this sometimes. If you are trying to
quickly test changes to a package you might just want a quick build. It
would be possible to do this by specifying ``--builder`` on the command
line, but this might be tiresome if you have a long command that takes a lot
of options. An alternative way to do this is to use the ``--quick`` option.
This option means that running

::

  $ bzr builddeb --quick

uses the quick-builder. This command defaults to ``fakeroot debian/rules
binary``, but you can set the ``quick-builder`` option in a configuration
file if you wish to customise it.

If you are running in merge mode and you have a large upstream tarball that
takes a while to unpack, you can avoid having to wait for that on every
build by unpacking it once and then reusing the unpacked source. To do this
you need to export the package from the branch once::

  $ bzr builddeb --export-only

and then on each subsequent build use the ``--reuse`` and ``-dont-purge``
options. **N.B. This may cause spurious build failures, especially if files
are removed**, it is advisable to build without ``--reuse`` after removing
any files. If you still build with ``--dont-purge`` then you will be able to
reuse again on the next build with both ``--dont-purge`` and ``--reuse``.

``--export-only`` is also useful for other tasks, especially when running in
merge mode, for instance getting a full build directory to test things out,
or to manipulate patches.

There are many more options available when building. The output of

::

  $ bzr help builddeb

lists them all.

Remote Branches
---------------

It is possible to build directly from remote branches, e.g.::

  $ bzr builddeb http://bzr.debian.org/pkg-bazaar/bzr-builddeb/trunk/

This doesn't require you to have any of the branch history locally, and will
just download what is needed to build the branch.

If you do not have different directories set in ``~/.bazaar/builddeb.conf``
then all actions will take place within ``./build-area/``, which should
avoid overwriting any files that you wish to keep.

.. vim: set ft=rst tw=76 :

