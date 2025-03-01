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

$(OUT)/myread.so: myread.c | $(OUT)
	gcc -g -o $(OUT)/myread.so -shared myread.c

.PHONY: build
build: $(OUT)/examples/rltest $(OUT)/examples/fgets $(OUT)/examples/input $(OUT)/myread.so

.PHONY: run
run: build
	echo "" > /tmp/read  #<<< TODO
	# <<< LD_PRELOAD=$(OUT)/myread.so $(OUT)/examples/rltest
	LD_PRELOAD=$(OUT)/myread.so $(OUT)/examples/fgets
	# <<< LD_PRELOAD=$(OUT)/myread.so $(OUT)/examples/input
	# <<< LD_PRELOAD=$(OUT)/myread.so python
	# <<< LD_PRELOAD=$(OUT)/myread.so cat
	# <<< LD_PRELOAD=$(OUT)/myread.so ./test
	# <<< LD_DEBUG=all LD_PRELOAD=$(OUT)/myread.so examples/input
	# <<< LD_DEBUG=all LD_PRELOAD=$(OUT)/myread.so examples/read-stdin

.PHONY: clean
clean:
	rm -r $(OUT)
