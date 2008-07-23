#!/usr/bin/env python2.4
from distutils.core import setup

bzr_plugin_name = 'fastimport'

bzr_plugin_version = (0, 7, 0, 'dev', 0)
bzr_minimum_version = (1, 1, 0)
bzr_maximum_version = None

if __name__ == 'main':
    setup(name="fastimport",
          version="0.7.0dev0",
          description="stream-based import into and export from Bazaar.",
          author="Canonical Ltd",
          author_email="bazaar@lists.canonical.com",
          license = "GNU GPL v2",
          url="https://launchpad.net/bzr-fastimport",
          packages=['bzrlib.plugins.fastimport',
                    'bzrlib.plugins.fastimport.processors',
                    'bzrlib.plugins.fastimport.tests',
                    ],
          package_dir={'bzrlib.plugins.fastimport': '.'})
