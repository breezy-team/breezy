bzr-keywords: RCS-like keyword expansion
========================================

Overview
--------

This plugin adds keyword expansion to selected files. This allows
you to do things like include the date a file was last changed.
This functionality is provided as a working-tree content filter.
As a consequence:

 * It needs to be explicitly enabled for certain files.

 * Bazaar will internally store the unexpanded content.

 * Expanded content will only appear in working trees and
   when content is displayed (bzr cat) or exported (bzr export).

See ``bzr help filters`` and the Documentation section below for
more details.


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

    bzr selftest keywords
 

Documentation
-------------

Keyword markers use the pattern $Keyword$ inside files. The
supported keywords are:

 * Date - the date and time in UTC this file was last changed
 * Author - the Author or Committer (Author takes precedence if set)
   making the last change.

The pattern looks like ``$Keyword: value $`` when expanded. For example,
``$Author: jsmith@example.com $``.


Licensing
---------

Otherwise this plugin is (C) Copyright Canonical Limited 2008 under the
GPL Version 2 or later. Please see the file COPYING.txt for the licence
details.
