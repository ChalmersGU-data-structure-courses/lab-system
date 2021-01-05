function rndNotInSet(rng, set, min, max) {
    var r;
    do {
	r = rng.nextInt(max - min) + min;
    } while(set.has(r));
    return r;
}

function sum3(ws, sum) {
    let wset = new Set(ws);
    ws = [...wset];
    ws.sort();
    
    for(var i = 0; i < ws.length; i++) {
	for(var j = i + 1; j < ws.length; j++) {
	    let sum2 = ws[i] + ws[j];
	    let diff = sum - sum2;
	    if(wset.has(diff) && diff != ws[i] && diff != ws[j]) {
		return [true, ws[i], ws[j], diff];
	    }
	}
    }
    return [false];
}

function disjoint3(ws, low3, high3) {
    let sl = sum3(ws, low3);
    if(sl[0]) {
	let dws = new Set(ws);
	dws.delete(sl[1]);
	dws.delete(sl[2]);
	dws.delete(sl[3]);
	let sh = sum3(dws, high3);
	return sh[0];
    }
    return false;
}

function getDigraphWeights(rng, size, low3, high3, dummies, minDummy, disjoint) {
    var used;
    do {
	let ws = rng.intList(size - dummies, 0);
	ws = rng.relabelInts(ws, 1, minDummy);
	used = new Set(ws);
	for(var i = 0; i < dummies; i++) {
	    var r = rndNotInSet(rng, used, minDummy, high3);
	    used.add(r);
	}
//    } while(!disjoint3(used, low3, high3));
    } while((disjoint == 0 && (!sum3(used, low3)[0] || !sum3(used, high3)[0])) ||
	    (disjoint != 0 && !disjoint3(used, low3, high3)));

    let sortedW = [...used];
    sortedW.sort();
    return sortedW;
}
