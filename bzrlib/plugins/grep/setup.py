#!/usr/bin/env python
from distutils.core import setup
import version

bzr_plugin_name = 'grep'

bzr_plugin_version = version.version_info

bzr_commands = ['grep']

if __name__ == '__main__':
    setup(name="bzr-grep",
          version=version.version_str,
          description="Print lines matching pattern for specified "
                      "files and revisions",
          author="Canonical Ltd",
          author_email="bazaar@lists.canonical.com",
          license = "GNU GPL v2",
          url="https://launchpad.net/bzr-grep",
          packages=['bzrlib.plugins.grep'],
          package_dir={'bzrlib.plugins.grep': '.'})
