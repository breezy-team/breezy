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

.PHONY: update-pot po/bzr-rewrite.pot
update-pot: po/bzr-rewrite.pot

TRANSLATABLE_PYFILES:=$(shell find . -name '*.py' \
		| grep -v 'tests/' \
		)

po/bzr-rewrite.pot: $(PYFILES) $(DOCFILES)
	bzr export-pot \
          --plugins=rebase,rebase-abort,rebase-continue,rebase-foreign,rebase-todo \
          > po/bzr-rewrite.pot
	echo $(TRANSLATABLE_PYFILES) | xargs \
	  xgettext --package-name "bzr-rewrite" \
	  --msgid-bugs-address "<bazaar@canonical.com>" \
	  --copyright-holder "Canonical" \
	  --from-code ISO-8859-1 --sort-by-file --join --add-comments=i18n: \
	  -d bzr-rewrite -p po -o bzr-rewrite.pot
