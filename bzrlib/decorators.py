# Copyright (C) 2005 Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


__all__ = ['needs_read_lock',
           'needs_write_lock',
           ]

def needs_read_lock(unbound):
    """Decorate unbound to take out and release a read lock.

    This decorator can be applied to methods of any class with lock_read() and
    unlock() methods.
    
    Typical usage:
        
    class Branch(...):
        @needs_read_lock
        def branch_method(self, ...):
            stuff
    """
    def decorated(self, *args, **kwargs):
        self.lock_read()
        try:
            return unbound(self, *args, **kwargs)
        finally:
            self.unlock()
    return decorated


def needs_write_lock(unbound):
    """Decorate unbound to take out and release a write lock."""
    def decorated(self, *args, **kwargs):
        self.lock_write()
        try:
            return unbound(self, *args, **kwargs)
        finally:
            self.unlock()
    return decorated

