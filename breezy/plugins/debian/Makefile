BRZ ?= $(shell which brz)
BRZ_OPTIONS ?= -Derror
SETUP ?= $(PYTHON) ./setup.py
TESTS ?= "^breezy.plugins.debian." "^unittest"

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

check:: testsuite

testsuite:
	BRZ_PLUGINS_AT=debian@$(shell pwd) $(BRZ) $(BRZ_OPTIONS) selftest $(TEST_OPTIONS) $(TESTS)

check:: flake8

flake8:
	flake8 . scripts/deb-*

mypy:
	BRZ_PLUGINS_AT=debian@$(shell pwd) mypy -p breezy.plugins.debian

docker:
	buildah build -t ghcr.io/breezy-team/deb-new-upstream:latest -f Dockerfile.deb-new-upstream .
	buildah push ghcr.io/breezy-team/deb-new-upstream:latest
	buildah build -t ghcr.io/breezy-team/deb-auto-backport:latest -f Dockerfile.deb-auto-backport .
	buildah push ghcr.io/breezy-team/deb-auto-backport:latest
	buildah build -t ghcr.io/breezy-team/deb-move-orphaned:latest -f Dockerfile.deb-move-orphaned .
	buildah push ghcr.io/breezy-team/deb-move-orphaned:latest
	buildah build -t ghcr.io/breezy-team/deb-import-uncommitted:latest -f Dockerfile.deb-import-uncommitted .
	buildah push ghcr.io/breezy-team/deb-import-uncommitted:latest
