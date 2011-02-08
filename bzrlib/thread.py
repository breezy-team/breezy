# Copyright (C) 2011 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

import sys
import threading


class ThreadWithException(threading.Thread):
    """A catching exception thread.

    If an exception occurs during the thread execution, it's caught and
    re-raised when the thread is joined().
    """

    def __init__(self, *args, **kwargs):
        # There are cases where the calling thread must wait, yet, if an
        # exception occurs, the event should be set so the caller is not
        # blocked. The main example is a calling thread that want to wait for
        # the called thread to be in a given state before continuing.
        try:
            event = kwargs.pop('event')
        except KeyError:
            # If the caller didn't pass a specific event, create our own
            event = threading.Event()
        super(ThreadWithException, self).__init__(*args, **kwargs)
        self.set_ready_event(event)
        self.exception = None
        self.ignored_exceptions = None # see set_ignored_exceptions

    # compatibility thunk for python-2.4 and python-2.5...
    if sys.version_info < (2, 6):
        name = property(threading.Thread.getName, threading.Thread.setName)

    def set_ready_event(self, event):
        """Set the ``ready`` event used to synchronize exception catching.

        When the thread uses an event to synchronize itself with another thread
        (setting it when the other thread can wake up from a ``wait`` call),
        the event must be set after catching an exception or the other thread
        will hang.

        Some threads require multiple events and should set the relevant one
        when appropriate.
        """
        self.ready = event

    def set_ignored_exceptions(self, ignored):
        """Declare which exceptions will be ignored.

        :param ignored: Can be either:
           - None: all exceptions will be raised,
           - an exception class: the instances of this class will be ignored,
           - a tuple of exception classes: the instances of any class of the
             list will be ignored,
           - a callable: that will be passed the exception object
             and should return True if the exception should be ignored
        """
        if ignored is None:
            self.ignored_exceptions = None
        elif isinstance(ignored, (Exception, tuple)):
            self.ignored_exceptions = lambda e: isinstance(e, ignored)
        else:
            self.ignored_exceptions = ignored

    def run(self):
        """Overrides Thread.run to capture any exception."""
        self.ready.clear()
        try:
            try:
                super(ThreadWithException, self).run()
            except:
                self.exception = sys.exc_info()
        finally:
            # Make sure the calling thread is released
            self.ready.set()


    def join(self, timeout=5):
        """Overrides Thread.join to raise any exception caught.


        Calling join(timeout=0) will raise the caught exception or return None
        if the thread is still alive.

        The default timeout is set to 5 and should expire only when a thread
        serving a client connection is hung.
        """
        super(ThreadWithException, self).join(timeout)
        if self.exception is not None:
            exc_class, exc_value, exc_tb = self.exception
            self.exception = None # The exception should be raised only once
            if (self.ignored_exceptions is None
                or not self.ignored_exceptions(exc_value)):
                # Raise non ignored exceptions
                raise exc_class, exc_value, exc_tb

    def pending_exception(self):
        """Raise the caught exception.

        This does nothing if no exception occurred.
        """
        self.join(timeout=0)
