"""Line-by-line profiler for Python.

This module provides a line-by-line profiler for Python programs. It is based on
the lsprof profiler from the Python distribution, with modifications to support
Breezy's profiling needs.

The main entry point is the profile() function, which profiles a callable and
returns both the function's result and profiling statistics.

Note: This module is copied from the lsprof distribution because it is not
installed by distutils. The main modification is that profile() returns a pair
(result, stats) instead of just the Stats object.
"""

import _thread
import codecs
import operator
import os
import pickle
import sys
import threading
from _lsprof import Profiler, profiler_entry
from typing import TextIO

from . import errors

__all__ = ["Stats", "profile"]


def profile(f, *args, **kwds):
    """Run a function profile.

    Exceptions are not caught: If you need stats even when exceptions are to be
    raised, pass in a closure that will catch the exceptions and transform them
    appropriately for your driver function.

    Important caveat: only one profile can execute at a time. See BzrProfiler
    for details.

    :return: The functions return value and a stats object.
    """
    profiler = BzrProfiler()
    profiler.start()
    try:
        ret = f(*args, **kwds)
    finally:
        stats = profiler.stop()
    return ret, stats


class BzrProfiler:
    """Bzr utility wrapper around Profiler.

    For most uses the module level 'profile()' function will be suitable.
    However profiling when a simple wrapped function isn't available may
    be easier to accomplish using this class.

    To use it, create a BzrProfiler and call start() on it. Some arbitrary
    time later call stop() to stop profiling and retrieve the statistics
    from the code executed in the interim.

    Note that profiling involves a threading.Lock around the actual profiling.
    This is needed because profiling involves global manipulation of the python
    interpreter state. As such you cannot perform multiple profiles at once.
    Trying to do so will lock out the second profiler unless the global
    breezy.lsprof.BzrProfiler.profiler_block is set to 0. Setting it to 0 will
    cause profiling to fail rather than blocking.
    """

    profiler_block = 1
    """Serialise rather than failing to profile concurrent profile requests."""

    profiler_lock = threading.Lock()
    """Global lock used to serialise profiles."""

    def start(self):
        """Start profiling.

        This hooks into threading and will record all calls made until
        stop() is called.
        """
        self._g_threadmap = {}
        self.p = Profiler()
        permitted = self.__class__.profiler_lock.acquire(self.__class__.profiler_block)
        if not permitted:
            raise errors.InternalBzrError(msg="Already profiling something")
        try:
            self.p.enable(subcalls=True)
            threading.setprofile(self._thread_profile)
        except BaseException:
            self.__class__.profiler_lock.release()
            raise

    def stop(self):
        """Stop profiling.

        This unhooks from threading and cleans up the profiler, returning
        the gathered Stats object.

        :return: A breezy.lsprof.Stats object.
        """
        try:
            self.p.disable()
            for pp in self._g_threadmap.values():
                pp.disable()
            threading.setprofile(None)
            p = self.p
            self.p = None
            threads = {}
            for tid, pp in self._g_threadmap.items():
                threads[tid] = Stats(pp.getstats(), {})
            self._g_threadmap = None
            return Stats(p.getstats(), threads)
        finally:
            self.__class__.profiler_lock.release()

    def _thread_profile(self, f, *args, **kwds):
        """Profile function for new threads.

        This method is called when a new thread starts executing. It creates
        a new Profiler instance for the thread and enables profiling.

        Args:
            f: The function being profiled.
            *args: Positional arguments for the function.
            **kwds: Keyword arguments for the function.
        """
        # we lose the first profile point for a new thread in order to
        # trampoline a new Profile object into place
        thr = _thread.get_ident()
        self._g_threadmap[thr] = p = Profiler()
        # this overrides our sys.setprofile hook:
        p.enable(subcalls=True, builtins=True)


