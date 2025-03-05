OUT=./out

$(OUT):
	mkdir $(OUT)
	mkdir $(OUT)/examples

$(OUT)/examples/rltest: examples/rltest.c | $(OUT)
	gcc -Wall -lreadline examples/rltest.c -o $(OUT)/examples/rltest

$(OUT)/examples/fgets: examples/fgets.c | $(OUT)
	gcc -Wall -lreadline examples/fgets.c -o $(OUT)/examples/fgets

$(OUT)/examples/input: examples/input.c | $(OUT)
	gcc -Wall -lreadline examples/input.c -o $(OUT)/examples/input

.PHONY: build
build: $(OUT)/examples/rltest $(OUT)/examples/fgets $(OUT)/examples/input

.PHONY: run
run: build
	echo "" > /tmp/read  #<<< TODO
	# <<< ./instrument.py $(OUT)/examples/rltest
	# <<< ./instrument.py $(OUT)/examples/fgets
	# <<< ./instrument.py $(OUT)/examples/input
	./instrument.py python
	# <<< ./instrument.py cat
	# <<< ./instrument.py examples/input
	# <<< ./instrument.py examples/read-stdin

.PHONY: clean
clean:
	rm -r $(OUT)
