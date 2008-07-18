bzr-keywords: RCS-like keyword templates
========================================

Overview
--------

This plugin adds keyword filtering to selected files. This allows
you to do things like include the current user and date in a web page.


Installation
------------

The easiest way to install this plugin is to either copy or symlink the
directory into your ~/.bazaar/plugins directory. Be sure to rename the
directory to keywords (instead of bzr-keywords).

See http://bazaar-vcs.org/UsingPlugins for other options such as
using the BZR_PLUGIN_PATH environment variable.


Testing
-------

To test the plugin after installation:

    bzr selftest keywords.tests
 

Documentation
-------------

To see the documentation after installation:

    bzr help keywords


Licensing
---------

This plugin is (C) Copyright Canonical Limited 2008 under the
GPL Version 2 or later. Please see the file COPYING.txt for the licence
details.
