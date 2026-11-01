// jar-log front-end. No build step and no framework (see CLAUDE.md).

// --- Service worker, so the app is installable on a phone ---------------
if ("serviceWorker" in navigator) {
  window.addEventListener("load", function () {
    navigator.serviceWorker.register("/sw.js").catch(function (err) {
      console.warn("jar-log: service worker registration failed", err);
    });
  });
}

// --- Feeding alerts ------------------------------------------------------
// The server decides when an alert fires; this only mirrors that into a
// desktop notification while a tab happens to be open. Closing the tab must
// never lose an alert, which is why nothing here creates or clears one.
(function () {
  var POLL_MS = 60000;
  var SEEN_KEY = "jarlog.notified";
  var button = document.querySelector("[data-notify-enable]");
  var status = document.querySelector("[data-notify-status]");

  var supported = "Notification" in window;

  function seen() {
    // Remembered per browser so a page refresh does not re-notify.
    try {
      return new Set(JSON.parse(localStorage.getItem(SEEN_KEY) || "[]"));
    } catch (err) {
      return new Set();
    }
  }

  function remember(ids) {
    try {
      localStorage.setItem(SEEN_KEY, JSON.stringify(Array.from(ids).slice(-50)));
    } catch (err) {
      /* private mode: notifications simply repeat, which is harmless */
    }
  }

  function say(text) {
    if (status) status.textContent = text;
  }

  function refreshButton() {
    if (!button) return;
    if (!supported) {
      say("This browser cannot show notifications.");
      return;
    }
    if (Notification.permission === "granted") {
      button.hidden = true;
      say("");
    } else if (Notification.permission === "denied") {
      button.hidden = true;
      say("Notifications are blocked in your browser settings.");
    } else {
      // Permission is only ever requested from this click, never on load.
      button.hidden = false;
      say("");
    }
  }

  if (button) {
    button.addEventListener("click", function () {
      Notification.requestPermission().then(function () {
        refreshButton();
        poll();
      });
    });
  }

  function notify(alert) {
    var note = new Notification("jar-log: feed " + alert.jar_name, {
      body: alert.jar_name + " is " + alert.overdue_by + ".",
      tag: "jarlog-alert-" + alert.id,
      icon: "/static/icons/icon-192.png",
    });
    note.onclick = function () {
      window.focus();
      window.location.href = alert.url;
    };
  }

  function poll() {
    fetch("/api/alerts", { headers: { Accept: "application/json" } })
      .then(function (response) {
        return response.ok ? response.json() : null;
      })
      .then(function (data) {
        if (!data) return;
        if (!supported || Notification.permission !== "granted") return;

        var already = seen();
        data.alerts.forEach(function (alert) {
          if (already.has(alert.id)) return;
          notify(alert);
          already.add(alert.id);
        });
        remember(already);
      })
      .catch(function () {
        /* offline is fine: the banner is already rendered server-side */
      });
  }

  refreshButton();
  poll();
  setInterval(poll, POLL_MS);
})();

// --- Repeating form rows -------------------------------------------------
// Ingredient and stage rows. The form works without this: the server drops
// blank rows and ignores missing ones, so a browser with no JS just gets the
// rows it was served. This only saves a round trip to add another.
(function () {
  function blankCopy(row) {
    var copy = row.cloneNode(true);
    copy.querySelectorAll("input").forEach(function (input) {
      input.value = "";
    });
    copy.querySelectorAll("select").forEach(function (select) {
      select.selectedIndex = 0;
    });
    return copy;
  }

  document.querySelectorAll("[data-repeat]").forEach(function (group) {
    var rows = group.querySelector("[data-repeat-rows]");
    var add = group.querySelector("[data-repeat-add]");
    if (!rows || !add) return;

    add.addEventListener("click", function () {
      var last = rows.querySelector("[data-repeat-row]:last-of-type");
      if (!last) return;
      var copy = blankCopy(last);
      rows.appendChild(copy);
      var first = copy.querySelector("input, select");
      if (first) first.focus();
    });
  });
})();
