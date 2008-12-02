#    source_distiller.py -- Getting the source to build from a branch
#    Copyright (C) 2008 Canonical Ltd.
#
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA


class SourceDistiller(object):
    """A source distiller extracts the source to build from a location.

    It does whatever is needed to give you a source you can build at
    a location of your choice.
    """

    def __init__(self, branch):
        """Create a SourceDistiller to distill from the specified branch.

        :param location: a Branch to extract the source from.
        """
        self.branch = branch

    def distill(self, target):
        """Extract the source to a tree rooted at the given location.

        :param target: a string containing the location at which to 
            place the tree containing the buildable source.
        """
        self.target = target

