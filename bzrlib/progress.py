# Copyright (C) 2005 Aaron Bentley <aaron.bentley@utoronto.ca>
# Copyright (C) 2005 Canonical <canonical.com>
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program; if not, write to the Free Software
#    Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""
Simple text-mode progress indicator.

Everyone loves ascii art!

To display an indicator, create a ProgressBar object.  Call it,
passing Progress objects indicating the current state.  When done,
call clear().

Progress is suppressed when output is not sent to a terminal, so as
not to clutter log files.
"""

# TODO: remove functions in favour of keeping everything in one class


import sys
import datetime


def _width():
    """Return estimated terminal width.

    TODO: Do something smart on Windows?

    TODO: Is there anything that gets a better update when the window
          is resized while the program is running?
    """
    import os
    try:
        return int(os.environ['COLUMNS'])
    except (IndexError, KeyError, ValueError):
        return 80


def _supports_progress(f):
    return hasattr(f, 'isatty') and f.isatty()



class Progress(object):
    def __init__(self, units, current, total=None):
        self.units = units
        self.current = current
        self.total = total

    def _get_percent(self):
        if self.total is not None and self.current is not None:
            return 100.0 * self.current / self.total

    percent = property(_get_percent)

    def __str__(self):
        if self.total is not None:
            return "%i of %i %s %.1f%%" % (self.current, self.total, self.units,
                                         self.percent)
        else:
            return "%i %s" (self.current, self.units)



class ProgressBar(object):
    def __init__(self, to_file=sys.stderr):
        object.__init__(self)
        self.start = None
        self.to_file = to_file
        self.suppressed = not _supports_progress(self.to_file)


    def __call__(self, progress):
        if self.start is None:
            self.start = datetime.datetime.now()
        if not self.suppressed:
            draw_progress_bar(progress, start_time=self.start,
                              to_file=self.to_file)

    def clear(self):
        if not self.suppressed:
            clear_progress_bar(self.to_file)
    

        
def divide_timedelta(delt, divisor):
    """Divides a timedelta object"""
    return datetime.timedelta(float(delt.days)/divisor, 
                              float(delt.seconds)/divisor, 
                              float(delt.microseconds)/divisor)

def str_tdelta(delt):
    if delt is None:
        return "-:--:--"
    return str(datetime.timedelta(delt.days, delt.seconds))


def get_eta(start_time, progress, enough_samples=20):
    if start_time is None or progress.current == 0:
        return None
    elif progress.current < enough_samples:
        return None
    elapsed = datetime.datetime.now() - start_time
    total_duration = divide_timedelta((elapsed) * long(progress.total), 
                                      progress.current)
    if elapsed < total_duration:
        eta = total_duration - elapsed
    else:
        eta = total_duration - total_duration
    return eta


def draw_progress_bar(progress, start_time=None, to_file=sys.stderr):
    eta = get_eta(start_time, progress)
    if start_time is not None:
        eta_str = " "+str_tdelta(eta)
    else:
        eta_str = ""

    fmt = " %i of %i %s (%.1f%%)"
    f = fmt % (progress.total, progress.total, progress.units, 100.0)
    cols = _width() - 3 - len(f)
    if start_time is not None:
        cols -= len(eta_str)
    markers = int (float(cols) * progress.current / progress.total)
    txt = fmt % (progress.current, progress.total, progress.units,
                 progress.percent)
    to_file.write("\r[%s%s]%s%s" % ('='*markers, ' '*(cols-markers), txt, 
                                       eta_str))

def clear_progress_bar(to_file=sys.stderr):
    to_file.write('\r%s\r' % (' '*79))


def spinner_str(progress, show_text=False):
    """
    Produces the string for a textual "spinner" progress indicator
    :param progress: an object represinting current progress
    :param show_text: If true, show progress text as well
    :return: The spinner string

    >>> spinner_str(Progress("baloons", 0))
    '|'
    >>> spinner_str(Progress("baloons", 5))
    '/'
    >>> spinner_str(Progress("baloons", 6), show_text=True)
    '- 6 baloons'
    """
    positions = ('|', '/', '-', '\\')
    text = positions[progress.current % 4]
    if show_text:
        text+=" %i %s" % (progress.current, progress.units)
    return text


def spinner(progress, show_text=False, output=sys.stderr):
    """
    Update a spinner progress indicator on an output
    :param progress: The progress to display
    :param show_text: If true, show text as well as spinner
    :param output: The output to write to

    >>> spinner(Progress("baloons", 6), show_text=True, output=sys.stdout)
    \r- 6 baloons
    """
    output.write('\r%s' % spinner_str(progress, show_text))


def run_tests():
    import doctest
    result = doctest.testmod()
    if result[1] > 0:
        if result[0] == 0:
            print "All tests passed"
    else:
        print "No tests to run"


def demo():
    from time import sleep
    pb = ProgressBar()
    for i in range(100):
        pb(Progress('Elephanten', i, 100))
        sleep(0.3)
    print 'done!'

if __name__ == "__main__":
    demo()
