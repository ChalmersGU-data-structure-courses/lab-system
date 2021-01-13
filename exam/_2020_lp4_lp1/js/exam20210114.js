
////////////////////////////////////////////////////////////////////////////////
// complexity
function q1(rng) {
    // name randomization
    let names_function = rng.shuffle(['f', 'g', 'h', 'prog', 'algo']);
    let f = names_function[0];

    let names_array = rng.shuffle(['as', 'bs', 'cs', 'ds', 'xs', 'ys']);
    let xs = names_array[0];
    let ys = names_array[1];
    
    let {i, j} = rng.selectUniform([
        {i: 'i', j: 'j'},
        {i: 'j', j: 'k'},
        {i: 'm', j: 'n'},
    ]);

    let {u, v} = rng.selectUniform([
        {u: 'u', v: 'v'},
        {u: 'p', v: 'q'},
        {u: 's', v: 't'},
    ]);

    let names_result = rng.shuffle(['r']);
    let r = names_result[0];

    // irrelevant program code randomization
    let second_loop = rng.nextBool() ? `0 .. ${i}` : `${i} .. ${xs}.length-1`;
    let first_sum = rng.nextBool() ? `${xs}[${i}] + ${xs}[${j}]` : `${xs}[${j}] + ${xs}[${i}]`;
    let second_sum = rng.nextBool() ? `${u} + ${v}` : `${v} + ${u}`;

    let {factor, interval} = rng.selectUniform([
      {factor: 2, interval: 3},
      {factor: 2, interval: 4},
      {factor: 2, interval: 5},
      {factor: 4, interval: 5},
      {factor: 4, interval: 7},
      {factor: 4, interval: 9},
    ]);

    // make sure randomization doesn't impact answer
    let num_intervals = Math.round(12 * Math.log(2) / Math.log(factor));

    let size_new = 1000;

    let time_new = rng.nextBool() ? 'one hour' : 'one day';
    let time_old = time_new;

    let year_new = 2021;
    let year_old = year_new - num_intervals * interval;

    return `
<h4>Algorithm:</h4>
<pre class='pseudocode'>
boolean ${f}(int[] ${xs}):
    ${ys} = new dynamic array of int
    for ${i} in 0 .. ${xs}.length-1:
        for ${j} in ${second_loop}:
            ${ys}.add(${first_sum})

    boolean ${r} = false;
    for ${u} in ${ys}:
        for ${v} in ${ys}:
            if ${second_sum} == 0:
                ${r} = true;
    return ${r};
</pre>
<h4>Part B question:</h4>
<p>
When you run the program on your computer in ${year_new} on an array of size ${size_new}, it takes ${time_old}.
Your computer has gotten faster by a factor of ${factor} every ${interval} years.
What is the largest array size you could have processed in ${time_new} in ${year_old}?
</p>
`;
}


////////////////////////////////////////////////////////////////////////////////
// sorting
function q2(rng) {
    let arr =
        rng.nextBool() ?
        [2, 3, 8, 9, 7, 4, 1, 6, 5] :
        [8, 2, 6, 9, 5, 3, 1, 7, 4] ;
    for (let i = 0; i < arr.length; i++) {
        let extra = rng.nextInt(8);
        if (extra >= 3) extra++; // Unlucky numbers avoidance
        if (extra >= 8) extra++;
        arr[i] = arr[i] * 10 + extra;
    }
    return "Array: {" + arr.join(", ") + "}";
}


