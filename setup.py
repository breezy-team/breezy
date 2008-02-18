#!/usr/bin/env python

from distutils.core import setup

# Queryable plugin variables, from a proposal by Robert Collins.

bzr_plugin_name = 'bisect'
bzr_plugin_version = '1.1pre'

bzr_minimum_version = '0.18'
bzr_maximum_version = None

bzr_commands = [ 'bisect' ]

if __name__ == "__main__":
    setup(name=bzr_plugin_name,
          version=bzr_plugin_version,
          description="Git-style bisect plugin for bzr.",
          author="Jeff Licquia",
          author_email="jeff@licquia.org",
          license="GNU GPL v2",
          url="http://bzr.licquia.org/",
          packages=["bzrlib.plugins.bisect"],
          package_dir={"bzrlib.plugins.bisect": "."})
