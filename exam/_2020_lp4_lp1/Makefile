BABEL=$(HOME)/node_modules/@babel/cli/bin/babel.js
OBFUSCATE=$(HOME)/node_modules/javascript-obfuscator/bin/javascript-obfuscator
JS=js/randutils.js js/sha1.js js/exam20210114.js
TREES=$(addprefix trees/randavl, $(addsuffix .png, 1 2 3 4 5 6 7 8 9 10))

all: $(TREES) js/trees.js generated/exam20210114.html

$(shell mkdir -p generated)

generated/%.png: source/%.rtree source/tree.gv
	gawk -f source/makerandomtrees.awk $< | dot -Gdpi=72 | gvpr -c -fsource/tree.gv | neato -Gdpi=72 -n -Tpng -o $@

trees/%.png: generated/%.png
	pngcrush -d trees $<

js/trees.js: $(TREES) source/maketreesjs.py
	source/maketreesjs.py $(TREES) > $@

clean:
	rm -f js/trees.js trees/randavl*.png
	rm -rf generated

generated/babelled.js: $(JS)
	$(BABEL) $(JS) > $@

generated/obfuscated.js: generated/babelled.js
	$(OBFUSCATE) $< --output $@

generated/exam20210114.html: exam20210114.html js/trees.js generated/obfuscated.js
	gawk -f source/embed-script.awk $< > $@
