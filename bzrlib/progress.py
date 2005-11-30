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


"""Simple text-mode progress indicator.

To display an indicator, create a ProgressBar object.  Call it,
passing Progress objects indicating the current state.  When done,
call clear().

Progress is suppressed when output is not sent to a terminal, so as
not to clutter log files.
"""

# TODO: should be a global option e.g. --silent that disables progress
# indicators, preferably without needing to adjust all code that
# potentially calls them.

# TODO: If not on a tty perhaps just print '......' for the benefit of IDEs, etc

# TODO: Optionally show elapsed time instead/as well as ETA; nicer
# when the rate is unpredictable


import sys
import time
import os
from collections import deque


def _supports_progress(f):
    if not hasattr(f, 'isatty'):
        return False
    if not f.isatty():
        return False
    if os.environ.get('TERM') == 'dumb':
        # e.g. emacs compile window
        return False
    return True



def ProgressBar(to_file=sys.stderr, **kwargs):
    """Abstract factory"""
    if _supports_progress(to_file):
        return TTYProgressBar(to_file=to_file, **kwargs)
    else:
        return DotsProgressBar(to_file=to_file, **kwargs)
    
    
class _BaseProgressBar(object):
    def __init__(self,
                 to_file=sys.stderr,
                 show_pct=False,
                 show_spinner=False,
                 show_eta=True,
                 show_bar=True,
                 show_count=True):
        object.__init__(self)
        self.to_file = to_file
 
        self.last_msg = None
        self.last_cnt = None
        self.last_total = None
        self.show_pct = show_pct
        self.show_spinner = show_spinner
        self.show_eta = show_eta
        self.show_bar = show_bar
        self.show_count = show_count



class DummyProgress(_BaseProgressBar):
    """Progress-bar standin that does nothing.

    This can be used as the default argument for methods that
    take an optional progress indicator."""
    def tick(self):
        pass

    def update(self, msg=None, current=None, total=None):
        pass

    def clear(self):
        pass
        
    
class DotsProgressBar(_BaseProgressBar):
    def __init__(self, **kwargs):
        _BaseProgressBar.__init__(self, **kwargs)
        self.last_msg = None
        self.need_nl = False
        
    def tick(self):
        self.update()
        
    def update(self, msg=None, current_cnt=None, total_cnt=None):
        if msg and msg != self.last_msg:
            if self.need_nl:
                self.to_file.write('\n')
            
            self.to_file.write(msg + ': ')
            self.last_msg = msg
        self.need_nl = True
        self.to_file.write('.')
        
    def clear(self):
        if self.need_nl:
            self.to_file.write('\n')
        
    
