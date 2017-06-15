DEBUGGER ?= 
BRZ_OPTIONS ?= 
BRZ ?= $(shell which brz)
PYTHON ?= $(shell which python)
SETUP ?= ./setup.py
PYDOCTOR ?= pydoctor
CTAGS ?= ctags
PYLINT ?= pylint
RST2HTML ?= rst2html
TESTS ?= -s bp.git

all:: build 

build::
	$(SETUP) build

build-inplace::

install::
	$(SETUP) install

clean::
	$(SETUP) clean
	rm -f *.so

check:: build-inplace 
	BRZ_PLUGINS_AT=git@$(shell pwd) $(DEBUGGER) $(PYTHON) $(PYTHON_OPTIONS) $(BRZ) $(BRZ_OPTIONS) selftest $(TEST_OPTIONS) $(TESTS)

check-all::
	$(MAKE) check TESTS="^breezy.plugins.git. Git"

check-verbose::
	$(MAKE) check TEST_OPTIONS=-v

check-one::
	$(MAKE) check TEST_OPTIONS=--one

check-random::
	$(MAKE) check TEST_OPTIONS="--random=now --verbose --one"

show-plugins::
	BRZ_PLUGINS_AT=git@$(shell pwd) $(BRZ) plugins -v

lint::
	$(PYLINT) -f parseable *.py */*.py

tags::
	$(CTAGS) -R .

ctags:: tags

coverage::
	$(MAKE) check BRZ_OPTIONS="--coverage coverage"

.PHONY: update-pot po/brz-git.pot
update-pot: po/brz-git.pot

TRANSLATABLE_PYFILES:=$(shell find . -name '*.py' \
		| grep -v 'tests/' \
		)

po/brz-git.pot: $(PYFILES) $(DOCFILES)
	BRZ_PLUGINS_AT=git@$(shell pwd) brz export-pot \
          --plugin=git > po/brz-git.pot
	echo $(TRANSLATABLE_PYFILES) | xargs \
	xgettext --package-name "brz-git" \
	  --msgid-bugs-address "<bazaar@lists.canonical.com>" \
	  --copyright-holder "Canonical Ltd <canonical-bazaar@lists.canonical.com>" \
	  --from-code ISO-8859-1 --sort-by-file --join --add-comments=i18n: \
	  -d brz-git -p po -o brz-git.pot
