Configuration files
-------------------

There are also configuration files that can be used, these are, in the order
that values will be used if found::

  * .bzr-builddeb/local.conf (in the package directory)
  * ~/.bazaar/builddeb.conf
  * debian/bzr-builddeb.conf (in the package directory)
  * .bzr-builddeb/default.conf (in the package directory, deprecated)

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
#####################

The following options are read from the configuration files. Most can also be
used as command line arguments by prepending ``--`` to the names and not using
the ``=`` symbol. There are a few exceptions to this that are noted in the
descriptions.

Directories
^^^^^^^^^^^

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
^^^^^

These change the way in which the plugin operates. They can be set depending
on the type of package you are building. If none of these are set then
`normal mode`_ is used.

  * ``merge = True``

    Turns on `merge mode`_. This is where only the ``debian/`` directory is 
    versioned. It uses an ``orig.tar.gz`` for the upstream and combines the
    two before building. It works with both the ``debian/`` directory in the 
    branch, or the contents of ``debian/`` (e.g. ``rules``, ``control``) 
    directly in the top level directory of the branch. (Defaults to ``False``).

  * ``native = True``

    If you want to build a native package from a branch then turn on this
    option. It will stop the plugin from looking for an ``orig.tar.gz`` and
    build a native package instead. This has no effect if merge mode is on,
    as I don't think it makes any sense to version the ``debian/`` separately
    for a native package. If you disagree let me know. See `native mode`_.

  * ``split = True``

    This takes a package from a branch that includes both the upstream source
    and the ``debian/`` dir and creates a non-native package from it by
    creating an ``orig.tar.gz`` from the code outside of ``debian/``. This
    is probably most useful if you are both upstream and Debian maintainer
    of a non-native package. This has no effect if ``merge`` or ``native``
    are true, the former is for use when you don't version the full source,
    the second for when you don't need an ``orig.tar.gz`` so they make no sense
    to be used together. See `split mode`_.

.. _normal mode: normal.html
.. _merge mode: merge.html
.. _native mode: native.html
.. _split mode: split.html

Interaction with an upstream branch
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

When the upstream source is in ``bazaar`` it is possible to have the
``.orig.tar.gz`` created by exporting the upstream branch. To do this set
the ``upstream-branch`` option. This only works only for merge mode. For
normal mode use the ``merge-upstream`` command.

  * ``upstream-branch = path``

    This option takes a path (remote or local) to a bzr branch that contains
    the upstream code. If this is set then the plugin will export the code
    from that branch to create the ``.orig.tar.gz`` if needed. This option
    only has effect if ``merge`` is set.

  * ``export-upstream-revision = revision``

    This sets the revision that the upstream code will be branched at. It takes
    the same revision spec as the normal --revision parameter. Use it to
    associate an upstream version number with a particular revision of the
    upstream code. This has no effect if ``upstream-branch`` is not set.


Committing
^^^^^^^^^^

When there are quilt patches applied in the current tree, ``bzr commit``
will by default warn::

  $ bzr commit
  Committing with 5 quilt patches applied.
  Committing to: /tmp/popt/
  Committed revision 20.

It is also possible to force it to always make sure that quilt patches
are unapplied or applied during a commit by setting the
``quilt.commit_policy`` to either ``applied`` or ``unapplied``.

Builders
^^^^^^^^

These configure the commands that are used to build the package in different
situations.

  * ``builder = command``

    The command to use to build the package. Defaults to ``debuild``.
    Will only be read from the file in your home directory.

  * ``quick-builder = command``

    The command used to build the package if the ``--quick`` option is used. 
    (Defaults to ``fakeroot debian/rules binary``). Will only be read from
    the config file in your home directory.

The idea is that certain options can be set in ``debian/bzr-builddeb.conf`` 
that apply to the package on all systems, or that there is a default that is 
wanted that differs from the default provided. ``merge = True`` is a perfect 
example of this.

Then the user can override this locally if they want for all of their packages
(they prefer ``builder = pdebuild``), so they can set this in 
``~/.bazaar/builddeb.conf``. They can override it for the package if they want 
(e.g. they have a different location for upstream tarballs of a package if
they are involved with upstream as well, so they set ``orig_dir = 
/home/.../releases/``), this can be done in ``.bzr-builddeb/local.conf``.

