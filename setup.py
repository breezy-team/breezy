#!/usr/bin/env python

from distutils.core import setup
from meta import *
from meta import __version__

if __name__ == "__main__":
    setup(name=bzr_plugin_name,
          version=__version__,
          description="Git-style bisect plugin for bzr.",
          author="Jeff Licquia",
          author_email="jeff@licquia.org",
          license="GNU GPL v2",
          url="http://bzr.licquia.org/",
          packages=["bzrlib.plugins.bisect"],
          package_dir={"bzrlib.plugins.bisect": "."})
