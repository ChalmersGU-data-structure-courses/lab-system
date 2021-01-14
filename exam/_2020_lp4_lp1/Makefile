# Requirements:
# javascript-obfuscator, install with:
#   npm install javascript-obfuscator
# pngcrush

.PHONY: all clean
.DEFAULT: all

.SECONDEXPANSION:

OBFUSCATE=$(HOME)/node_modules/javascript-obfuscator/bin/javascript-obfuscator
TREES=$(addprefix trees/randavl, $(addsuffix .png, 1 2 3 4 5 6 7 8 9 10))

all: $(TREES) js/trees.js generated/exam20210114.html

$(shell mkdir -p generated/js)

trees/%.png: source/%.rtree source/tree.gv
	gawk -f source/makerandomtrees.awk $< | dot -Gdpi=72 | gvpr -c -fsource/tree.gv | neato -Gdpi=72 -n -Tpng -o $@
	pngcrush -ow $< temp-$<

js/trees.js: $(TREES) source/maketreesjs.py
	source/maketreesjs.py $(TREES) > $@

generated/js/%.js: js/%.js
	$(OBFUSCATE) $< --output $@

generated/%.html: %.html $$(shell gawk -f source/get-scripts.awk %.html)
	gawk -f source/embed-script.awk $< > $@

clean:
	rm -f js/trees.js trees/randavl*.png
	rm -rf generated
