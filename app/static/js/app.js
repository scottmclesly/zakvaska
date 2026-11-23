// zakvaska front-end. No build step and no framework (see CLAUDE.md).

// --- Service worker, so the app is installable on a phone ---------------
if ("serviceWorker" in navigator) {
  window.addEventListener("load", function () {
    navigator.serviceWorker.register("/sw.js").catch(function (err) {
      console.warn("zakvaska: service worker registration failed", err);
    });
  });
}

// --- Feeding alerts ------------------------------------------------------
// The server decides when an alert fires; this only mirrors that into a
// desktop notification while a tab happens to be open. Closing the tab must
// never lose an alert, which is why nothing here creates or clears one.
(function () {
  var POLL_MS = 60000;
  var SEEN_KEY = "zakvaska.notified";
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
    var bake = alert.kind === "stage_due";
    var title = bake
      ? "zakvaska: " + alert.subject
      : "zakvaska: feed " + alert.subject;
    var body = bake
      ? alert.subject + " is due " + alert.overdue_by + "."
      : alert.subject + " is " + alert.overdue_by + ".";
    var note = new Notification(title, {
      body: body,
      tag: "zakvaska-alert-" + alert.id,
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


// Loaf-size hot buttons: a bread maker is sold by the pound its pan takes,
// so fill in the flour that gets you there. Two forms ask for it — the bake
// form records the machine setting as text, the planner times the program
// from a number in pounds — so the row names the fields it fills and this
// only moves the values across. See partials/loaf_presets.html.
document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-loaf]");
  if (!button) return;

  const row = button.closest("[data-loaf-row]");
  const form = button.closest("form");
  if (!row || !form) return;

  const fill = (fieldName, value) => {
    if (!fieldName || value === undefined) return;
    const field = form.querySelector(`[name="${fieldName}"]`);
    if (!field) return;
    field.value = value;
    field.dispatchEvent(new Event("input", { bubbles: true }));
  };

  // The flour box reads in whichever unit is on display, so the button
  // carries that text; the grams are the fallback.
  fill(
    row.dataset.flourField,
    button.dataset.flourText ||
      String(Math.round(parseFloat(button.dataset.flour)))
  );
  fill(row.dataset.sizeField, button.dataset.size);
  fill(row.dataset.poundsField, button.dataset.pounds);

  row.querySelectorAll("[data-loaf]").forEach((other) => {
    other.classList.toggle("is-chosen", other === button);
  });

  // Say what happened, now that the fields hold the new numbers. The
  // planner listens for this and redraws the plan; the bake form has
  // nothing listening, and nothing goes wrong there.
  document.body.dispatchEvent(
    new CustomEvent("loaf-chosen", { bubbles: true })
  );
});


// --- Lid colour on the jar form -----------------------------------------
// The swatches and the colour picker are two controls for one field, and the
// "another colour" radio is what tells the server to read the picker. The
// form is correct without this: it only saves you ticking that radio by hand
// after choosing a colour.
document.addEventListener("input", (event) => {
  const picker = event.target.closest(".cap-picker");
  if (!picker) return;

  const row = picker.closest(".cap-row");
  const radio = row && row.querySelector('.is-any input[type="radio"]');
  if (radio) radio.checked = true;

  // Show the chosen colour on its chip, so the row reads as one control.
  const chip = row && row.querySelector(".is-any .cap-chip");
  if (chip) {
    chip.style.setProperty("--cap", picker.value);
    chip.style.backgroundImage = "none";
  }
});
