#!/usr/bin/env python
from distutils.core import setup

bzr_plugin_name = 'fastimport'

bzr_plugin_version = (0, 10, 0, 'dev', 0)
bzr_minimum_version = (1, 1, 0)
bzr_maximum_version = None

version = "0.9.0dev0"

if __name__ == '__main__':
    setup(name="bzr-fastimport",
          version=version,
          description="stream-based import into and export from Bazaar.",
          author="Canonical Ltd",
          author_email="bazaar@lists.canonical.com",
          license = "GNU GPL v2",
          download_url="http://launchpad.net/bzr-fastimport/trunk/%s/+download/bzr-fastimport-%s.tar.gz" % (version, version),
          url="https://launchpad.net/bzr-fastimport",
          scripts=[],
          packages=['bzrlib.plugins.fastimport',
                    'bzrlib.plugins.fastimport.exporters',
                    'bzrlib.plugins.fastimport.processors',
                    'bzrlib.plugins.fastimport.tests',
                    ],
          package_dir={'bzrlib.plugins.fastimport': '.'})
