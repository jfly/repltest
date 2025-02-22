BUILD=./build

$(BUILD):
	mkdir $(BUILD)

$(BUILD)/rltest: rltest.c | $(BUILD)
	gcc -Wall -lreadline rltest.c -o $(BUILD)/rltest

$(BUILD)/myreadline.so: myreadline.c | $(BUILD)
	gcc -g -o $(BUILD)/myreadline.so -shared myreadline.c

.PHONY: run
run: $(BUILD)/rltest $(BUILD)/myreadline.so
	# <<< LD_PRELOAD=$(BUILD)/myreadline.so $(BUILD)/rltest
	LD_DEBUG=all LD_PRELOAD=$(BUILD)/myreadline.so python

.PHONY: clean
clean:
	rm -r $(BUILD)
