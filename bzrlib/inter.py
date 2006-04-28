# Copyright (C) 2006 Canonical Ltd
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


"""Inter-object utility class."""


class InterObject(object):
    """This class represents operations taking place between two objects.

    Its instances have methods like join or copy_content or fetch, and contain
    references to the source and target objects these operations can be 
    carried out between.

    Often we will provide convenience methods on the objects which carry out
    operations with another of similar type - they will always forward to
    a subclass of InterObject - i.e. 
    InterVersionedFile.get(other).method_name(parameters).
    """

    # _optimisers = set()
    # Each concrete InterObject type should have its own optimisers set.

    def __init__(self, source, target):
        """Construct a default InterObject instance. Please use 'get'.
        
        Only subclasses of InterObject should call 
        InterObject.__init__ - clients should call InterFOO.get where FOO
        is the base type of the objects they are interacting between. I.e.
        InterVersionedFile or InterRepository.
        get() is a convenience class method which will create an optimised
        InterFOO if possible.
        """
        self.source = source
        self.target = target

    @classmethod
    def get(klass, source, target):
        """Retrieve a Inter worker object for these objects.

        :param source: the object to be the 'source' member of
                       the InterObject instance.
        :param target: the object to be the 'target' member of
                       the InterObject instance.
        If an optimised worker exists it will be used otherwise
        a default Inter worker instance will be created.
        """
        for provider in klass._optimisers:
            if provider.is_compatible(source, target):
                return provider(source, target)
        return klass(source, target)

    @classmethod
    def register_optimiser(klass, optimiser):
        """Register an InterObject optimiser."""
        klass._optimisers.add(optimiser)

    @classmethod
    def unregister_optimiser(klass, optimiser):
        """Unregister an InterObject optimiser."""
        klass._optimisers.remove(optimiser)
