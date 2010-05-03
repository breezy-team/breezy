Upstream tarballs
-----------------

When you are building a version of a package that uses a version of the
upstream package that you have not used in a build yet, the upstream
tarball for that version needs to be fetched from somewhere. It can be
tedious to track the correct file down, download it and rename or repack it
to have the correct name and be in the correct format.

To ease this step the plugin will try different methods to find the tarball
if it is not already in the required place.

If it can it will reconstruct the tarball from ``pristine-tar`` information
stored in the branch. ``bzr-builddeb`` will store this information whenever
it can, so using its commands such as ``merge-upstream`` and ``import-dsc``
will lead to the best experience. If you have an existing branch missing
this information, you can use the ``import-upstream`` command to import a
single tarball, after which the ``merge-upstream`` command should be used.

If there is no ``pristine-tar`` information then it will use apt to download
the tarball from the archive if there is one of the correct version there.

If that does not find the required package the plugin will use ``uscan``
from the ``devscripts`` package to obtain the file for you if it needs it
and your branch has a ``debian/watch`` file. The correct file will be
downloaded if ``uscan`` can find it, and it will be renamed or repacked
as necessary so that it can be used straight away for the build.

I also hope to extend this functionality to retrieve the tarball using apt
if it is in the archive, and from a central location for those who work on
packaging teams.

.. : vim: set ft=rst tw=76 :

