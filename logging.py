
from bzrlib.trace import info as bzrinfo, mutter as bzrmutter

verbose = False

def set_verbose(v):
  verbose=v
  
def debug(fmt, *args):
  if verbose:
    bzrinfo(fmt, *args)
  else:
    bzrmutter(fmt, *args)

def info(fmt, *args):
  bzrinfo(fmt, *args)

