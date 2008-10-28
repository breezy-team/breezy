rm -rf test.darcs test.hg
mkdir test.hg
cd test.hg
hg init
cd ..
if [ "$1" != "--stdout" ]; then
	../darcs-fast-export.py test |(cd test.hg; hg fastimport /dev/stdin)
	if [ $? = 0 ]; then
		echo "bugs:"
		diff --exclude .hg -Naur test.hg test/_darcs/pristine
	fi
else
	../darcs-fast-export.py test
fi
