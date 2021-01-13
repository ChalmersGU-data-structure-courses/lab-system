function gcd(a, b) {
    if(b == 0) {
        return a;
    } else {
        return this.gcd(b, a % b);
    }
}

function nextRelativePrime(n, p, min) {
    while(this.gcd(n, p) != 1) {
        p = Math.max(min, (p + 1) % n); 
    }
    return p;
}


function prb(keys, hashes, m, k) {
    let ht = [];
    let p = 0;
    if(gcd(m, k) != 1) {
        throw new Error("m and k must be relatively prime (was " + m + ", " + k + ")");
    }
    for(let i = 0; i < keys.length; i++) {
        let h = hashes[i];
        p++;
        while(ht[h] != undefined) {
            h = (h + k) % m;
            p++;
        }
        ht[h] = keys[i];
    }
    return p;
}

function ht(rng, size, skew, min, max, p, c) {
    let m = Math.max(Math.trunc(size * c), size + 1);
    let k = 1;
    let bp = 1E10;
    let bpk = 0;
    let hv = [];
    let hk = [];

    do {    
        hv = rng.relabelInts(rng.intList(size, skew), 0, Math.trunc(size * c));
        hk = rng.keyList(size, 0);
        let keySet = new Set(hk);
        while((k = nextRelativePrime(m, k + 1, min)) < m - 1) {
            let ph = prb(hk, hv, m, k);
            let pf = Math.abs(ph - p * keySet.size);
            if(pf < bp) {
                bpk = k;
                bp = pf;
            }
        }
    } while(bp / size < 0.3 || bp / size > 0.5);
    return [bpk, m, hk.map(function n(x, i) { return x + ":" + hv[i]; })];
}

function ht2(rng, capacity, size, skew, min, max, p, c) {
    var m;
    if(capacity != 0) {
        m = Math.max(Math.trunc(size * c), size + 1);
    } else {
        let m = capacity;
    }
    let k = 1;
    let bp = 1E10;
    let bpk = 0;
    let hv = [];
    let hk = [];

    hv = rng.relabelInts(rng.intList(size, skew), m, m * 2);
    hk = rng.keyList(size, 0);
    let keySet = new Set(hk);
    
    return [bpk, m, hk.map(function n(x, i) { return x + ":" + hv[i]; })];
}
