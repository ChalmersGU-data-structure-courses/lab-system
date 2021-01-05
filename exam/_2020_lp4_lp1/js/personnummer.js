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
    pnr = pnr.replace('-', '');
    if (pnr.length === 12) {
        pnr = pnr.substring(2);
    }
    var date = new Date(RegExp.$1, RegExp.$2, RegExp.$3),
        check = 0;
    if (Object.prototype.toString.call(date) !== '[object Date]' || isNaN(date.getTime())) return false;
    for (var i = 0; i < pnr.length; i++) {
        var digit = parseInt(pnr.charAt(i), 10);
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
