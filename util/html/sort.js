// Inspired by "sortable 1.0" by Jonas Earendel
document.addEventListener('click', event => {
  var sortable = 'sortable'
  var th = event.target
  if (!(th.nodeName === 'TH' && th.classList.contains(sortable)))
		return

  var tr = th.parentNode
  var table = tr.parentNode.parentNode
  var tbody = table.tBodies[0]

	var column_index = th.cellIndex

  var order_asc = 'sortable-order-asc'
  var order_desc = 'sortable-order-desc'
  var order = th.classList.contains(order_asc) ? order_desc : order_asc
  for (let header of tr.cells)
    if (header.classList.contains(sortable))
      for (let order of [order_asc, order_desc])
        header.classList.remove(order)
  th.classList.add(order)

  function key(row) {
    s = row.cells[column_index].dataset.sortKey
    if (s === NaN)
      throw 'invalid sort key ' + row[column_index].dataset.sortKey
    return s
  }

  var rows = Array.prototype.slice.call(tbody.rows)
  rows.sort(function (a, b) {
    var key_a = key(a)
    var key_b = key(b)
    return order == order_asc ? key_a - key_b : key_b - key_a
  })

  for (let row of rows)
    tbody.appendChild(row)
})
