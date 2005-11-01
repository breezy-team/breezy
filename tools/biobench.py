# (C) 2005 Canonical Ltd

"""Benchmark for basicio

Tries serializing an inventory to basic_io repeatedly.
"""

import sys
from timeit import Timer
from tempfile import TemporaryFile, NamedTemporaryFile

from bzrlib.branch import Branch
from bzrlib.xml5 import serializer_v5
from bzrlib.basicio import write_inventory, BasicWriter

b = Branch.open('.')
inv = b.get_inventory(b.last_revision())
bio_tmp = NamedTemporaryFile()
xml_tmp = NamedTemporaryFile()

def bio_test():
    bio_tmp.seek(0)
    w = BasicWriter(bio_tmp)
    write_inventory(w, inv)
    bio_tmp.seek(0)
    new_inv = read_inventory(bio_tmp)

def xml_test():
    xml_tmp.seek(0)
    serializer_v5.write_inventory(inv, xml_tmp)
    xml_tmp.seek(0)
    new_inv = serializer_v5.read_inventory(xml_tmp)

ntimes = 100

def run_benchmark(function_name, tmp_file):
    t = Timer(function_name + '()', 
              'from __main__ import ' + function_name)
    times = t.repeat(1, ntimes)
    size = tmp_file.tell()
    print 'wrote inventory to %10s %d times, each %d bytes, total %dkB' \
            % (function_name, ntimes, size, (size * ntimes)>>10), 
    each = (min(times)/ntimes*1000)
    print 'in %.3fms each' % each 
    return each

xml_each = run_benchmark('xml_test', xml_tmp)
bio_each = run_benchmark('bio_test', bio_tmp)

print 'so bio is %.1f%% faster' % (100 * ((xml_each / bio_each) - 1))

# make sure it was a fair comparison
assert 'cElementTree' in sys.modules
