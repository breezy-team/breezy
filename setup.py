#!/usr/bin/env python
# Copyright (C) 2008 by Canonical Ltd
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

from distutils.core import setup

setup(name='bzr-upload',
      description='Incrementally uploads changes to a dumb server',
      keywords='plugin bzr upload dumb protocol',
      version='0.1.0',
      url='http://launchpad.net/bzr-upload',
      download_url='http://launchpad.net/bzr-upload',
      author='Vincent Ladeuil, Martin Albisetti',
      license='GPL',
      long_description="""
      Web sites are often hosted on servers where bzr can't be installed. In
      other cases, the web site must not give access to its corresponding
      branch (for security reasons for example). Finally, web hosting providers
      often provides only ftp access to upload sites.  This plugin uploads only
      the relevant changes since the last upload using ftp or sftp protocols.
      """,
      package_dir={'bzrlib.plugins.upload':'.',
                   'bzrlib.plugins.upload.tests':'tests'},
      packages=['bzrlib.plugins.upload',
                'bzrlib.plugins.upload.tests']
      )
