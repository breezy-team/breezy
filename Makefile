all: update-pot

.PHONY: update-pot po/bzr-builddeb.pot
update-pot: po/bzr-builddeb.pot

TRANSLATABLE_PYFILES:=$(shell find . -name '*.py' \
		| grep -v 'tests/' \
		)

po/bzr-builddeb.pot: $(PYFILES) $(DOCFILES)
	BZR_PLUGINS_AT=builddeb@$(shell pwd) bzr export-pot \
          --plugin=builddeb > po/bzr-builddeb.pot
	echo $(TRANSLATABLE_PYFILES) | xargs \
	  xgettext --package-name "bzr-builddeb" \
	  --msgid-bugs-address "<bazaar@lists.canonical.com>" \
	  --copyright-holder "Canonical Ltd. <bazaar@lists.canonical.com>" \
	  --from-code ISO-8859-1 --sort-by-file --join --add-comments=i18n: \
	  -d bzr-builddeb -p po -o bzr-builddeb.pot
