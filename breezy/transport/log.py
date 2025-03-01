# Copyright (C) 2008, 2009, 2010 Canonical Ltd
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

"""Transport decorator that logs transport operations to brz.log."""

# see also the transportstats plugin, which gives you some summary information
# in a machine-readable dump

import time
import types

from ..trace import mutter
from ..transport import decorator


class TransportLogDecorator(decorator.TransportDecorator):
    """Decorator for Transports that logs interesting operations to brz.log.

    In general we want to log things that usually take a network round trip
    and may be slow.

    Not all operations are logged yet.

    See also TransportTraceDecorator, that records a machine-readable log in
    memory for eg testing.
    """

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)

        def _make_hook(hookname):
            def _hook(relpath, *args, **kw):
                return self._log_and_call(hookname, relpath, *args, **kw)

            return _hook

        # GZ 2017-05-21: Not all methods take relpath as first argument, for
        # instance copy_to takes list of relpaths. Also, unclear on url vs
        # filesystem path split. Needs tidying up.
        for methodname in (
            "append_bytes",
            "append_file",
            "copy_to",
            "delete",
            "get",
            "has",
            "open_write_stream",
            "mkdir",
            "move",
            "put_bytes",
            "put_bytes_non_atomic",
            "put_file put_file_non_atomic",
            "list_dir",
            "lock_read",
            "lock_write",
            "readv",
            "rename",
            "rmdir",
            "stat",
            "ulock",
        ):
            setattr(self, methodname, _make_hook(methodname))

    @classmethod
    def _get_url_prefix(self):
        return "log+"

    def iter_files_recursive(self):
        # needs special handling because it does not have a relpath parameter
        mutter("{} {}".format("iter_files_recursive", self._decorated.base))
        return self._call_and_log_result("iter_files_recursive", (), {})

    def _log_and_call(self, methodname, relpath, *args, **kwargs):
        if kwargs:
            kwargs_str = dict(kwargs)
        else:
            kwargs_str = ""
        mutter(
            "{} {} {} {}".format(
                methodname,
                relpath,
                self._shorten(self._strip_tuple_parens(args)),
                kwargs_str,
            )
        )
        return self._call_and_log_result(methodname, (relpath,) + args, kwargs)

    def _call_and_log_result(self, methodname, args, kwargs):
        before = time.time()
        try:
            result = getattr(self._decorated, methodname)(*args, **kwargs)
        except Exception as e:
            mutter("  --> {}".format(e))
            mutter("      %.03fs" % (time.time() - before))
            raise
        return self._show_result(before, methodname, result)

    def _show_result(self, before, methodname, result):
        result_len = None
        if isinstance(result, types.GeneratorType):
            # We now consume everything from the generator so that we can show
            # the results and the time it took to get them.  However, to keep
            # compatibility with callers that may specifically expect a result
            # (see <https://launchpad.net/bugs/340347>) we also return a new
            # generator, reset to the starting position.
            result = list(result)
            return_result = iter(result)
        else:
            return_result = result
        # Is this an io object with a getvalue() method?
        getvalue = getattr(result, "getvalue", None)
        if getvalue is not None:
            val = repr(getvalue())
            result_len = len(val)
            shown_result = "%s(%s) (%d bytes)" % (
                result.__class__.__name__,
                self._shorten(val),
                result_len,
            )
        elif methodname == "readv":
            num_hunks = len(result)
            total_bytes = sum((len(d) for o, d in result))
            shown_result = "readv response, %d hunks, %d total bytes" % (
                num_hunks,
                total_bytes,
            )
            result_len = total_bytes
        else:
            shown_result = self._shorten(self._strip_tuple_parens(result))
        mutter("  --> {}".format(shown_result))
        # The log decorator no longer shows the elapsed time or transfer rate
        # because they're available in the log prefixes and the transport
        # activity display respectively.
        if False:
            elapsed = time.time() - before
            if result_len and elapsed > 0:
                # this is the rate of higher-level data, not the raw network
                # speed using base-10 units (see HACKING.txt).
                mutter("      %9.03fs %8dkB/s" % (elapsed, result_len / elapsed / 1000))
            else:
                mutter("      {:9.3f}s".format(elapsed))
        return return_result

    def _shorten(self, x):
        if len(x) > 70:
            x = x[:67] + "..."
        return x

    def _strip_tuple_parens(self, t):
        t = repr(t)
        if t[0] == "(" and t[-1] == ")":
            t = t[1:-1]
        return t


def get_test_permutations():
    """Return the permutations to be used in testing."""
    from ..tests import test_server

    return [(TransportLogDecorator, test_server.LogDecoratorServer)]
