bench-results.png: bench-results.gnu bench-results.dat
	gnuplot bench-results.gnu

bench-results.dat: bench-results.py $(wildcard ../darcs-benchmark/big-zoo/*.log)
	python bench-results.py > bench-results.dat
