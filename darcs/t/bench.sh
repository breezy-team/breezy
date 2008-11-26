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
#for i in *_play.tar.gz
for i in small-repo_play.tar.gz
do
	echo "benchmarking $i"
	rm -rf _playground
	tar xf $i
	cd _playground
	sh -c 'time d2x -f git sandbox' 2>&1 |tee ../$i.d-f-e.log
	if diff_git sandbox; then
		echo "ok, the result is correct" >> ../$i.d-f-e.log
	else
		echo "ouch, the result is corrupted" >> ../$i.d-f-e.log
		exit 1
	fi
	cd ..
done
