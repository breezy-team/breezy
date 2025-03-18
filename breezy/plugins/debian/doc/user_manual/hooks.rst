Using Hooks
===========

Hooks are the ability to run an arbitrary command at pre-defined points in the
build process. This can be useful for several purposes, for instance updating
the changelog to record which person built the package, or running autotools
before building the package.

You should consider carefully whether hooks are the right tool to solve your
problem, as they are specific to `bzr-builddeb`, and so you may make it more
difficult for someone not using the plugin to build the package.

Hook points
-----------

The following are the pre-defined hooks that are available when building the
package. More hook points could be added if you have a specific need, contact
me to discuss it if that is the case.

  * ``merge-upstream`` - This is run after a new upstream version has
     been merged into the current tree using ``bzr merge-upstream``.
     This allows you to update the debian/ metadata based on the new upstream
     release that has been merged in.

  * ``pre-export`` - This is run before the branch is exported to create
     the build directory. This allows you to modify the branch or the working
     tree. Note however that the tree to export is grabbed before the hook is
     run if you use the ``--revision`` option. This means that if you use
     ``--revision -1`` and run ``bzr commit`` in this hook, the revision before
     the commit will exported, rather than the new one that is created. This
     hook is run with the root of the branch as the working directory.

  * ``pre-build`` - This is run before the package is built, but after it
     has been exported. This allows you to modify the files that will be built,
     but not affect the files in the branch. If you are using merge mode then
     this hook will have the full source of the package available, including
     the upstream source. This hook is run with the root of the exported
     package as the working directory.

  * ``post-build`` - This is run after the package has been built, if the
     build was successful. This allows you to examine the result of the build.
     This hook is run with the root of the exported package as the working
     directory.

Setting hooks
-------------

Hooks are set by editing the configuration files. The normal precedence
rules for these files are followed (see `configuration`_ for details). This
means that you should set hooks needed to build the package in
``debian/bzr-builddeb.conf``, and any hooks that you would like to run
that would not be appropriate for everyone in ``.bzr-builddeb/local.conf``.
Note however that the latter overrides the formula, so your local hooks should
run all necessary commands from the default hooks that are necessary to build
the package.

.. _configuration: configuration.html

The hooks are set in a ``[HOOKS]`` section of the configuration file. The
key is the hook point that the hook is set for, the value is the command(s)
to run. For instance to run autoconf before building you would set the
following::

  [HOOKS]
  pre-build = autoconf

The command is run through the shell, so you can do things like use ``&&`` to
run multiple commands.

If the command fails then it will stop the build.

