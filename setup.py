#!/usr/bin/env python
from distutils.core import setup

bzr_plugin_name = 'grep'

bzr_plugin_version = (0, 3, 0, 'dev', 0)

bzr_commands = ['grep']

if __name__ == 'main':
    setup(name="bzr grep",
          version="0.3",
          description="Print lines matching pattern for specified "
                      "files and revisions",
          author="Canonical Ltd",
          author_email="bazaar@lists.canonical.com",
          license = "GNU GPL v2",
          url="https://launchpad.net/bzr-grep",
          packages=['grep'],
          package_dir={'grep': '.'})
