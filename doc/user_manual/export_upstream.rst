Export-upstream mode
--------------------

Export-upstream mode is for use when upstream uses Bazaar for their revision
control, and does not make release tarballs that you can build against. It
creates an upstream tarball for you from the upstream branch, and then uses
that in the build.

It currently only works in merge mode, but it should also support normal
mode, and I hope to add this functionality at a later point.

This mode is also useful for automated builds of a package against an
upstream Bazaar branch at regular intervals, as it can be configured to just
build the latest version at the time the command is run.

This mode should also work against an upstream branch in another version
control system that Bazaar has native branch support for if you have the
appropriate plugin installed. Notably it is reported to work against an SVN
repository if `bzr-svn`_ is installed.

.. _bzr-svn: https://launchpad.net/bzr-svn/

Setting up the package
######################

Setting up a package to use export-upstream mode is very much like setting
it up to use merge mode. You should refer to the `instructions`_ for details
on how to do that, as the following only details how to change a merge mode
package in to an export-upstream mode package.

.. _instructions: merge.html

Creating a New Package
^^^^^^^^^^^^^^^^^^^^^^

Once you have created your merge mode package you need to tell
`bzr-builddeb` that you wish to use export-upstream mode for the package.
This is again a matter of editing the configuration file. The first value
you need to set is the ``export-upstream`` value. When this value is given
then it enables export-upstream mode. The value that you set for this should
be the URI of the branch that you wish to build against. This can be any URI
or path, as you would use for ``bzr branch`` say. The second value to set is
``export-upstream-revision``. This is the revision of the upstream branch
that you would like to build the package against. It can be specified in any
format that can be passed to a ``--r`` argument to a Bazaar command. This
includes revision numbers, revision ids prefixed by ``revid:``, or tags
prefixed by ``tag:``. See ``bzr help revisionspec`` for all of the values that
can be used here. Note that using a revision number may be unstable, it is
better to look up the revision id and use that instead, or use a tag if there
is one present.

A typical configuration file would then look like::

  [BUILDDEB]
  merge = True
  export-upstream = http://scruff.org/bzr/scruff.dev/
  export-upstream-revision = tag:scruff-0.1

It can be expensive to pull the revision from a remote location, and so it
is possible to use a local mirror. The value of ``export-upstream`` in
``.bzr-builddeb/default.conf`` should still be set to a public branch as
above though, for people that wish to build the package, but do not have a
local mirror.  What you should do instead is set ``export-upstream`` to your
local mirror in ``.bzr/branch/branch.conf``, like::

  [BUILDDEB]
  export-upstream = /home/user/work/scruff/trunk/

See `Configuration Files`_ for more information.

.. _Configuration Files: configuration.html

New upstream version
####################

To update to a new upstream version you need to do three things. The first
of these is to tell `bzr-builddeb` to build against the new version of the
upstream code. To do this edit ``.bzr-builddeb/default.con`` and set
``export-upstream-revision`` to the revision of the new version of the code
that you want to build.

The next step is to update the version recorded in ``debian/changelog``. The
``dch`` tool from ``devscripts`` can help you here, to update to version
``0.2`` you can run::

  $ dch -v 0.2-1

The last step is to adapt the packaging to any changes in the upstream code.
There are some comments in the documentation of ``merge mode`` about doing
this that also apply here.

.. _merge mode: merge.html

Once you have completed the three steps you can commit the new version and
build the package. `bzr-builddeb` will see that there is a new version and
export the new revision of the upstream branch to create the upstream
tarball.

.. vim: set ft=rst tw=76 :

