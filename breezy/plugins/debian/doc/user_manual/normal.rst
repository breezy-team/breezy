Normal mode
-----------

This mode is known as normal mode, as it is the default. It has the whole
source in the branch (all upstream code and the ``debian/`` directory). It also
requires the upstream tarball to be available to use in the source package.
This is the mode that works most like packaging without Bazaar. When you issue
the command to build the package the plugin exports the source to the build
directory, and places the upstream tarball there as well. It then calls the
build command in the exported source directory. Most build commands (like
``debuild``) know how to work in this situation, and create a source
package using the upstream tarball and generating the diff against it.

This arrangement means that any changes you make to the source in the branch
will appear in the generated ``.diff.gz``. If you prefer to use a patch system
you can, and the tools will work as normal as you have the full source.

Setting up the package
######################

To set up a package to use this mode is quite easy. I will explain how to do
it for the default options. First you need to create the branch. As you
may well be creating multiple branches of the package in future it is a good
idea to create a shared repository to hold the branches of the project. I will
assume that you want to keep all of your packages in a directory called
``~/packages/`` and you are creating a package named ``scruff``.

::

  $ bzr init-repo ~/packages/scruff/
  $ cd ~/packages/scruff/

If you are working on a package that already has several versions then you
can import these old versions to create the history for your new branch.
This allows you to use Bazaar to explore the history of the package. The
steps required to do this are outlined in the `Importing History`_ section
below.

If you have a package stored in another version control system then you can
probably convert this to a Bazaar branch, and then use `bzr-builddeb` to
manage the package. However this may take a little work beyond converting
the formats.