class Stats:
    """Wrapper around the collected data.

    A Stats instance is created when the profiler finishes. Normal
    usage is to use save() to write out the data to a file, or pprint()
    to write human-readable information to the command line.
    """

    def __init__(self, data, threads):
        """Initialize a Stats instance.

        Args:
            data: The profiling data collected by the profiler.
            threads: A dictionary mapping thread IDs to thread-specific Stats objects.
        """
        self.data = data
        self.threads = threads

    def sort(self, crit="inlinetime", reverse=True):
        """Sort the data by the supplied critera.

        :param crit: the data attribute used as the sort key.
        """
        if crit not in profiler_entry.__dict__ or crit == "code":
            raise ValueError(f"Can't sort by {crit}")

        key_func = operator.attrgetter(crit)
        self.data.sort(key=key_func, reverse=reverse)

        for e in self.data:
            if e.calls:
                e.calls.sort(key=key_func, reverse=reverse)

    def pprint(self, top=None, file=None):
        """Pretty-print the data as plain text for human consumption.

        :param top: only output the top n entries.
            The default value of None means output all data.
        :param file: the output file; if None, output will
        default to stdout.
        """
        if file is None:
            file = sys.stdout
        d = self.data
        if top is not None:
            d = d[:top]
        cols = "% 12s %12s %11.4f %11.4f   %s\n"
        hcols = "% 12s %12s %12s %12s %s\n"
        file.write(
            hcols
            % (
                "CallCount",
                "Recursive",
                "Total(ms)",
                "Inline(ms)",
                "module:lineno(function)",
            )
        )
        for e in d:
            file.write(
                cols
                % (
                    e.callcount,
                    e.reccallcount,
                    e.totaltime,
                    e.inlinetime,
                    label(e.code),
                )
            )
            if e.calls:
                for se in e.calls:
                    file.write(
                        cols
                        % (
                            f"+{se.callcount}",
                            se.reccallcount,
                            se.totaltime,
                            se.inlinetime,
                            f"+{label(se.code)}",
                        )
                    )

    def freeze(self):
        """Replace all references to code objects with string
        descriptions; this makes it possible to pickle the instance.
        """
        # this code is probably rather ickier than it needs to be!
        for i in range(len(self.data)):
            e = self.data[i]
            if not isinstance(e.code, str):
                self.data[i] = type(e)((label(e.code),) + e[1:])
            if e.calls:
                for j in range(len(e.calls)):
                    se = e.calls[j]
                    if not isinstance(se.code, str):
                        e.calls[j] = type(se)((label(se.code),) + se[1:])
        for s in self.threads.values():
            s.freeze()

    def calltree(self, file):
        """Output profiling data in calltree format (for KCacheGrind)."""
        _CallTreeFilter(self.data).output(file)

    def save(self, filename, format=None):
        """Save profiling data to a file.

        :param filename: the name of the output file
        :param format: 'txt' for a text representation;
            'callgrind' for calltree format;
            otherwise a pickled Python object. A format of None indicates
            that the format to use is to be found from the filename. If
            the name starts with callgrind.out, callgrind format is used
            otherwise the format is given by the filename extension.
        """
        if format is None:
            basename = os.path.basename(filename)
            if basename.startswith("callgrind.out"):
                format = "callgrind"
            else:
                ext = os.path.splitext(filename)[1]
                if len(ext) > 1:
                    format = ext[1:]
        with open(filename, "wb") as outfile:
            if format == "callgrind":
                # The callgrind format states it is 'ASCII based':
                # <http://valgrind.org/docs/manual/cl-format.html>
                # But includes filenames so lets ignore and use UTF-8.
                self.calltree(codecs.getwriter("utf-8")(outfile))
            elif format == "txt":
                self.pprint(file=codecs.getwriter("utf-8")(outfile))
            else:
                self.freeze()
                pickle.dump(self, outfile, 2)


