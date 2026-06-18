Working with Packages in Bazaar using bzr-builddeb
==================================================

Introduction
------------

Storing a package in a version control system can give many benefits,
particularly the record of changes, and the ability to work with multiple
branches and pull changes between them.

`Bazaar`_ is a modern distributed version control system that can be used
for this task. Bazaar aims to be easy to use, and provides all of the features
that you would expect of a version control system. However to ease working
with packages that are stored in version control other features need to be
provided. Bazaar has a plugin system that allows the set of commands to be
supplemented with others, and so a plugin exists to provide extra commands
useful for working with packages. This plugin is named `bzr-builddeb`.

This document aims to explain the features provided by the plugin, explain
some of the choices that are available when deciding how you want to work,
and provide examples of putting a package under version control and working
with it. It is not a tutorial on Bazaar itself, and it is assumed that you
know how to work with Bazaar already. If you do not then there are
`tutorials`_ available.

.. _Bazaar: http://www.bazaar-vcs.org/
.. _tutorials: http://doc.bazaar-vcs.org/bzr.dev/

If you do not yet have the plugin installed then you can see the `Installation`_
section for details on how to do this.

.. _Installation: installing.html

The plugin operates in several different `modes` depending on the type of
package and how you want to work. Each mode has its own documentation for
many tasks, so you should read the documentation for your mode. If you do
not know which mode you would like to use then you can either read about
each mode in its page, or use the `Mode Selector`_.

.. _Mode Selector: mode_selector.html

The modes are

  * `Normal mode`_
  * `Native mode`_
  * `Merge mode`_
  * `Split mode`_

.. _Normal mode: normal.html
.. _Merge mode: merge.html
.. _Native mode: native.html
.. _Split mode: split.html

The remainder of the documentation explains general features of the package.
These sections are

  * `Configuration Files`_
  * `Building a package`_
  * `Upstream tarballs`_
  * `Using hooks`_

.. _Configuration Files: configuration.html
.. _Building a package: building.html 
.. _Upstream tarballs: upstream_tarballs.html
.. _Using hooks: hooks.html

Appendices

  * `License`_

.. _License: license.html

.. vim: set ft=rst tw=76 :

