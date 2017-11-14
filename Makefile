BRZ ?= $(shell which brz)
BRZ_OPTIONS ?= -Derror
PYTHON ?= $(shell which python)
SETUP ?= $(PYTHON) ./setup.py
TESTS ?= "^breezy.plugins.debian."

all: update-pot

.PHONY: update-pot po/breezy-debian.pot
update-pot: po/breezy-debian.pot

TRANSLATABLE_PYFILES:=$(shell find . -name '*.py' \
		| grep -v 'tests/' \
		)

po/breezy-debian.pot: $(PYFILES) $(DOCFILES)
	BRZ_PLUGINS_AT=builddeb@$(shell pwd) $(BRZ) export-pot \
          --plugin=builddeb > po/breezy-debian.pot
	echo $(TRANSLATABLE_PYFILES) | xargs \
	  xgettext --package-name "breezy-debian" \
	  --msgid-bugs-address "<bazaar@lists.canonical.com>" \
	  --copyright-holder "Canonical Ltd. <bazaar@lists.canonical.com>" \
	  --from-code ISO-8859-1 --sort-by-file --join --add-comments=i18n: \
	  -d breezy-debian -p po -o breezy-debian.pot

check:
	BRZ_PLUGINS_AT=debian@$(shell pwd) $(PYTHON) $(PYTHON_OPTIONS) $(BRZ) $(BRZ_OPTIONS) selftest $(TEST_OPTIONS) $(TESTS)
