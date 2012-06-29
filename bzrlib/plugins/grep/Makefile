# Copyright (C) 2010 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

# Makefile based on the Makefile from bzr-hg plugin

DEBUGGER ?=
BZR ?= $(shell which bzr)
PYTHON ?= $(shell which python)
SETUP ?= ./setup.py
PYDOCTOR ?= pydoctor
CTAGS ?= ctags
PYLINT ?= pylint
RST2HTML ?= rst2html
TESTS ?= bzrlib.plugins.grep
TMP_PLUGINS_DIR = $(shell pwd)/.plugins


all:: build

build::
	$(SETUP) build

build-inplace::

install::
	$(SETUP) install

clean::
	$(SETUP) clean
	rm -f *.so
	rm -rf $(TMP_PLUGINS_DIR)
	rm -rf build

$(TMP_PLUGINS_DIR):
	mkdir -p $@

$(TMP_PLUGINS_DIR)/grep: $(TMP_PLUGINS_DIR)
	ln -sf .. $@

check:: build-inplace $(TMP_PLUGINS_DIR)/grep
	BZR_PLUGIN_PATH=$(TMP_PLUGINS_DIR) $(DEBUGGER) $(PYTHON) $(PYTHON_OPTIONS) $(BZR) $(BZR_OPTIONS) selftest $(TEST_OPTIONS) $(TESTS)

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

coverage::
	$(MAKE) check BZR_OPTIONS="--coverage ,coverage"

