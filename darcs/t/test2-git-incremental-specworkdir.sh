. lib.sh

create_darcs test2 --darcs-2

rm -rf test2.darcs test2.git
mkdir test2.git
cd test2.git
git --bare init
mkdir darcs
cd ..
if [ "$1" != "--stdout" ]; then
	dmark="$(pwd)/test2.git/darcs/test2.dfe-marks"
	gmark="$(pwd)/test2.git/darcs/test2.gfi-marks"
	rm -f $mark $gmark
	../darcs-fast-export --export-marks=$dmark test2 --working test2.git/darcs/repo |(cd test2.git; git fast-import --export-marks=$gmark)
	diff_git test2 || die "initial conversion differs"
	upd_file_darcs test2 file2 upd_contents
	../darcs-fast-export --export-marks=$dmark --import-marks=$dmark test2 --working test2.git/darcs/repo |(cd test2.git; git fast-import --export-marks=$gmark --import-marks=$gmark)
	diff_git test2 || die "update differs"
else
	../darcs-fast-export test2
fi
