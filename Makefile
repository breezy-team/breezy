BZR ?= bzr
SETUP ?= ./setup.py
PYDOCTOR ?= pydoctor
CTAGS = ?= ctags
PYLINT ?= pylint

all:: build

build::
	$(SETUP) build

install::
	$(SETUP) install

clean::
	$(SETUP) clean

TMP_PLUGINS_DIR = $(shell pwd)/.plugins

$(TMP_PLUGINS_DIR):
	mkdir -p $@

$(TMP_PLUGINS_DIR)/svn: $(TMP_PLUGINS_DIR)
	ln -sf `pwd` $(TMP_PLUGINS_DIR)/svn

check:: $(TMP_PLUGINS_DIR)/svn
	BZR_PLUGIN_PATH=$(TMP_PLUGINS_DIR) $(BZR) selftest $(TEST_OPTIONS) svn

check-verbose::
	$(MAKE) check TEST_OPTIONS=-v

check-one::
	$(MAKE) check TEST_OPTIONS=--one

lint::
	$(PYLINT) -f parseable *.py */*.py

pydoctor::
	$(PYDOCTOR) --make-html -c bzr-svn.cfg

tags::
	$(CTAGS) -R .

ctags:: tags
