Selecting the mode
------------------

When setting up a package to use `bzr-builddeb` there are several ways of
organising the branch which depend on the type of the package, and the way
in which you want to work. The choices are laid out below, but to decide which
is applicable you might want to answer the following questions.

1. Is the package a native package?

  * Yes? You should use `Native mode`_.
  * No? Go to question 2.

2. Are you also the upstream maintainer?

  * Yes? Go to question 4.
  * No? Go to question 3.

3. Do you want to store only the ``debian/`` directory?

  * Yes? You should use `Merge mode`_.
  * No? You should use `Normal mode`_.

4. Would you like to maintain a separate branch for your packaging work?

  * Yes? Go to question 3.
  * No? You should use `Split mode`_.

.. _Normal mode: normal.html
.. _Merge mode: merge.html
.. _Native mode: native.html
.. _Split mode: split.html

