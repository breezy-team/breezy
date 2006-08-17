
from bzrlib.trace import info as bzrinfo, mutter as bzrmutter

verbose = False

def set_verbose(v):
  verbose=v
  
def debug(fmt, *args):
  """Log a message that will be shown if verbose is on."""
  if verbose:
    bzrinfo(fmt, *args)
  else:
    bzrmutter(fmt, *args)

def info(fmt, *args):
  bzrinfo(fmt, *args)

def _test():
  import doctest
  doctest.testmod()

if __name__ == "__main__":
  _test()


