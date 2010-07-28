DEBUGGER ?= 
BZR ?= $(shell which bzr)
PYTHON ?= $(shell which python)
SETUP ?= ./setup.py
CTAGS ?= ctags
PYLINT ?= pylint
TESTS ?= 
DESTDIR ?= 

all:: build 

build::
	$(SETUP) build

install::
ifneq ($(DESTDIR),)
	$(SETUP) install --root "$(DESTDIR)"
else
	$(SETUP) install
endif

clean::
	$(SETUP) clean

check::
	BZR_PLUGINS_AT=rewrite@$(shell pwd) $(DEBUGGER) $(PYTHON) $(BZR) $(BZR_OPTIONS) selftest $(TEST_OPTIONS) --starting-with=bzrlib.plugins.rewrite $(TESTS)

check-verbose::
	$(MAKE) check TEST_OPTIONS=-v

coverage::
	$(MAKE) check BZR_OPTIONS="--coverage coverage"

check-one::
	$(MAKE) check TEST_OPTIONS=--one

show-plugins::
	BZR_PLUGINS_AT=rewrite@$(shell pwd) $(BZR) plugins -v

lint::
	$(PYLINT) -f parseable *.py */*.py

tags::
	$(CTAGS) -R .

ctags:: tags
