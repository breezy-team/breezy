Native mode
-----------

Native mode is, unsurprisingly, the mode used for maintaining a native
package. The main difference to normal mode is that an upstream tarball is
not needed. The consequence of this is that most operations, such as
importing a new upstream are not needed.

Setting up the package
######################

Setting up the package is rather easy. If you already have some versions of
the package then you can import the history, see the `Importing History`_
section below. If you are starting a new package, and you like to use
``dh_make``, then the easiest way is to do that as normal, then build a
source package using ``dpkg-buildpackage -S``, and then import that as
outlined in `Importing History`_.

If you wish to create a new package without using a tool like ``dh_make``
then you should see the next section.

If you have an existing package using another version control system then
you may prefer to retain the full history by converting it to a Bazaar
branch. Once you have done this then you should be able to build it using
`bzr-builddeb`, but you need to tell it that it is a native package. The
best way to do this is to use the configuration file, see the next section
for details.

Whatever method you wish to use it will probably be beneficial to set up a
shared repository for the package. Shared in this context means shared
between your branches, rather than shared between users in a public
location, the latter can be done later. To set up a repository then you
should run (for a package named scruff)

::

  $ bzr init-repo ~/packages/scruff/
  $ cd ~/packages/scruff/

and then do all of your work in that directory.

Creating a New Package
^^^^^^^^^^^^^^^^^^^^^^

Creating a new native package is little more than creating a new Bazaar
branch and setting up the configuration file. To set up a branch then use
the command

::

  $ bzr init --dirstate-trees scruff/
  $ cd scruff/

The ``--dirstate-tags`` option here ensures that the branch supports tags,
as the current default branch format in Bazaar does not.

Now you have a branch that you will create the package in you need to tell
`bzr-builddeb` that it will be a native package. To do this you need to
create the configuration file ``.bzr-builddeb/default.conf``. This contains
the default options for the package. The file starts with a ``[BUILDDEB]``
header which states that the file is for use by `bzr-builddeb`. The option
we are interested in is the ``native`` option. The commands to do this are::

  $ mkdir .bzr-builddeb/
  $ echo -e '[BUILDDEB]\nnative = True' > .bzr-builddeb/default.conf
  $ bzr add .bzr-builddeb/default.conf

Now you are ready to create the package. Add all of the files for the
package, and the packaging in ``debian/``, and then you can add the files
and commit and you are ready to build.

Importing History
^^^^^^^^^^^^^^^^^

If you have several versions of a package available then you can import the
history to create your branch to work in. This is easy to do, you just
need a collection of source packages to import. You use the ``import-dsc``
command to do the import. It takes a list of ``.dsc`` files to import as the
argument. So if you have all of the history in one directory then you can
run

::

  $ bzr import-dsc --to scruff *.dsc

which will create a branch named ``scruff``, which will have the history
populated with the information in the source packages. You can see this
with ``bzr log`` in the branch, or ``bzr viz`` if you have `bzr-gtk`_
installed.

.. _bzr-gtk: https://launchpad.net/bzr-gtk/

It is also possible to retrieve the .dsc files over ``HTTP``, ``FTP`` or
``SFTP`` automatically. Just give the URIs to the files on the command line
instead of local paths. For instance::

  $ bzr import-dsc --to scruff \
    http://ftp.debian.org/pool/main/s/scruff/scruff_0.1-1.dsc

As it is unwieldy to provide lots of URIs on the command line it is also
possible to supply them in a text file. To do this create a text file where
every non-blank line is the URI of a ``.dsc`` file, or the path to one on the
local filesystem. The ordering does not matter, they will be reordered as
needed to ensure the history is correct. For instance if the file
``package-sources`` contains the list for ``scruff`` then the command

::

  $ bzr import-dsc --to scruff -F package-sources

will import all of the ``.dsc`` files listed. You can provide both a file
and a list of packages on the command line if you like.

`snapshot.debian.net`_ stores every version of a package that gets uploaded to
Debian. This means that the history of a package is available, even if you
don't have all of the source packages yourself. If you want to use this
history it is easy to do so. If you pass the ``--snapshot`` option to the
``import-dsc`` command then the list of source packages you supply
will be supplemented with all those found on ``snapshot.debian.net``. The
option takes the name of the source package as it is known to
``snapshot.debian.net``. For instance if there are several versions of
``scruff`` available on this service then I can run

::

  $ bzr import-dsc --to scruff --snapshot scruff *.dsc

to have all those versions automatically imported. If you use the
``--snapshot`` option then it is possible to omit all of the source packages
from the command line, so that the history is made up of only those packages
available on ``snapshot.debian.net``.

.. _snapshot.debian.net: http://snapshot.debian.net/

All of the above takes care to create the configuration file that tells
`bzr-builddeb` that you are building a native package, so you should not
need to take any extra steps before building the package.

This import functionality is very convenient, but due to the nature of Bazaar
it is not a good idea to do this more than once. If there are two contributors
to a package, and they both do the import independently then they will find
it difficult to merge between themselves, as the two branches are not related
in Bazaar's eyes. What should be done is for one of the contributors to
perform the import and then make the resulting branch available for the other
to work from.

New upstream version
####################

As there is no upstream for a native package then this step is redundant.
All you need to do is update the version in ``debian/changelog``. The
``dch`` command can help here, for instance

  $ dch -i

will add a new changelog stanza, incrementing the version number, and
allowing you to add a message for the new version.

There is a command provided by `bzr-builddeb` for importing a new upstream
version. As there is no need to do this for a native package the command
will refuse to run against a package that is marked as being native.

.. vim: set ft=rst tw=76 :

