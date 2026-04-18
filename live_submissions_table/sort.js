const sortable = 'sortable';
const order_asc = 'sortable-order-asc';
const order_desc = 'sortable-order-desc';

var sort_column = null;
var sort_order = null;

// Inspired by "sortable 1.0" by Jonas Earendel.
function sort() {
  if (sort_column == null)
    return;

  r = document.getElementsByClassName(sort_column)[0];
  if (!r)
    return;

  const th = r[0];
  const tr = th.parentNode;
  const table = tr.parentNode.parentNode;
  const tbody = table.tBodies[0];
  const column_index = th.cellIndex;

  for (let header of tr.cells)
    if (header.classList.contains(sortable))
      for (let order of [order_asc, order_desc])
        header.classList.remove(order);
  th.classList.add(sort_order);

  function key(row) {
    s = row.cells[column_index].dataset.sortKey;
    if (s === NaN)
      throw 'invalid sort key ' + row[column_index].dataset.sortKey;
    return s;
  }

  function compare(a, b) {
    var key_a = key(a);
    var key_b = key(b);
    return sort_order == order_asc ? key_a - key_b : key_b - key_a;
  }

  var rows = Array.prototype.slice.call(tbody.rows);
  rows.sort(compare);
  for (let row of rows)
    tbody.appendChild(row);
}

function handle(event) {
  var th = event.target;
  if (!(th.nodeName === 'TH' && th.classList.contains(sortable)))
		return;

  sort_column = th.classList[0];
  sort_order = th.classList.contains(order_asc) ? order_desc : order_asc;
  sort();
}

document.addEventListener('click', handle);