If you have started packaging, but do have not completed the first version
of the package yet, for instance you have used ``dh_make``, but have not
completed the packaging, the best approach to convert this to a bzr branch is
to build a source package (with ``debuild -S``, and then import
this with ``import-dsc`` as described in `Importing History`_.

If however you are starting a completely new package you can follow the steps
in the `Creating a New Package`_ section. If you are going to use ``dh_make``
to create the package then you might find it easier to do this without the
tool, and then create a source package and import that, as described in the
previous paragraph.

Creating a New Package
^^^^^^^^^^^^^^^^^^^^^^

.. TODO: perhaps add a command to do all of these steps.

You need to create a new branch in which to do your work. To create a new
branch you use the ``bzr init`` command.

  $ bzr init scruff

(replacing scruff with the name of your package. This name is the name of
the branch that is created, and as such you can pick any name that you like).

Now you need to populate this branch with the files from the upstream tarball.
`bzr-builddeb` provides a command to help you with this, it is the
``merge-upstream`` command. To use it you need to download the upstream
tarball in to the current directory. Then you enter the current directory
and run the command, passing it the name of the upstream tarball, and the
version number that it corresponds to. It is required as it is difficult
to guess this number, and so it is better for the user to provide it.
In our example the upstream tarball is named ``scruff-0.1.tar.gz`` and
the version number is ``0.1``. As there is not code in the branch yet the
plugin does not know what package you are creating. So you must also supply
the package name using the ``--package`` option. This means that once you
have downloaded the tarball you should run::

  $ cd scruff/
  $ bzr merge-upstream ../scruff-0.1.tar.gz --version 0.1 \
      --distribution debian --package scruff

If it is instead intended for Ubuntu then substitute "debian" with
"ubuntu".

This command will work for upstream tarballs that are ``.tar.gz``, ``.tgz``,
``.tar`` or ``.tar.bz2``, or unpacked directories if you have one of those
instead.

This creates a commit in the branch that contains the upstream code, if you
run ``bzr log`` you will be able to see this. ``bzr tags`` will show you that
a tag was created for this commit, so that it is possible to find it again
easily, which will become important later.

The upstream tarball is also converted to the required form, this means that
it is repacked to ``.tar.gz`` format if it is in a different format, and then
renamed to the correct name for the ``.orig.tar.gz`` part of a source package.
Finally it is placed in the parent directory, where later commands
will expect to find it. If you do not like this location for the upstream
tarballs you are free to change it, the `Configuration Files`_ section
explains how.

.. _Configuration Files: configuration.html

Now you need to start the packaging work. To do this create ``debian/`` and
the files that you need in it. ``dh_make`` can help you with this. However
it will probably not work straight away as the directory name is not how it
expects, and the upstream tarball is not in the right place for it. You can
create a new place to work in, run ``dh_make`` and then copy across the
``debian/`` directory when you finish.

.. FIXME: the instructions could be changed to make this step easier, or more
   clear.

Once you have you ``debian/`` directory then you need to add the files to
your branch. This should be easy to do by just running::

  $ bzr add

(Note that this will also add any ``.ex`` files left by ``dh_make`` if you
don't remove them).

Once you are happy with the packaging then you can run ``bzr commit`` to
commit your work.

Importing History
^^^^^^^^^^^^^^^^^

If you have several versions of a package available then you can import the
history to create your branch to work in. This is easy to do, you just
need a collection of source packages to import. You use the ``import-dsc``
command to do the import. It takes a list of ``.dsc`` files to import as the
argument. So if you have all of the history in one directory then you can
run

::

  $ bzr init scruff
  $ cd scruff
  $ bzr import-dsc ../*.dsc

which will create a branch named ``scruff``, which will have the history
populated with the information in the source packages. You can see this
with ``bzr log`` in the branch, or ``bzr viz`` if you have `bzr-gtk`_
installed. It assumes that all packages were uploaded to Debian. If
they were uploaded to Ubuntu instead then substitute "debian" with
"ubuntu". If they were mixed then you have to perform some manual
steps to get the correct history.

.. _bzr-gtk: https://launchpad.net/bzr-gtk/

It is also possible to retrieve the .dsc files over ``HTTP``, ``FTP`` or
``SFTP`` automatically. Just give the URIs to the files on the command line
instead of local paths. For instance::

  $ bzr import-dsc http://ftp.debian.org/pool/main/s/scruff/scruff_0.1-1.dsc

As it is unwieldy to provide lots of URIs on the command line it is also
possible to supply them in a text file. To do this create a text file where
every non-blank line is the URI of a ``.dsc`` file, or the path to one on the
local filesystem. The ordering does not matter, they will be reordered as
needed to ensure the history is correct. For instance if the file
``package-sources`` contains the list for ``scruff`` then the command

::

  $ bzr import-dsc -F package-sources

will import all of the ``.dsc`` files listed. You can provide both a file
and a list of packages on the command line if you like.

The process places all of the ``.orig.tar.gz`` files from the source packages
in the parent directory, as they are required if that version of the package is
going to be built. If you do not like to use the disk space for these files
then they can be deleted, provided they can be retrived from elsewhere. If
you do not like the location of those files then you can configure a
different location. See the `Configuration Files`_ section for instructions.

.. TODO: test what happens when you try to repack to the same file.

.. TODO: perhaps make it so that if you import a bunch of local files,
   and you want a central dir for all tarballs then you can save on
   copying/duplicates.

This import functionality is very convenient, but due to the nature of Bazaar
it is not a good idea to do this more than once. If there are two contributors
to a package, and they both do the import independently then they will find
it difficult to merge between themselves, as the two branches are not related
in Bazaar's eyes. What should be done is for one of the contributors to
perform the import and then make the resulting branch available for the other
to work from.

New upstream version
####################

When a new upstream version is released then the package needs to be updated
to use the new code. To do this, first the new upstream version is
imported on top of the last one, as it is a direct descendant of it. Then your
current packaging changes are merged in to the new version, which may cause
conflicts that need to be resolved.

This process is automated using the ``merge-upstream`` command. This
takes as an argument the version number of the new upstream version, and the
tarball that represents this release. This tarball can be local or remote.

For instance when the ``0.2`` version of ``scruff`` is released the command
to update to the new version is::

  $ bzr merge-upstream --version 0.2 \
        http://scruff.org/releases/scruff-0.2.tar.gz

This command downloads the new version, and imports it in to the branch. It
then merges in the packaging changes to the new version.

If there are any conflicts caused by the merge of the packaging changes you
will be notified. You must resolve the conflicts in the normal way.

Once you have resolved any conflicts, edited any other files as you require,
and reviewed the diff, you can commit the changes, and then attempt to
build the new version.

::

  $ bzr commit -m 'New upstream version'
  $ bzr builddeb

If upstream is stored in bzr, or in a VCS that there is bzr foreign branch
support for then you can also merge the branch at the same time. Specify the
branch as an extra argument to the ``merge-upstream`` command, and use the
``--revision`` argument to specify the revision that the release corresponds
to.

::

  $ bzr merge-upstream --version 0.2 \
        http://scruff.org/releases/scruff-0.2.tar.gz \
        http://scruff.org/bzr/scruff.dev -r tag:scruff-0.2

If upstream doesn't release tarballs, or you would like to package a
snapshot then you can just specify a branch, instead of a tarball,
and ``bzr-builddeb`` will create the tarball for you.

::

  $ bzr merge-upstream --version 0.2 http://scruff.org/bzr/scruff.dev

Merging a package
#################

When merging a package you should use the ``merge-package`` command,
which knows about packages in a way that ``merge`` does not. This
knowledge allows it to reconcile deviations in the upstream
ancestry so that they don't cause excess conflicts. (Note that the
command works whether or not there are deviations in the upstream
ancestry.)

The command works in the same way as ``merge``. For example::

    $ cd scruff-unstable/
    $ bzr merge-package ../scruff-experimental

will leave the branch in the same state as a normal merge allowing
you to review the changes and commit.

In a small number of cases, however, the source `upstream` and target
`packaging` branches will have conflicts that cause the following error
instead::

    $ bzr merge-package ../scruff-highly-experimental
    The upstream branches for the merge source and target have diverged.
    Unfortunately, the attempt to fix this problem resulted in conflicts.
    Please resolve these, commit and re-run the "merge-package" command to
    finish.
    Alternatively, until you commit you can use "bzr revert" to restore the
    state of the unmerged branch.

This will leave you in a conflicted tree, and you can deal with the conflicts
and use ``resolve`` as normal. Once you have resolved all the conflicts you
need to commit and then run the same ``merge-package`` command again to
complete the operation. As with normal merges until you commit you can
use ``revert`` to return you to the state before you started.

Importing a source package from elsewhere
#########################################

During the life of a package it is possible that an upload will be done
where the changes are not included in the branch, perhaps if an NMU is done.
This also applies to Ubuntu when merging packages with new Debian uploads.

The plugin allows you to import a source package, and will merge the changes
within allowing you to incorporate them as you like. It will also try and
pull in the upstream changes as it would when doing an initial import,
allowing you to use Bazaar to inspect differences with the upstream.

To import the source package you again use the ``import-dsc`` command.
Either run it from the base of your branch, or use the ``--to`` option to
specify the base of the branch. Also on the command line specify the
location of the ``.dsc`` file you would like to import. As well as using a
local path this can be any URI that Bazaar supports, for instance a
``http://`` URL. For instance::

  $ bzr import-dsc ../scruff_0.2-1.1.dsc

The command will import the changes and then leave you with a tree that is
the result of merging the changes in the source package in to the tip of
your branch before you started. You can then see the changes that were made
by running ``bzr status`` and ``bzr diff``. There may also be conflicts
from the merge (usually ``debian/changelog`` will conflict). You should
edit the files to resolve the conflicts as normal. Once you have finished
you should commit, and then you can carry on with your work.

.. vim: set ft=rst tw=76 :

