#!/usr/bin/env python2.4
from distutils.core import setup

bzr_plugin_name = 'commitfromnews'

bzr_plugin_version = (0, 0, 1, 'dev', 0)
bzr_minimum_version = (2, 2, 0)

if __name__ == 'main':
    setup(name="bzr-commitfromnews plugin",
          version="0.0.1dev0",
          description="Generate commit message templates from NEWS.",
          author="Canonical Ltd",
          author_email="bazaar@lists.canonical.com",
          license = "GNU GPL v2",
          url="https://launchpad.net/bzr-commitfromnews",
          packages=['bzrlib.plugins.commitfromnews',
                    'bzrlib.plugins.commitfromnews.tests',
                    ],
          package_dir={'bzrlib.plugins.commitfromnews': '.'})
