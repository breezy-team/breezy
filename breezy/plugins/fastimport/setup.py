#!/usr/bin/env python
from distutils.core import setup
from info import *

if __name__ == '__main__':
    version = ".".join([str(x) for x in bzr_plugin_version])
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
                    'bzrlib.plugins.fastimport.processors',
                    'bzrlib.plugins.fastimport.tests',
                    ],
          package_dir={'bzrlib.plugins.fastimport': '.'})