class _CallTreeFilter:
    """Converter of a Stats object to input suitable for KCacheGrind.

    This code is taken from http://ddaa.net/blog/python/lsprof-calltree
    with the changes made by J.P. Calderone and Itamar applied. Note that
    isinstance(code, str) needs to be used at times to determine if the code
    object is actually an external code object (with a filename, etc.) or
    a Python built-in.
    """

    out_file: TextIO

    def __init__(self, data):
        """Initialize a _CallTreeFilter instance.

        Args:
            data: The profiling data to convert to callgrind format.
        """
        self.data = data

    def output(self, out_file):
        self.out_file = out_file
        out_file.write("events: Ticks\n")
        self._print_summary()
        for entry in self.data:
            self._entry(entry)

    def _print_summary(self):
        """Print the summary line for callgrind format.

        This calculates and outputs the maximum cost (total time) across all
        profiling entries.
        """
        max_cost = 0
        for entry in self.data:
            totaltime = int(entry.totaltime * 1000)
            max_cost = max(max_cost, totaltime)
        self.out_file.write("summary: %d\n" % (max_cost,))

    def _entry(self, entry):
        """Output a single profiling entry in callgrind format.

        Args:
            entry: A profiler_entry object containing profiling data for a
                single function.
        """
        out_file = self.out_file
        code = entry.code
        inlinetime = int(entry.inlinetime * 1000)
        if isinstance(code, str):
            out_file.write("fi=~\n")
        else:
            out_file.write(f"fi={code.co_filename}\n")
        out_file.write(f"fn={label(code, True)}\n")
        if isinstance(code, str):
            out_file.write(f"0  {inlinetime}\n")
        else:
            out_file.write("%d %d\n" % (code.co_firstlineno, inlinetime))
        # recursive calls are counted in entry.calls
        calls = entry.calls if entry.calls else []
        lineno = 0 if isinstance(code, str) else code.co_firstlineno
        for subentry in calls:
            self._subentry(lineno, subentry)
        out_file.write("\n")

    def _subentry(self, lineno, subentry):
        """Output a called function entry in callgrind format.

        Args:
            lineno: The line number in the calling function.
            subentry: A profiler_entry object for the called function.
        """
        out_file = self.out_file
        code = subentry.code
        totaltime = int(subentry.totaltime * 1000)
        if isinstance(code, str):
            out_file.write("cfi=~\n")
            out_file.write(f"cfn={label(code, True)}\n")
            out_file.write("calls=%d 0\n" % (subentry.callcount,))
        else:
            out_file.write(f"cfi={code.co_filename}\n")
            out_file.write(f"cfn={label(code, True)}\n")
            out_file.write("calls=%d %d\n" % (subentry.callcount, code.co_firstlineno))
        out_file.write("%d %d\n" % (lineno, totaltime))


_fn2mod: dict[str, object] = {}


def label(code, calltree=False):
    """Generate a human-readable label for a code object.

    Args:
        code: A code object or string. If a string, it is returned as-is.
        calltree: If True, format the label for callgrind output.

    Returns:
        A string label in the format "module:line(function)" or
        "function module:line" if calltree is True.
    """
    if isinstance(code, str):
        return code
    try:
        mname = _fn2mod[code.co_filename]
    except KeyError:
        for k, v in sys.modules.items():
            if v is None:
                continue
            if getattr(v, "__file__", None) is None:
                continue
            if not isinstance(v.__file__, str):
                continue
            if v.__file__.startswith(code.co_filename):
                mname = _fn2mod[code.co_filename] = k
                break
        else:
            mname = _fn2mod[code.co_filename] = f"<{code.co_filename}>"
    if calltree:
        return "%s %s:%d" % (code.co_name, mname, code.co_firstlineno)
    else:
        return "%s:%d(%s)" % (mname, code.co_firstlineno, code.co_name)


def main():
    """Command-line interface for the lsprof profiler.

    Profiles a Python script and prints the results to stdout.
    """
    sys.argv = sys.argv[1:]
    if not sys.argv:
        sys.stderr.write("usage: lsprof.py <script> <arguments...>\n")
        sys.exit(2)
    import runpy

    _result, stats = profile(runpy.run_path, sys.argv[0], run_name="__main__")
    stats.sort()
    stats.pprint()


if __name__ == "__main__":
    main()
