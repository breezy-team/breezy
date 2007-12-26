#!/usr/bin/env python
from distutils.core import setup
setup(name="bisect",
      version="unreleased",
      description="Git-style bisect plugin for bzr.",
      author="Jeff Licquia",
      author_email="jeff@licquia.org",
      license="GNU GPL v2",
      url="http://bzr.licquia.org/",
      packages=["bzrlib.plugins.bisect"],
      package_dir={"bzrlib.plugins.bisect": "."})