class TTYProgressBar(_BaseProgressBar):
    """Progress bar display object.

    Several options are available to control the display.  These can
    be passed as parameters to the constructor or assigned at any time:

    show_pct
        Show percentage complete.
    show_spinner
        Show rotating baton.  This ticks over on every update even
        if the values don't change.
    show_eta
        Show predicted time-to-completion.
    show_bar
        Show bar graph.
    show_count
        Show numerical counts.

    The output file should be in line-buffered or unbuffered mode.
    """
    SPIN_CHARS = r'/-\|'
    MIN_PAUSE = 0.1 # seconds


    def __init__(self, **kwargs):
        from bzrlib.osutils import terminal_width
        _BaseProgressBar.__init__(self, **kwargs)
        self.spin_pos = 0
        self.width = terminal_width()
        self.start_time = None
        self.last_update = None
        self.last_updates = deque()
    

    def throttle(self):
        """Return True if the bar was updated too recently"""
        now = time.time()
        if self.start_time is None:
            self.start_time = self.last_update = now
            return False
        else:
            interval = now - self.last_update
            if interval > 0 and interval < self.MIN_PAUSE:
                return True

        self.last_updates.append(now - self.last_update)
        self.last_update = now
        return False
        

    def tick(self):
        self.update(self.last_msg, self.last_cnt, self.last_total)
                 


    def update(self, msg, current_cnt=None, total_cnt=None):
        """Update and redraw progress bar."""

        if current_cnt < 0:
            current_cnt = 0
            
        if current_cnt > total_cnt:
            total_cnt = current_cnt

        # save these for the tick() function
        self.last_msg = msg
        self.last_cnt = current_cnt
        self.last_total = total_cnt
            
        if self.throttle():
            return 
        
        if self.show_eta and self.start_time and total_cnt:
            eta = get_eta(self.start_time, current_cnt, total_cnt,
                    last_updates = self.last_updates)
            eta_str = " " + str_tdelta(eta)
        else:
            eta_str = ""

        if self.show_spinner:
            spin_str = self.SPIN_CHARS[self.spin_pos % 4] + ' '            
        else:
            spin_str = ''

        # always update this; it's also used for the bar
        self.spin_pos += 1

        if self.show_pct and total_cnt and current_cnt:
            pct = 100.0 * current_cnt / total_cnt
            pct_str = ' (%5.1f%%)' % pct
        else:
            pct_str = ''

        if not self.show_count:
            count_str = ''
        elif current_cnt is None:
            count_str = ''
        elif total_cnt is None:
            count_str = ' %i' % (current_cnt)
        else:
            # make both fields the same size
            t = '%i' % (total_cnt)
            c = '%*i' % (len(t), current_cnt)
            count_str = ' ' + c + '/' + t 

        if self.show_bar:
            # progress bar, if present, soaks up all remaining space
            cols = self.width - 1 - len(msg) - len(spin_str) - len(pct_str) \
                   - len(eta_str) - len(count_str) - 3

            if total_cnt:
                # number of markers highlighted in bar
                markers = int(round(float(cols) * current_cnt / total_cnt))
                bar_str = '[' + ('=' * markers).ljust(cols) + '] '
            elif False:
                # don't know total, so can't show completion.
                # so just show an expanded spinning thingy
                m = self.spin_pos % cols
                ms = (' ' * m + '*').ljust(cols)
                
                bar_str = '[' + ms + '] '
            else:
                bar_str = ''
        else:
            bar_str = ''

        m = spin_str + bar_str + msg + count_str + pct_str + eta_str

        assert len(m) < self.width
        self.to_file.write('\r' + m.ljust(self.width - 1))
        #self.to_file.flush()
            

    def clear(self):        
        self.to_file.write('\r%s\r' % (' ' * (self.width - 1)))
        #self.to_file.flush()        
    

        
def str_tdelta(delt):
    if delt is None:
        return "-:--:--"
    delt = int(round(delt))
    return '%d:%02d:%02d' % (delt/3600,
                             (delt/60) % 60,
                             delt % 60)


def get_eta(start_time, current, total, enough_samples=3, last_updates=None, n_recent=10):
    if start_time is None:
        return None

    if not total:
        return None

    if current < enough_samples:
        return None

    if current > total:
        return None                     # wtf?

    elapsed = time.time() - start_time

    if elapsed < 2.0:                   # not enough time to estimate
        return None
    
    total_duration = float(elapsed) * float(total) / float(current)

    assert total_duration >= elapsed

    if last_updates and len(last_updates) >= n_recent:
        while len(last_updates) > n_recent:
            last_updates.popleft()
        avg = sum(last_updates) / float(len(last_updates))
        time_left = avg * (total - current)

        old_time_left = total_duration - elapsed

        # We could return the average, or some other value here
        return (time_left + old_time_left) / 2

    return total_duration - elapsed


def run_tests():
    import doctest
    result = doctest.testmod()
    if result[1] > 0:
        if result[0] == 0:
            print "All tests passed"
    else:
        print "No tests to run"


def demo():
    sleep = time.sleep
    
    print 'dumb-terminal test:'
    pb = DotsProgressBar()
    for i in range(100):
        pb.update('Leoparden', i, 99)
        sleep(0.1)
    sleep(1.5)
    pb.clear()
    sleep(1.5)
    
    print 'smart-terminal test:'
    pb = ProgressBar(show_pct=True, show_bar=True, show_spinner=False)
    for i in range(100):
        pb.update('Elephanten', i, 99)
        sleep(0.1)
    sleep(2)
    pb.clear()
    sleep(1)

    print 'done!'

if __name__ == "__main__":
    demo()
