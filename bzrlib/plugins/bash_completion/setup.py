#!/usr/bin/env python

# Copyright (C) 2010  Martin von Gagern
#
# This file is part of bzr-bash-completion
#
# bzr-bash-completion free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation, either version 2 of the
# License, or (at your option) any later version.
#
# bzr-bash-completion is distributed in the hope that it will be
# useful, but WITHOUT ANY WARRANTY; without even the implied warranty
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from setuptools import setup
from meta import *
from meta import __version__

if __name__ == "__main__":

    readme=file('README.txt').read()
    readme=readme[readme.index('\n===') :
                  readme.index('\n.. cut long_description here')]

    # see http://docs.python.org/distutils/setupscript.html#meta-data
    # and http://docs.python.org/distutils/apiref.html
    # for a list of meta data to be included here.
    setup(
        name="bzr-bash-completion",
        version=__version__,
        description="Generate bash command line completion function for bzr",
        keywords='bash bazaar bzr complete completion plugin shell vcs',
        long_description=readme,
        author="Martin von Gagern",
        author_email="Martin.vGagern@gmx.net",
        license="GNU GPL v2",
        url="https://launchpad.net/bzr-bash-completion",
        packages=["bzrlib.plugins.bash_completion"],
        package_dir={"bzrlib.plugins.bash_completion": "."},
        classifiers=[
            'Development Status :: 5 - Production/Stable',
            'Environment :: Console',
            'Environment :: Plugins',
            'Intended Audience :: Developers',
            'License :: OSI Approved :: GNU General Public License (GPL)',
            'Operating System :: OS Independent',
            'Programming Language :: Python :: 2',
            'Programming Language :: Python',
            'Programming Language :: Unix Shell',
            'Topic :: Software Development :: Version Control',
            'Topic :: System :: Shells',
            # see http://pypi.python.org/pypi?:action=list_classifiers for more
        ],
    )
