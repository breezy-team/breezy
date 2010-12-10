#!/usr/bin/env python
# Copyright (C) 2008-2010 by Canonical Ltd
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

if __name__ == '__main__':
    from distutils.core import setup
    series = bzr_plugin_version[:2]
    series_string = ".".join([str(x) for x in series])
    version = bzr_plugin_version[:3]
    version_string = ".".join([str(x) for x in version])
    setup(name='bzr-upload',
          description='Incrementally uploads changes to a dumb server',
          keywords='plugin bzr upload dumb protocol',
          version=version_string,
          url='http://launchpad.net/bzr-upload/%s/%s/bzr-upload-%s.tar.gz' % (
            series_string, version_string, version_string),
          download_url='http://launchpad.net/bzr-upload',
          author='Vincent Ladeuil, Martin Albisetti',
          author_email='v.ladeuil+lp@free.fr',
          license='GPL',
          long_description="""\
Web sites are often hosted on servers where bzr can't be
installed.  In other cases, the web site must not give access to
its corresponding branch (for security reasons for example).
Finally, web hosting providers often provides only ftp access to
upload sites.  This plugin uploads only the relevant changes since
the last upload using ftp or sftp protocols.
""",
          package_dir={'bzrlib.plugins.upload':'.'},
          packages=['bzrlib.plugins.upload',
                    'bzrlib.plugins.upload.tests']
          )
