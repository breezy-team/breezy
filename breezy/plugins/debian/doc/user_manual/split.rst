Split mode
----------

Split mode is quite a specialised mode. It is for people who are both the
upstream author and maintainer of a package. It allows you to maintain both
in a single branch, but have a separation during the build, and not have to
create the upstream tarball by hand.

Some people like this way of working, but it does make it harder for someone
else to take over maintenance of the package at a later date.

This mode should not be used by those who are not the upstream author of a
package, and who are not making the upstream tarball releases.

This mode is a mixture of most of the other modes. You have the upstream
code and the packaging in the same branch like `normal mode`_ and
`native mode`_, but the only packaging changes can be in the ``debian/``
directory, like `merge mode`_.

.. _normal mode: normal.html
.. _native mode: native.html
.. _merge mode: merge.html

Setting up the package
######################

Before creating the package it may be beneficial to set up a shared
repository for the package. Shared in this context means shared between your
branches, rather than shared between users in a public location, the latter
can be done later. To set up a repository then you should run (for a package
named scruff)

::

  $ bzr init-repo ~/packages/scruff/
  $ cd ~/packages/scruff/

and then do all of your work in that directory.

Creating a New Package
^^^^^^^^^^^^^^^^^^^^^^ 
To create a new package using split mode you need to create a branch to hold
all of the work. If it is a completely new project and there is no code yet
then you can run

::

  $ bzr init scruff/
  $ cd scruff/

if you already have some code, then you can rename the directory containing
that code to ``~/packages/scruff/scruff`` and then run

::

  $ cd scruff/
  $ bzr init
  $ bzr add

which will create a branch and add all of your current code to it.

The next step is to tell `bzr-builddeb` that it is a split mode package. To
do this create the configuration file ``debian/bzr-builddeb.conf`` in the
branch. This contains the options that are default for building the package.
The file starts with a ``[BUILDDEB]`` header to identify the options that
the plugin should use, and the option that you need to set is ``split``.
The following commands will set up the configuration files for you::

  $ echo -e '[BUILDDEB]\nsplit = True' > debian/bzr-builddeb.conf
  $ bzr add debian/bzr-builddeb.conf

When you are happy with the code you can commit, and then build the package.
`bzr-builddeb` will see that it is a split mode package and create the
upstream tarball out of the branch after removing the ``debian/``
directory. The ``debian/`` directory will then form the ``.diff.gz``.

Importing History
^^^^^^^^^^^^^^^^^

It is not currently possible to import history from source packages in split
mode. Hopefully this will be possible at some point in the future.

New upstream version
####################

Creating a new upstream version of the package is easy in split mode. It is
merely a case of updating the ``debian/changelog``. The ``dch`` tool from
``devscripts`` can help you here. To create the ``0.2-1`` version of the
package you can run

::

  $ dch -v 0.2-1

and enter a message about the new version. Then when you next build the
package it will have the correct version number.

.. vim: set ft=rst tw=76 :

