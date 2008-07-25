DEBUGGER ?= 
BZR ?= $(shell which bzr)
PYTHON ?= $(shell which python)
SETUP ?= ./setup.py
PYDOCTOR ?= pydoctor
CTAGS ?= ctags
PYLINT ?= pylint
RST2HTML ?= rst2html
TESTS ?= 

all:: build 

build::
	$(SETUP) build

build-inplace::

install::
	$(SETUP) install

clean::
	$(SETUP) clean
	rm -f *.so

TMP_PLUGINS_DIR = $(shell pwd)/.plugins

$(TMP_PLUGINS_DIR):
	mkdir -p $@

$(TMP_PLUGINS_DIR)/git: $(TMP_PLUGINS_DIR)
	ln -sf .. $@

check:: build-inplace $(TMP_PLUGINS_DIR)/git
	BZR_PLUGIN_PATH=$(TMP_PLUGINS_DIR) $(DEBUGGER) $(PYTHON) $(PYTHON_OPTIONS) $(BZR) selftest $(TEST_OPTIONS) --starting-with=bzrlib.plugins.git $(TESTS)

check-verbose::
	$(MAKE) check TEST_OPTIONS=-v

check-one::
	$(MAKE) check TEST_OPTIONS=--one

check-random::
	$(MAKE) check TEST_OPTIONS="--random=now --verbose --one"

show-plugins::
	BZR_PLUGIN_PATH=$(TMP_PLUGINS_DIR) $(BZR) plugins

lint::
	$(PYLINT) -f parseable *.py */*.py

tags::
	$(CTAGS) -R .

ctags:: tags
