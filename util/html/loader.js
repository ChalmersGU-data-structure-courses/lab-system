if (typeof url === 'undefined') {
  obj_url = new URL(document.URL);
  obj_url.searchParams.delete("fetch");
  obj_url.searchParams.append("initial", "1");
  url = obj_url.toString();
}

const event_source = new EventSource(url);
const title = document.title;

document.title = title + " (connecting)";

event_source.onopen = function() {
  console.log("Connection to server opened.");
  document.title = title + " (updating automatically)";
};

event_source.addEventListener("update", (e) => {
  console.log("Update received.");
  var body = new DOMParser().parseFromString(e.data, "text/html").body;
  document.body.replaceWith(body);
  sort();
});

event_source.addEventListener("error", (e) => {
  console.log("Error: " + e.data);
  var b = document.createElement("b");
  b.appendChild(document.createTextNode("Error:"))
  var p = document.createElement("p");
  p.appendChild(b)
  p.appendChild(document.createTextNode(" " + e.data))
  var body = document.createElement("body");
  body.appendChild(p);
  document.body.replaceWith(body);
  event_source.close();
});

event_source.onerror = function() {
  console.log("Connection failed.");
  document.title = title + " (connection failed)";
  document.body.innerHTML += "<p>Connection failed.</p>";
};
