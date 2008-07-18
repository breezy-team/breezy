#!/usr/bin/env python2.4
from distutils.core import setup

bzr_plugin_name = 'keywords'

bzr_plugin_version = (0, 1, 0, 'dev', 0)
bzr_minimum_version = (1, 6, 0)
bzr_maximum_version = None

if __name__ == 'main':
    setup(name="keywords",
          version="0.1.0dev0",
          description="Keyword templating plugin for bzr.",
          author="Canonical Ltd",
          author_email="bazaar@lists.canonical.com",
          license = "GNU GPL v2",
          url="https://launchpad.net/bzr-keywords",
          packages=['bzrlib.plugins.keywords',
                    'bzrlib.plugins.keywords.tests',
                    ],
          package_dir={'bzrlib.plugins.keywords': '.'})
