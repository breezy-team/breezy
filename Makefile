DEBUGGER ?= 
BZR ?= $(shell which bzr)
PYTHON ?= $(shell which python)
SETUP ?= ./setup.py
PYDOCTOR ?= pydoctor
CTAGS ?= ctags
PYLINT ?= pylint
RST2HTML ?= rst2html
TESTS ?= 

all:: build build-inplace README.html FAQ.html AUTHORS.html

build::
	$(SETUP) build

build-inplace::
	$(SETUP) build_ext --inplace

build-inplace-debug::
	$(SETUP) build_ext --inplace --debug

install::
	$(SETUP) install

clean::
	$(SETUP) clean
	rm -f *.so

TMP_PLUGINS_DIR = $(shell pwd)/.plugins

$(TMP_PLUGINS_DIR):
	mkdir -p $@

$(TMP_PLUGINS_DIR)/svn: $(TMP_PLUGINS_DIR)
	ln -sf .. $@

check:: build-inplace $(TMP_PLUGINS_DIR)/svn 
	BZR_PLUGIN_PATH=$(TMP_PLUGINS_DIR) $(DEBUGGER) $(PYTHON) $(PYTHON_OPTIONS) $(BZR) selftest $(TEST_OPTIONS) --starting-with=bzrlib.plugins.svn $(TESTS)

check-verbose::
	$(MAKE) check TEST_OPTIONS=-v

check-one::
	$(MAKE) check TEST_OPTIONS=--one

check-random::
	$(MAKE) check TEST_OPTIONS="--random=now --verbose --one"

valgrind-check:: build-inplace-debug
	$(MAKE) check DEBUGGER="valgrind --suppressions=/usr/lib/valgrind/python.supp $(VALGRIND_OPTIONS)"

leak-check:: 
	$(MAKE) valgrind-check VALGRIND_OPTIONS="--leak-check=full --show-reachable=yes --num-callers=200 --leak-resolution=med --log-file=leaks.log"

gdb-check:: build-inplace-debug
	$(MAKE) check DEBUGGER="gdb --args $(GDB_OPTIONS)"

strace-check::
	$(MAKE) check DEBUGGER="strace $(STRACE_OPTIONS)"

show-plugins::
	BZR_PLUGIN_PATH=$(TMP_PLUGINS_DIR) $(BZR) plugins

lint::
	$(PYLINT) -f parseable *.py */*.py

pydoctor::
	$(PYDOCTOR) --make-html -c bzr-svn.cfg

FAQ.html README.html AUTHORS.html: %.html: %
	$(RST2HTML) $< > $@

tags::
	$(CTAGS) -R .

ctags:: tags