////////////////////////////////////////////////////////////////////////////////
// search trees
function q3(rng, elem) {
    let treeNum = rng.nextInt(10) + 1;
    let n = function(x, l, r) {
        return "" + x + "<ul><li>" + l + "</li><li>" + r + "</li></ul>";
    }
    let trees =
        [n(41, n(25, 10, 33), n(86, n(68, 59, 78), 96)),
         n(40, n(20, 15, 32), n(86, n(68, 50, 71), 92)),
         n(42, n(25, 14, 33), n(84, n(63, 50, 71), 98)),
         n(47, n(28, 10, 31), n(86, n(64, 53, 71), 97)),
         n(46, n(29, 18, 36), n(81, n(60, 53, 75), 94)),
         n(64, n(23, 19, n(44, 35, 51)), n(81, 71, 90)),
         n(68, n(26, 11, n(41, 31, 53)), n(83, 75, 94)),
         n(67, n(28, 14, n(40, 32, 50)), n(82, 79, 95)),
         n(69, n(21, 18, n(40, 34, 59)), n(86, 77, 93)),
         n(62, n(25, 17, n(49, 31, 59)), n(82, 73, 97))]
    return (
      "<p><img src=\"trees/randavl" + treeNum + ".png\"></p>" +
      "<p><b>If you have trouble scanning your answers,</b> " +
      "you can instead write your tree as a nested list. " +
      "For example, you could write the tree above as: " +
      "<ul><li>" + trees[treeNum-1] + "</li></ul></p>" +
      "<p>If you choose to do this, if a node has one child you should say if it's " +
      "the left or right child.</p>")
}


////////////////////////////////////////////////////////////////////////////////
// not in this exam
function q4(rng) {
}


////////////////////////////////////////////////////////////////////////////////
// hash tables
function q5(rng) {
    let varnames = rng.selectUniform(["D E F G H J K",
                                      "J K L M N P Q",
                                      "P Q R S T U V"]).split(" ");
    let [a,b,c,d,e,f,g] = varnames;
    let table = [a,d,'-',g,b,e,'-',c,f];
    let tableitems = table.map((v,i) => `<li>${i}: ${v}</li>`).join("");

    let [ha,hb] = rng.selectUniform([[9,13], [18,4]]),
        [hc,hf] = rng.shuffle([7, 16]),
        [he,hg] = rng.shuffle([3, 12]),
        hd = 8;
    let hashes = [ha, hb, hc, hd, he, hf, hg];
    let hashvalues = varnames.map((v,i) => `hash(${v}) = ${hashes[i]}`).join("<br/>");

    return `
<h4>Hash table array</h4>
<pre>  [${table.join(", ")}]</pre>
or, equivalently:
<ul>${tableitems}</ul>
<h4>Hash values</h4>
<pre>${hashvalues}</pre>
`;
}


////////////////////////////////////////////////////////////////////////////////
// graphs
function q6(rng) {
    let [sx, pt] = [1, 6],
        [pz, sz] = rng.shuffle([3, 4]),
        [ps, px] = rng.shuffle([5, 7]);
    let qt, qx, ru, ry, rz, uy;
    if (rng.nextBool()) {
        [ru, uy] = rng.shuffle([8, 9]);
        [qx, rz] = rng.shuffle([10, 11]);
        [qt, ry] = rng.shuffle([12, 13]);
    } else {
        [ry, uy] = rng.shuffle([8, 9]);
        [qt, rz] = rng.shuffle([10, 11]);
        [qx, ru] = rng.shuffle([12, 13]);
    }

    let p2 = (n) => (n<10 ? ` ${n}` : n);
    let graph = `
   Q -- ${qx} -- X --- ${sx} --- S           R --- ${ry} --- Y
    \\          \\         / \\         / \\         /
     \\          \\       /   \\       /   \\       /
     ${qt}          ${px}     ${ps}     ${sz}    ${rz}    ${p2(ru)}     ${uy}
       \\          \\   /       \\   /       \\   /
        \\          \\ /         \\ /         \\ /
         T -- ${pt} --- P --- ${pz} --- Z           U
`;

    let edges   = "QT QX PT PX PS PZ SX SZ RZ RU RY UY".split(" ");
    let weights = [qt,qx,pt,px,ps,pz,sx,sz,rz,ru,ry,uy];
    let edgelist = edges.map((e,i) => `${e}:${weights[i]}`).join(", ");

    return `
Edge weights:
<ul><li>${edgelist}</li></ul>
or equivalently, as a weighted graph:
<pre>${graph}</pre>
`;
}


////////////////////////////////////////////////////////////////////////////////
// complexity
function q7(rng, elem) {
    // TODO
    return "TODO";
}


////////////////////////////////////////////////////////////////////////////////
// not in this exam
function q8(rng, elem) {
}


////////////////////////////////////////////////////////////////////////////////
// not in this exam
function q9(rng, elem) {
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

