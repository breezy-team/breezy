#!/usr/bin/env python
"""A plugin to generate summary information about a bzr branch.

This plugin provides the command 'bzr version-info', which can
be used to create a summary of the branch at the current moment.
It is very useful as part of a build routine, to include information
about the current tree.
"""

from distutils.core import setup

doclines = __doc__.split("\n")

setup(name="version_info",
      version="0.1dev",
      description = __doc__.split("\n")[0],
      maintainer="John A Meinel",
      maintainer_email="john@arbash-meinel.com",
      url = "http://bzr.arbash-meinel.com/plugins/version_info",
      license = "GNU GPL v2",
      packages=['bzrlib.plugins.version_info'],
      package_dir={'bzrlib.plugins.version_info': '.'}
      )
