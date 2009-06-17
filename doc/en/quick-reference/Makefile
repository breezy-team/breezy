# If you feel the need to duplicate this file, you'll win the right to refactor
# doc/*/quick-reference/Makefile and update TARGETS and OBJECTS usages in
# doc/Makefile

TARGETS=quick-start-summary.png quick-start-summary.pdf
OBJECTS=quick-start-summary.svg Makefile

all: $(TARGETS)

.SUFFIXES: .svg .png .pdf

.svg.pdf:
	rsvg-convert -d 300 -p 300 -f pdf -o $@ $<

.svg.png:
	rsvg-convert -d 300 -p 300 -z 3.3346 -f png -o $@ $<

bzr-quickref.png: $(OBJECTS)

bzr-quickref.pdf: $(OBJECTS)

clean:
	rm -f $(TARGETS)
