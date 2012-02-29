bzr-fastimport: Backend for fast Bazaar data importers
======================================================

Dependencies
------------

Required and recommended packages are:

* Python 2.4 or later

* Python-Fastimport 0.9.0 or later.

* Bazaar 1.18 or later.


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

To view the documentation after installation:

    bzr help fastimport
 
Exporters/Importers
-------------------

There are also fast importers / fast exporters available for other version
control tools.

 * Git: fastimport support is built-in ("git fast-import" / "git fast-export")
 * Mercurial: http://mercurial.selenic.com/wiki/FastImportExtension
 * Subversion: http://repo.or.cz/w/fast-export.git
 * CVS: http://cvs2svn.tigris.org/cvs2bzr.html
 * Perforce: https://github.com/git/git/blob/master/contrib/fast-import/git-p4

Licensing
---------

For copyright and licensing details of the exporters, see the relevant
files in the exporters/ directory.

Otherwise this plugin is (C) Copyright Canonical Limited 2008 under the
GPL Version 2 or later. Please see the file COPYING.txt for the licence
details.
