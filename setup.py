#!/usr/bin/env python
from distutils.core import setup

bzr_plugin_name = 'groupcompress'

bzr_plugin_version = (1, 6, 0, 'dev', 0)


if __name__ == '__main__':
    setup(name="bzr groupcompress",
          version="1.6.0dev0",
          description="bzr group compression.",
          author="Robert Collins",
          author_email="bazaar@lists.canonical.com",
          license = "GNU GPL v2",
          url="https://launchpad.net/bzr-groupcompress",
          packages=['bzrlib.plugins.groupcompress',
                    'bzrlib.plugins.groupcompress.tests',
                    ],
          package_dir={'bzrlib.plugins.groupcompress': '.'},
          }
