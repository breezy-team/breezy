#!/bin/sh

# this is a test as well, but it would take a lot of time, so don't
# prefix it with 'test'.

. lib.sh

if [ ! -d darcs-benchmark ]; then
	darcs get http://code.haskell.org/darcs/darcs-benchmark
	cd darcs-benchmark
else
	cd darcs-benchmark
	darcs pull -a
fi
sh initialise.sh
cd big-zoo
if [ -n "$1" ]; then
	targets=$1
else
	targets=*_play.tar.gz
fi
for i in $targets
do
	echo "benchmarking $i"
	rm -rf _playground
	tar xf $i
	cd _playground
	log="../$i.d-f-e-$(git describe).log"
	sh -c 'time d2x -f git sandbox' 2>&1 |tee $log
	if diff_git sandbox >/dev/null; then
		echo "ok, the result is correct" >> $log
	else
		echo "ouch, the result is corrupted" >> $log
		exit 1
	fi
	cd ..
done
