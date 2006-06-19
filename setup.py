#! /usr/bin/env python

from distutils.core import setup
from distutils.command.install_scripts import install_scripts
from distutils.command.build import build

setup(name='svn2bzr',
      version='0.8.2',
      author='Gustavo Niemeyer',
      author_email='gustavo@niemeyer.net',
      url='http://www.bazaar-vcs.org/svn2bzr',
      description='Conversion tool for Subversion branches',
      license='GNU GPL v2',
      scripts=['svn2bzr'],
      data_files=[('man/man1', ['svn2bzr.1'])],
     )
