#!/usr/bin/env python

# Copyright (C) 2008 Canonical Ltd
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
