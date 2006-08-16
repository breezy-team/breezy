#!/usr/bin/env python2.4

from distutils.core import setup

setup(name="bzr-builddeb",
      version="0.1.0",
      description="Build a .deb from a bzr branch",
      author="James Westby",
      author_email="jw+debian@jameswestby.net",
      license = "GNU GPL v2",
      url="http://jameswestby.net/bzr/bzr-builddeb/",
      packages=['bzrlib.plugins.bzr-builddeb'],
      package_dir={'bzrlib.plugins.bzr-builddeb': '.'})

