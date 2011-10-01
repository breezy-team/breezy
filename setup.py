#!/usr/bin/env python
# Setup file for bzr-mtn

# Copyright (C) 2011 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from info import *

if __name__ == '__main__':
    from distutils.core import setup
    readme = open("README", "r").read()
    version = bzr_plugin_version[:3]
    version_string = ".".join([str(x) for x in version])
    setup(name='bzr-mtn',
          description='Support for Monotone branches in Bazaar',
          keywords='plugin bzr monotone mtn',
          version=version_string,
          url='http://launchpad.net/bzr-mtn',
          license='GPL',
          author='Jelmer Vernooij',
          author_email='jelmer@samba.org',
          long_description=readme,
          package_dir={'bzrlib.plugins.mtn':'.' },
          packages=['bzrlib.plugins.mtn'],
          classifiers=[
              'Topic :: Software Development :: Version Control',
              'Environment :: Plugins',
              'License :: OSI Approved :: GNU General Public License (GPL)',
              'Natural Language :: English',
              'Operating System :: OS Independent',
              'Programming Language :: Python',
              'Programming Language :: Python :: 2',
          ]
          )
