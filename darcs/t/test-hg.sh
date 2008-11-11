. lib.sh

create_darcs test --old-fashioned-inventory

rm -rf test.darcs test.hg
mkdir test.hg
cd test.hg
hg init
cd ..
if [ "$1" != "--stdout" ]; then
	../darcs-fast-export.py test |(cd test.hg; hg fastimport /dev/stdin)
	if [ $? = 0 ]; then
		echo "bugs:"
		diff --exclude _darcs --exclude .hg --exclude '*-darcs-backup*' -Naur test.hg test
		exit $?
	fi
else
	../darcs-fast-export.py test
fi
