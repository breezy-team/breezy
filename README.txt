bzr-fastimport: Backend for fast Bazaar data importers
======================================================

Dependencies
------------

Required and recommended packages are:

* Python 2.4 or later

* Bazaar 1.1 or later.


Installation
------------

The easiest way to install this plugin is to either copy or symlink the
directory into your ~/.bazaar/plugins directory. Be sure to rename the
directory to fastimport (instead of bzr-fastimport).

See http://bazaar-vcs.org/UsingPlugins for other options such as
using the BZR_PLUGIN_PATH environment variable.


Testing
-------

To test the plugin after installation:

    bzr selftest fastimport
 

Documentation
-------------

The normal recipe is::

  bzr init-repo .
  frontend | bzr fast-import -

For further details, see http://bazaar-vcs.org/BzrFastImport and the
online help::

  bzr help fast-import
  bzr help fast-import-info
  bzr help fast-import-filter


Licensing
---------

This plugin is (C) Copyright Canonical Limited 2008 under the GPL Version 2.
Please see the file COPYING.txt for the licence details.
