#! /usr/bin/env python

# (C) 2005 Canonical Ltd

"""Benchmark for basicio

Tries serializing an inventory to basic_io repeatedly.
"""

if True:
    import psyco
    psyco.full()


import sys
from timeit import Timer
from tempfile import TemporaryFile, NamedTemporaryFile

from bzrlib.branch import Branch
from bzrlib.xml5 import serializer_v5
from bzrlib.basicio import write_inventory, BasicWriter, \
        read_inventory
from bzrlib.inventory import Inventory, InventoryEntry, InventoryFile, ROOT_ID

## b = Branch.open('.')
## inv = b.get_inventory(b.last_revision())

nrepeats = 3
ntimes = 5
NFILES = 30000

def make_inventory():
    inv = Inventory()
    for i in range(NFILES):
        ie = InventoryFile('%08d-id' % i, '%08d-file' % i, ROOT_ID)
        ie.text_sha1='1212121212121212121212121212121212121212'
        ie.text_size=12312
        inv.add(ie)
    return inv

inv = make_inventory()

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

def run_benchmark(function_name, tmp_file):
    t = Timer(function_name + '()', 
              'from __main__ import ' + function_name)
    times = t.repeat(nrepeats, ntimes)
    tmp_file.seek(0, 2)
    size = tmp_file.tell()
    print 'wrote inventory to %10s %5d times, each %6d bytes, total %6dkB' \
            % (function_name, ntimes, size, (size * ntimes)>>10), 
    each = (min(times)/ntimes*1000)
    print 'in %.1fms each' % each 
    return each

def profileit(fn): 
    import hotshot, hotshot.stats
    prof_f = NamedTemporaryFile()
    prof = hotshot.Profile(prof_f.name)
    prof.runcall(fn) 
    prof.close()
    stats = hotshot.stats.load(prof_f.name)
    #stats.strip_dirs()
    stats.sort_stats('time')
    ## XXX: Might like to write to stderr or the trace file instead but
    ## print_stats seems hardcoded to stdout
    stats.print_stats(20)

if '-p' in sys.argv[1:]:
    profileit(bio_test)
else:
    bio_each = run_benchmark('bio_test', bio_tmp)
    xml_each = run_benchmark('xml_test', xml_tmp)
    print 'so bio is %.1f%% faster' % (100 * ((xml_each / bio_each) - 1))

# make sure it was a fair comparison
# assert 'cElementTree' in sys.modules
