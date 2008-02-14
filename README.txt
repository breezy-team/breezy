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

The general usage is::

  frontend | bzr fast-import [options]

See the doc/ directory for details.


Licensing
---------

This plugin is (C) Copyright Canonical Limited 2008 under the GPL Version 2.
Please see the file COPYING.txt for the licence details.
