class RNG {
    mix(a, rounds) {
	const mask = a.length - 1;
	for(let j = 0; j < rounds; j++) {
	    for(let i = 0; i < a.length; i++) {
		let rv = a[i];
		rv = (rv + (a[(i + mask) & mask])) & 0xFFFFFFFF;
		rv = (rv * 469331) & 0xFFFFFFFF;
		rv ^= (rv >>> 15) ^ (rv >>> 7);
		a[i] = rv + 1;
	    }
	}
    }

    mixString(s) {
	var sz = 1;
	while(sz < s || sz < this.ctrSize) {
	    sz *= 2;
	}
	let a = new Array(sz);
	for(let i = 0; i < s.length; i++) {
	    a[i] = s.charAt(i);
	}
	for(let i = s.length; i < sz; i++) {
	    a[i] = 1;
	}
	this.mix(a, this.rounds);
	for(let i = 0; i < this.ctrSize; i++) {
	    this.ctr[i] ^= a[i];
	}
	this.update();
    }
    
    expand() {
	for(let j = 0; j < this.rndBufSize; j += this.ctrSize) {
	    for(let i = 0; i < this.ctrSize; i++) {
		this.rndBuf[j + i] = this.ctr[i];
	    }
	}
	this.mix(this.rndBuf, this.rounds);
	this.pos = this.rndBufSize;
    }

    update() {
	let carry = 0;
	for(let i = 0; i < this.ctrSize; i++) {
	    this.ctr[i] += 0x5B89092B + carry;
	    carry = this.ctr[i] > 0xFFFFFFFF ? 1 : 0;
	    this.ctr[i] &= 0xFFFFFFFF;
	}
	this.expand();
    }

    next() {
	if(this.pos == 0) {
	    this.update();
	}
	return this.rndBuf[--this.pos];
    }

    nextInt(bound) {
	if (bound <= 0) {
	    throw new Error('Bound must be positive.');
	}
	const m = bound - 1;
	let r = this.next() >>> 1;
	if ((bound & m) == 0) {
	    r &= m;
	} else {
	    for (let u = r >>> 1; u + m - (r = u % bound) < 0;
		 u = this.next() >>> 1) ;
	}
	return r;
    }

    nextBool() {
        return this.nextInt(2) == 1;
    }

    shuffle(a) {
	for(let i = a.length - 1; i > 0; i--) {
	    let r = this.nextInt(i + 1);
	    let tmp = a[r];
	    a[r] = a[i];
	    a[i] = tmp;
	}
	return a;
    }

    pad_array(arr,len,fill) {
	return arr.concat(Array(len).fill(fill)).slice(0,len);
    }

    nextDouble() {
	const LOWER_UNIT = 1.11022302462515654E-16;
	const UPPER_UNIT = 2.384185791015625E-7;
	const lower = (this.next() & 0x7FFFFFFF) * LOWER_UNIT;
	const upper = (this.next() & 0x3FFFFF) * UPPER_UNIT;
	return upper + lower;
    }

    nextGaussian(mean, stdDev) {
	if (this.hasSpare) {
	    this.hasSpare = false;
	    return this.spare * stdDev + mean;
	} else {
	    let u, v, s;
	    do {
		u = this.nextDouble() * 2 - 1;
		v = this.nextDouble() * 2 - 1;
		s = u * u + v * v;
	    } while (s >= 1 || s == 0);
	    s = Math.sqrt(-2.0 * Math.log(s) / s);
	    this.spare = v * s;
	    this.hasSpare = true;
	    return mean + stdDev * u * s;
	}
    }

    expandSeed(seed, length) {
	let seedClone;
	if(seed.length < length) {
	    seedClone = pad_array(seed, length, 0x23456789);
	} else {
	    seedClone = seed.slice(0);
	}
	this.mix(seedClone, 4);
	return seedClone.slice(0, length);
    }

    bias(t, a) {
	return t / ((1/a - 2) * (1 - t) + 1);
    }
    
    intList(length, bias) {
	let a = [];
	let v = 0;
	let dupC = 0;
	for(let i = 0; i < length; i++) {
	    a[i] = Math.trunc(length * this.bias(i / length, bias / 2.0 + 0.5));
	}
	this.shuffle(a);
	return a;
    }

    keyList(length, bias) {
	let a = [];
	let v = 0;
	let dupC = 0;
	for(let i = 0; i < length; i++) {
	    a[i] = String.fromCharCode(65 + Math.trunc(length * this.bias(i / length, bias / 2.0 + 0.5)));
	}
	this.shuffle(a);
	return a;
    }

    relabelInts(a, min, max) {
	let unique = [...new Set(a)];
	if(unique.length > max - min) {
	    throw new Error("Too narrow range for max - min; has to be at least " + unique.length);
	}
	let labels = new Map();
	if(unique.length < (max - min) / 2) {
	    let used = new Set();
	    for(let i = 0; i < unique.length; i++) {
		let r = 0;
		do {
		    r = this.nextInt(max - min) + min;
		} while(used.has(r));
		used.add(r);
		labels.set(unique[i], r);
	    }
	} else {
	    let tmpLabels = [];
	    for(let i = 0; i < max - min; i++) {
		tmpLabels[i] = i + min;
	    }
	    this.shuffle(tmpLabels);
	    for(let i = 0; i < unique.length; i++) {
		labels.set(unique[i], tmpLabels[i]);
	    }
	}
	let result = [];
	for(let i = 0; i < a.length; i++) {
	    result[i] = labels.get(a[i]);
	}
	return result;
    }

    setup(seed, ctrExp, bufExp, rounds) {
	this.ctrSize = 1 << ctrExp;
	this.ctr = [];
	this.rndBufSize = 1 << bufExp;
	this.rndBufMask = this.rndBufSize - 1;
	this.rndBuf = [];
	this.rounds = rounds;
	let expandedSeed = seed.slice(0);
	expandedSeed = this.expandSeed(expandedSeed);
	for(let i = 0; i < this.ctrSize; i++) {
	    this.ctr[i] = expandedSeed[i];
	}
	this.pos = 0;
	this.hasSpace = false;
    }

    constructor(seed, key) {
	if(typeof seed === 'undefined') {
	    seed = "";
	}
	if(typeof key === 'undefined') {
	    key = "";
	}
	if(typeof key !== 'string') {
	    key = key.toString();
	}
	if(typeof seed !== 'string') {
	    seed = seed.toString();
	}
	seed = int_hmac_sha1(seed, key);
	this.setup(seed, 4, 4, 3);
    }
}
