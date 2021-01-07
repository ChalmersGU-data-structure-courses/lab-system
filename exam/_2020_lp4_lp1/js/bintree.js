
function getTree(rng, size, callback) {
    let treeNum = rng.nextInt(2);
    loadFile("./trees/bintree" + treeNum + ".svg", (data) => {
	let problemText = data;
	let lIdx = rng.relabelInts(rng.intList(size, 0), 0, 26);
	lIdx.sort((a,b) => a-b);
	for(let i = 0; i < size; i++) {
	    problemText = problemText.replace("NODE_" + i, String.fromCharCode(65 + lIdx[i]));
	}
	callback(problemText);
    });
}

function getTree2(rng, callback) {
    loadFile("./trees/bintree2.svg", (data) => {
	let problemText = data;
	let lIdx = rng.relabelInts(rng.intList(16, 0), 4, 33);
	lIdx.sort((a,b) => a-b);
	for(let i = 16; i > 0; i--) {
	    problemText = problemText.replace("NODE_" + i, lIdx[i - 1] * 3);
	}
	callback(problemText);
    });
}

function getGraph(rng, size, callback) {
    loadFile("./trees/UnweightedDAG.svg", (data) => {
	let problemText = data;
	let lIdx = rng.relabelInts(rng.intList(size, 0), 0, 26);
	lIdx.sort((a,b) => a-b);
	for(let i = 0; i < size; i++) {
	    problemText = problemText.replace("NODE_" + i, String.fromCharCode(65 + lIdx[i]));
	}
	callback(problemText);
    });
}

