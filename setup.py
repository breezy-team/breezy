#!/usr/bin/env python2.4
from distutils.core import setup

bzr_plugin_name = 'guess'

bzr_plugin_version = (0, 0, 1, 'dev', 0)
bzr_minimum_version = (0, 17, 0)

if __name__ == 'main':
    setup(name="bzr-guess plugin",
          version="0.0.1dev0",
          description="when a bzr command is misspelt, offer the closest match instead.",
          author="Canonical Ltd",
          author_email="bazaar@lists.canonical.com",
          license = "GNU GPL v2",
          url="https://launchpad.net/bzr-guess",
          packages=['bzrlib.plugins.guess',
                    ],
          package_dir={'bzrlib.plugins.guess': '.'})
