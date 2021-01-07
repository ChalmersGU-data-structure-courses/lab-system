class PQ {
    removeMin() {
	let min = this.v[0];
	let minIdx = 0;
	for(let i = 1; i < this.v.length; i++) {
	    if(this.v[i] < min) {
		min = this.v[i];
		minIdx = i;
	    }
	}
	this.v.splice(minIdx, 1);
	return min;
    }

    removeNotMin() {
	let a = this.removeMin();
	if(this.v.length >= 1) {
	    let b = this.v.splice(this.rng.nextInt(this.v.length), 1)[0];
	    this.v.push(Math.min(a, b));
	    if(b > a) {
		this.o = 1;
	    }
	    return b;
	}
	return a;
    }

    
    quad(a) {
	function removeMin(a) {
	    let min = a[0];
	    let minIdx = 0;
	    for(let i = 1; i < a.length; i++) {
		if(a[i] < min) {
		    min = a[i];
		    minIdx = i;
		}
	    }
	    a.splice(minIdx, 1);
	    return min;
	}
	
	let e = this.e.slice();
	let q = [];
	a = a.slice();
	for(let i = 0; i < a.length; i++) {
	    let j = e.indexOf(a[i]);
	    for(; j >= 0 && e.length > 0; j--) {
		q.push(e.splice(0, 1)[0]);
	    }
	    if(j > 0 || a[i] != removeMin(q)) {
		return false;
	    }
	}
	return true;
    }
    
    rOrder() {
	this.o = 0;
	let e = this.e.slice();
	let r = [];
	let l = e.length * 2;
	let rl = 0;
	let rt = 0;
	for(let i = 0; i < l; i++) {
	    let p = this.rng.nextDouble();
	    let t = this.v.length / (e.length + this.v.length);
	    if(e.length > 0 && (p > t || (rt == 1 && rl > 3))) {
		this.v.push(e.splice(0, 1)[0]);
		if(rt == 0) {
		    rl++;
		} else {
		    rl = 0;
		}
		rt = 0;
	    } else {
		p = this.rng.nextDouble();
		if(p > 1 / l || this.v.length == 1) {
		    r.push(this.removeMin());
		} else {
		    r.push(this.removeNotMin());
		}
		if(rt == 1) {
		    rl++;
		} else {
		    rl = 0;
		}
		rt = 1;
	    }
	}

	return [this.o].concat(r);
    }

    strictlyIncreasing(a, s) {
	let min = a[s + 1];
	for(let i = s + 2; i < a.length; i++) {
	    if(min <= a[i]) {
		min = a[i];
	    } else {
		return false;
	    }
	}
	return true;
    }

    ps(r) {
	function collision(a) {
	    for(let i = 0; i < a.length; i++) {
		for(let j = i + 1; j < a.length; j++) {
		    if(a[i] + "" == a[j] + "") {
			return true;
		    }
		}
	    }
	    return false;
	}
	let a = [];
	let w = 0;
	do {
	    for(let i = 0; i < r - 1; i++) {
		a[i] = this.rOrder();
		if(a[i][0] == 0 || this.quad(a[i].slice(1))) {
		    i--;
		} else {
		    a[i] = a[i].slice(1);
		}
	    }
	} while(collision(a));
	do {
	    a[r - 1] = this.rOrder();
	} while(a[r - 1][0] == 1 || a[r-1] + "" == this.e + "" || (this.strictlyIncreasing(a[r - 1], 0) && false));
	a[r - 1] = a[r - 1].slice(1);
	this.rng.shuffle(a);
	return [this.e].concat(a);
    }
    
    constructor(rng, skew, length) {
	this.rng = rng;
	this.e = rng.relabelInts(rng.intList(length, skew), 0, length);
	this.v = [];
    }
}
