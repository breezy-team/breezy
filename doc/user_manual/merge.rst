Merge mode
----------

Merge mode is where only the packaging changes are versioned, that is the
branch contains only the ``debian/`` directory. Some people prefer this
mode, as it clearly separates the packaging changes from the upstream code.

It does however have a few drawbacks, the first being that some tools do not
understand this mode, and so may not work without some work on your part.
The second is that patches to the upstream source can be a little unwieldy
to handle, especially when updating to a new upstream version. I hope to add
some support for doing this in a later version. The last is that importing
history is difficult, if not impossible if the old versions of the package
touched anything outside of the ``debian/`` directory. Currently importing
history is not supported, even for packages that confine their changes to
the packaging directory.

Setting up the package
######################

As stated above importing existing packages is not supported yet, and so if
you choose this mode you will either have to do this yourself, or abandon
the history. I will only describe here how to create a new package.

Creating a New Package
^^^^^^^^^^^^^^^^^^^^^^

First you may find it beneficial to set up a shared repository for the
package. Shared in this context means shared between your branches, rather
than shared between users in a public location, the latter can be done
later. To set up a repository then you should run (for a package named
scruff)

::

  $ bzr init-repo ~/packages/scruff/
  $ cd ~/packages/scruff/

and then do all of your work in that directory.

Now you need to create a branch in which to create the package, to do that
then you should run

::

  $ bzr init --dirstate-trees scruff/
  $ cd scruff/

The ``--dirstate-tags`` option here ensures that the branch supports tags,
as the current default branch format in Bazaar does not.

Now you have a branch that you will create the package in you need to tell
`bzr-builddeb` that it will be built in merge mode. To do this you need to
create the configuration file ``.bzr-builddeb/default.conf``. This contains
the default options for the package. The file starts with a ``[BUILDDEB]``
header which states that the file is for use by `bzr-builddeb`. The option
we are interested in is the ``merge`` option. The commands to do this are::

  $ mkdir .bzr-builddeb/
  $ echo -e '[BUILDDEB]\nmerge = True' > .bzr-builddeb/default.conf
  $ bzr add .bzr-builddeb/default.conf

Now you should add the packaging files to the branch. You have a choice
here, either you can add a ``debian/`` directory containing the files,
or you can place them directly in the root of the branch, `bzr-builddeb`
supports both layouts. The latter layout is preferred by some as it
removes the extra directory at the root. However doing this makes some tools
more difficult to work with, as they expect to find ``debian/changelog`` or
similar, where you only have ``changelog``. This can normally be worked
around, or you can add a symlink like::

  $ ln -s . debian
  $ bzr ignore debian

that will allow some tools to work.

Once you have made the decision then add the packaging files to the branch,
run ``bzr add`` to tell Bazaar to version the files, and then make the first
commit.

Merge mode requires the upstream tarballs to be available when building. By
default it searches for them in ``../tarballs/``. If you would like to use a
different location then see the `Configuration Files`_ section. First you
should create this directory::

  $ mkdir ../tarballs/

and then add the upstream tarballs to it. The plugin expects them to be
named as they would be in a source package, that is the tarball for version
``0.1`` of ``scruff`` would be::

  scruff_0.1.orig.tar.gz

In the future you will be able to use the ``merge-upstream`` command to do
this for you, but it has not been made to support merge mode yet.

.. _Configuration Files: configuration.html

One the tarballs are in place then you are ready to build the package. See
the `Building the package`_ section for more details on this.

.. _Building the package: building.html

New upstream version
####################

There are three steps to updating a merge mode package to a new upstream
version. The first is to download the new upstream tarball, and place it in
``../tarballs/``, named as the plugin expects to find it (see above). The
``merge-upstream`` command will automate this part of the process in the
future, but for now it must be done manually.

The next step is to update the changelog for the new version. This can be
done using the ``dch`` command, for instance to update to version ``0.2-1``
of the package you would run::

  $ dch -v 0.2-1

Note that if you put all of the packaging files in the root of the branch
you will need to add the ``-c changelog`` option.

The last step is to update the packaging. The first part of this is changing
any files to reflect changes in the upstream build, for instance updating
``debian/rules``, or ``debian/install``. The last part is updating any
patches that have against the upstream code to work against the latest
version. This is currently quite troublesome, as you need an unpacked source
to apply them against. The easiest way to do this is to use the ``--export``
option of ``builddeb`` to get the unpacked source::

  $ bzr builddeb --export

(the ``-w`` option might also be useful here, see the `Building the
package`_ section for more details on this option).

Then you can ``cd`` to the exported directory, refresh the patches, and copy
them back in to the branch.

This is a tedious operation, and one that I hope to make easier with support
in the plugin in a later version.

.. vim: set ft=rst tw=76 :

