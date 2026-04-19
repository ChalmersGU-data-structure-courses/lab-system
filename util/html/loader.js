const url = 'https://localhost:1234/2026-lp4-lh-requests?password=pw';
const event_source = new EventSource(url);
const title = document.title;

document.title = title + " (connecting)";

event_source.onopen = function() {
  console.log("Connection to server opened.");
  document.title = title + " (updating automatically)";
};

event_source.onmessage = function(e) {
  console.log("Update received.");
  var body = new DOMParser().parseFromString(e.data, "text/html").body;
  document.body.replaceWith(body);
  sort();
};

event_source.onerror = function() {
  console.log("Connection failed.");
  document.title = title + " (connection failed)";
  document.body.innerHTML += "<p>Connection failed.</p>";
};
