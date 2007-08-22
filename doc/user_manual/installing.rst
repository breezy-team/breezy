Installing
----------

Installing the plugin is simple once you have Bazaar itself installed.

If you are using `Debian`_ or `Ubuntu`_ then you can install the package. It
will be reasonably up to date, and will work well with the packaged version 
of Bazaar (package name `bzr`) if you are using that as well. Like all
packages it can be installed by any of the package managers, for instance::

  # aptitude install bzr-builddeb

If you want to run the latest version of the code then you can use Bazaar
to get the development branch of the code.

::

  $ mkdir -p ~/.bazaar/plugins/
  $ bzr branch http://bzr.debian.org/pkg-bazaar/bzr-builddeb/trunk/ \
           ~/.bazaar/plugins/builddeb/

Then whenever you want to update the code you can run

::

  $ cd ~/.bazaar/plugins/builddeb/
  $ bzr pull

to get the latest version. Installing by this method means that you may be
missing some of the dependencies. The main one is `python-debian`_.
Installing the package for this dependency will probably get you a working
install, but API changes may mean that you need to install a development
version of this library.

To check your install you should be able to run

::

  $ bzr plugins

and see `bzr-builddeb` included in the output::

	bzr-builddeb - manage packages in a Bazaar branch.

The plugin also comes with a testsuite, and running

::

  $ bzr selftest builddeb

should run all the test and report any problems.

.. _Debian: http://www.debian.org/
.. _Ubuntu: http://www.ubuntu.com/
.. _python-debian: http://packages.debian.org/python-debian
.. _python-deb822: http://packages.debian.org/python-deb822

