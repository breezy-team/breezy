DEBUGGER ?= 
BZR_OPTIONS ?= 
BZR ?= $(shell which bzr)
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
	BZR_PLUGINS_AT=git@$(shell pwd) $(DEBUGGER) $(PYTHON) $(PYTHON_OPTIONS) $(BZR) $(BZR_OPTIONS) selftest $(TEST_OPTIONS) $(TESTS)

check-all::
	$(MAKE) check TESTS="^bzrlib.plugins.git. Git"

check-verbose::
	$(MAKE) check TEST_OPTIONS=-v

check-one::
	$(MAKE) check TEST_OPTIONS=--one

check-random::
	$(MAKE) check TEST_OPTIONS="--random=now --verbose --one"

show-plugins::
	BZR_PLUGINS_AT=git@$(shell pwd) $(BZR) plugins -v

lint::
	$(PYLINT) -f parseable *.py */*.py

tags::
	$(CTAGS) -R .

ctags:: tags

coverage::
	$(MAKE) check BZR_OPTIONS="--coverage coverage"

.PHONY: update-pot po/bzr-git.pot
update-pot: po/bzr-git.pot

TRANSLATABLE_PYFILES:=$(shell find . -name '*.py' \
		| grep -v 'tests/' \
		)

po/bzr-git.pot: $(PYFILES) $(DOCFILES)
	BZR_PLUGINS_AT=git@$(shell pwd) bzr export-pot \
          --plugin=git > po/bzr-git.pot
	echo $(TRANSLATABLE_PYFILES) | xargs \
	  xgettext --package-name "bzr-git" \
	  --msgid-bugs-address "<bazaar@lists.canonical.com>" \
	  --copyright-holder "Canonical Ltd <canonical-bazaar@lists.canonical.com>" \
	  --from-code ISO-8859-1 --sort-by-file --join --add-comments=i18n: \
	  -d bzr-git -p po -o bzr-git.pot
