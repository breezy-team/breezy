T = $(wildcard test*.sh)

all: $(T)
	@echo "passed $$(echo $(T)|wc -w) tests."

$(T):
	@echo "*** $@ ***"; sh $@

.PHONY: $(T)
