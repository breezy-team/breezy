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
	BZR_PLUGINS_AT=stats@$(shell pwd) $(DEBUGGER) $(PYTHON) $(BZR) $(BZR_OPTIONS) selftest $(TEST_OPTIONS) --starting-with=bzrlib.plugins.stats $(TESTS)

check-verbose::
	$(MAKE) check TEST_OPTIONS=-v

coverage::
	$(MAKE) check BZR_OPTIONS="--coverage coverage"

check-one::
	$(MAKE) check TEST_OPTIONS=--one

show-plugins::
	BZR_PLUGINS_AT=stats@$(shell pwd) $(BZR) plugins -v

lint::
	$(PYLINT) -f parseable *.py */*.py

tags::
	$(CTAGS) -R .

ctags:: tags



.PHONY: update-pot po/bzr-stats.pot
update-pot: po/bzr-stats.pot

TRANSLATABLE_PYFILES:=$(shell find . -name '*.py' \
		| grep -v 'tests/' \
		)

po/bzr-stats.pot: $(PYFILES) $(DOCFILES)
	BZR_PLUGINS_AT=stats@$(shell pwd) bzr export-pot \
          --plugin=stats > po/bzr-stats.pot
	echo $(TRANSLATABLE_PYFILES) | xargs \
	  xgettext --package-name "bzr-stats" \
	  --msgid-bugs-address "<bazaar@lists.canonical.com>" \
	  --copyright-holder "Bazaar Developers <bazaar@lists.canonical.com>" \
	  --from-code ISO-8859-1 --sort-by-file --join --add-comments=i18n: \
	  -d bzr-stats -p po -o bzr-stats.pot
