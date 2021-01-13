

function q1(rng) {
    // TODO
    let sizeV = 6, skew = 0.5;
    let s1 = rng.relabelInts(rng.intList(sizeV, skew), 10, 30);
    let s2 = rng.relabelInts(rng.intList(sizeV, skew * 2), 10, 30);
    return "S1: {" + s1.join(", ") + "}<br>" +
	"S2: {" + s2.join(", ") + "}";
}

function q2(rng) {
    // TODO
    let arr =
        rng.nextBool() ?
         [2, 3, 8, 9, 7, 4, 1, 6, 5] :
         [8, 2, 6, 9, 5, 3, 1, 7, 4] ;
    for (let i = 0; i < arr.length; i++)
        arr[i] = arr[i] * 10 + rng.nextInt(10);
    return arr.join(", ");
}


function q3(rng, elem) {
    let treeNum = rng.nextInt(10) + 1;
    return "<img src=\"trees/randavl" + treeNum + ".png\">";
}


function q4(rng) {
    // TODO
    let sizeV = 6, skew = 0.5;
    let pq = new PQ(rng, skew, sizeV);
    let A = pq.ps(3);
    return "Insättningsordning: " + A[0].join(", ") + "<br><br>" +
	"a) " + A[1].join(", ") + "<br><br>" +
	"b) " + A[2].join(", ") + "<br><br>" +
	"c) " + A[3].join(", ") + "<br><br>";
}


function q5(rng) {
    // TODO
    let capacityV = 5, sizeV = 6, skew = 0.5, minV = 10, maxV = 100;
    let h = ht2(rng, capacityV, sizeV, skew, minV, maxV, 1.1, 1.3);
    let m = h[1];
    let k = h[0];
    let hv = h[2].join(", ");
    return "m = " + m + ", k = " + k + "<br>" + hv;
}


function q6(rng) {
    // TODO
    let size = 12, disjoint = 1;
    let w = getDigraphWeights(rng, size, 20, 30, 3, 20, disjoint);
    w.sort((a,b) => a-b);
    return w.join(", ");
}


function q7(rng, elem) {
    // TODO
    loadFile("./trees/bintree2.svg", (data) => {
	let problemSVG = data;
	let lIdx = rng.relabelInts(rng.intList(16, 0), 4, 33);
	lIdx.sort((a,b) => a-b);
	for(let i = 16; i > 0; i--) {
	    problemSVG = problemSVG.replace("NODE_" + i, lIdx[i - 1] * 3);
	}
	elem.innerHTML = problemSVG;
    });
}


function q8(rng, elem) {
    // TODO
    let pairs = ["AG", "AH", "AF", "BE", "BF", "CE", "DH", "DG", "EG", "EH"];
    let pIdx = rng.nextInt(pairs.length);
    let R = rng.nextInt(10) + 15;
    let startNode = pairs[pIdx].substr(0, 1);
    let endNode = pairs[pIdx].substr(1, 1);
    return "R: " + R + "<br>" +
	"START: " + startNode + "<br>" + 
	"SLUT: " + endNode;
}


function q9(rng, elem) {
    // TODO
    let size = 10;
    loadFile("./trees/UnweightedDAG.svg", (data) => {
	let problemSVG = data;
	let lIdx = rng.relabelInts(rng.intList(size, 0), 0, 26);
	lIdx.sort((a,b) => a-b);
	for(let i = 0; i < size; i++) {
	    problemSVG = problemSVG.replace("NODE_" + i, String.fromCharCode(65 + lIdx[i]));
	}
	elem.innerHTML = problemSVG;
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



////////////////////////////////////////////////////////////////////////////////
// Generic code for all exams

function q(n) {
    let problemTitle = document.getElementById("problemTitle");
    let problemInstance = document.getElementById("problemInstance");
    problemTitle.innerHTML = "&nbsp;";
    problemInstance.innerHTML = "";
    let questions = [null, q1, q2, q3, q4, q5, q6, q7, q8, q9];
    let que = questions[n];
    if (que) {
        let pnr = document.getElementById("personnummer").value;
        let rng = new RNG(filterPnr(pnr));
        problemTitle.innerHTML = "Question " + n + " problem instance:";
        let html = que(rng, problemInstance);
        if (html) {
            problemInstance.innerHTML = html;
        }
    }
}


function validatePnr() {
    let pnr = document.getElementById("personnummer").value;
    let valid = personnummerValid(pnr);
    document.getElementById("statusIndicator").classList.toggle("invisible", valid);
    document.getElementById('questionButtons').classList.toggle("invisible", !valid);
    q();
}


function filterPnr(pnr) {
    return pnr.replace("-", "");
}


function personnummerValid(pnr) {
    if (!pnr) {
        return false;
    }
    if (pnr.indexOf('-') === -1) {
        pnr = pnr.slice(0, 8) + '-' + pnr.slice(8);
    }
    if (!pnr.match(/^(\d{4})(\d{2})(\d{2})\-(\d{4})$/)) {
        return false;
    };
    pnr = filterPnr(pnr);
    if (pnr.length === 12) {
        pnr = pnr.substring(2);
    }
    let date = new Date(RegExp.$1, RegExp.$2, RegExp.$3);
    if (Object.prototype.toString.call(date) !== '[object Date]' || isNaN(date.getTime())) return false;
    let check = 0;
    for (let i = 0; i < pnr.length; i++) {
        let digit = parseInt(pnr.charAt(i), 10);
        if (i % 2 === 0) {
            digit *= 2;
        }
        if (digit > 9) {
            digit -= 9;
        }
        check += digit;
    }
    return check % 10 === 0;
}


function loadFile(url, callback) {
    let request = new XMLHttpRequest();
    request.onreadystatechange = () => {
        if (request.readyState !== 4 || request.status !== 200) return;
        callback(request.responseText);
    };
    request.open('GET', url);
    request.send();
}

