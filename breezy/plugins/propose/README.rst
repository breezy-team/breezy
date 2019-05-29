brz-propose
===========

``brz-propose`` is a plugin for `Breezy <https://www.breezy-vcs.org/>`_ that
provides support for interacting with code hosting sites.

It provides the following extra commands for Breezy:

* ``brz publish``: publish a derived branch
* ``brz propose``: publish and propose a branch for merging
* ``brz find-merge-proposal``: locate branch proposals

Supported codehosting sites
---------------------------

brz-propose currently supports the following two centralized codehosting sites:

* `GitHub <https://www.github.com/>`_
* `Launchpad <https://launchpad.net/>`_

It also supports `GitLab <https://www.gitlab.com>`_ instances such as
`GitLab.com <https://www.gitlab.com/>`_ or
`Debian Salsa <https://salsa.debian.org>`_.

Support for `BitBucket <https://bitbucket.org/>`_ and Gerrit is planned.

Usage
-----

GitHub
~~~~~~

First, log into GitHub::

    $ brz github-login mylogin

Then, you can clone a repository::

    $ brz branch git://github.com/breezy-team/breezy
    $ cd breezy

Make a test change::

    $ touch test
    $ brz add test
    $ brz commit -m "Add test file"

And then propose the change for merging::

    $ brz propose --name my-branch-name

This last command will:

 * create a fork of the *breezy-team/breezy* named *mylogin/breezy* at
   https://github.com/mylogin/breezy (if it did not exist)
 * push the local branch with the test change to a remote branch named
   ``my-branch-name`` in the new remote repository
 * create a pull request on GitHub proposing the merge of ``my-branch-name``
   into the main branch

Launchpad
~~~~~~~~~

First, log into Launchpad::

    $ brz lp-login mylogin

Then, you can clone a branch::

    $ brz branch lp:brz
    $ cd brz

Make a test change::

    $ touch test
    $ brz add test
    $ brz commit -m "Add test file"

And then propose the change for merging::

    $ brz propose --name my-branch-name

This last command will:

 * push the local branch to a new branch at *lp:~mylogin/brz/my-branch-name*
 * create a merge proposal on Launchpad merging
   *lp:~mylogin/brz/my-branch-name* into *lp:brz*

GitLab
~~~~~~

First, log into your GitLab instance. Here, we'll use Debian's `salsa
<https://salsa.debian.org/>`_. When logged into your account in a web browser,
create a private token. Then run::

    $ brz gitlab-login https://salsa.debian.org private-token

Then, clone a branch::

    $ brz branch https://salsa.debian.org/jelmer/xandikos
    $ cd xandikos

Make a test change::

    $ touch test
    $ brz add test
    $ brz commit -m "Add test file"

And then propose the change for merging::

    $ brz propose --name my-branch-name

This last command will:

 * create a fork of the *jelmer/xandikos* project named *mylogin/xandikos* at
   https://salsa.debian.org/mylogin/xandikos (if it did not exist)
 * push the local branch with the test change to a remote branch named
   ``my-branch-name`` in the new remote repository
 * create a pull request on GitLab proposing the merge of ``my-branch-name``
   into the main branch
