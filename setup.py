#!/usr/bin/env python
# Copyright (C) 2008-2011 by Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from info import *

from distutils.core import setup

if __name__ == '__main__':
    version = bzr_plugin_version[:3]
    version_string = ".".join([str(x) for x in version])
    setup(name='bzr-webdav',
          version=version_string,
          author='Vincent Ladeuil',
          maintainer = "vila",
          description='Allows bzr to push on DAV enabled web servers',
          keywords='plugin bzr webdav DAV http https',
          url='http://launchpad.net/bzr.webdav',
          download_url='http://launchpad.net/bzr.webdav',
          license='GNU GPL v2 or later',
          package_dir={'bzrlib.plugins.webdav':'.',
                       'bzrlib.plugins.webdav.tests':'tests'},
          packages=['bzrlib.plugins.webdav',
                    'bzrlib.plugins.webdav.tests'],
          classifiers=[
              'Topic :: Software Development :: Version Control',
              'Environment :: Plugins',
              'Development Status :: 4 - Beta',
              'License :: OSI Approved :: GNU General Public License (GPL)',
              'Natural Language :: English',
              'Operating System :: OS Independent',
              'Programming Language :: Python',
              'Programming Language :: Python :: 2',
          ],
      )
