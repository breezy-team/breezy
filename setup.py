#!/usr/bin/env python

# Copyright (C) 2009-2018 Jelmer Vernooij <jelmer@jelmer.uk>

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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA



from info import *

readme = file('README').read()


if __name__ == '__main__':
    from distutils.core import setup
    version = bzr_plugin_version[:3]
    version_string = ".".join([str(x) for x in version])

    command_classes = {}
    try:
        from breezy.bzr_distutils import build_mo
    except ImportError:
        pass
    else:
        command_classes['build_mo'] = build_mo

    setup(name='bzr-git',
          description='Support for Git branches in Bazaar',
          keywords='plugin bzr git bazaar',
          version=version_string,
          url='http://bazaar-vcs.org/BzrForeignBranches/Git',
          license='GPL',
          maintainer='Jelmer Vernooij',
          maintainer_email='jelmer@samba.org',
          long_description=readme,
          package_dir={'breezy.plugins.git':'.'},
          packages=['breezy.plugins.git',
                    'breezy.plugins.git.tests'],
          scripts=['bzr-receive-pack', 'bzr-upload-pack', 'git-remote-bzr'],
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
          cmdclass=command_classes,
          )
