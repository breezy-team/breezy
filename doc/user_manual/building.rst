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

By default it uses ``dpkg-buildpackage -uc -us -rfakeroot`` to build the
package. If you would prefer to use something else then you can use the
``--builder`` option to control this. For instance to build in a chroot
you can run

::

  $ bzr builddeb --builder pdebuild

If you would like to always build with a different command you can save
yourself from having to type it every time by changing your preferences.
See the `Configuration Files`_ section for how to do this.

.. _Configuration Files: configuration.html

If you have some changes to the package that you would like to test before
commiting then you can use the ``-w`` option to ``builddeb`` which tells the
plugin to build the working tree, rather than the latest version committed
to the branch

::

  $ bzr builddeb -w

If you have a slow builder defined in your configuration (see `Configuration
Files`_) then you may want to bypass this sometimes. If you are trying to
quickly test changes to a package you might just want a quick build. It
would be possible to do this by specifying ``--builder`` on the command
line, but this might be tiresome if you have a long command that takes a lot
of options. An alternative way to do this is to use the ``--quick`` option.
This option means that running

::

  $ bzr builddeb --quick

Uses the quick-builder. This command defaults to ``fakeroot debian/rules
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

.. vim: set ft=rst tw=76 :

