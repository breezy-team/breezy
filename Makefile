DEBUGGER ?= 
BZR ?= $(shell which bzr)
PYTHON ?= $(shell which python)
SETUP ?= ./setup.py
PYDOCTOR ?= pydoctor
CTAGS ?= ctags
PYLINT ?= pylint
TESTS ?= svn

all:: build

build::
	$(SETUP) build

build-inplace::
	$(SETUP) build_ext --inplace

install::
	$(SETUP) install

clean::
	$(SETUP) clean

TMP_PLUGINS_DIR = $(shell pwd)/.plugins

$(TMP_PLUGINS_DIR):
	mkdir -p $@

$(TMP_PLUGINS_DIR)/svn: build-inplace $(TMP_PLUGINS_DIR)
	ln -sf `pwd` $(TMP_PLUGINS_DIR)/svn

check:: $(TMP_PLUGINS_DIR)/svn
	BZR_PLUGIN_PATH=$(TMP_PLUGINS_DIR) $(DEBUGGER) $(PYTHON) $(BZR) selftest $(TEST_OPTIONS) $(TESTS)

check-verbose::
	$(MAKE) check TEST_OPTIONS=-v

check-one::
	$(MAKE) check TEST_OPTIONS=--one

show-plugins::
	BZR_PLUGIN_PATH=$(TMP_PLUGINS_DIR) $(BZR) plugins

lint::
	$(PYLINT) -f parseable *.py */*.py

pydoctor::
	$(PYDOCTOR) --make-html -c bzr-svn.cfg

tags::
	$(CTAGS) -R .

ctags:: tags
