// zakvaska front-end. No build step and no framework (see CLAUDE.md).

// --- Service worker, so the app is installable on a phone ---------------
if ("serviceWorker" in navigator) {
  window.addEventListener("load", function () {
    navigator.serviceWorker.register("/sw.js").catch(function (err) {
      console.warn("zakvaska: service worker registration failed", err);
    });
  });
}

// --- Is it a good moment to refresh? -------------------------------------
// The regions that show a relative time refresh themselves on a timer (see
// templates_env.live). A refresh replaces markup, so it must not land while
// someone is part way through filling something in — the time you were
// picking for a feed, the minutes in the snooze box — and it must never
// stop landing, because a countdown frozen by a cursor left in a field is
// the very bug all of this exists to fix.
//
// So: quiet for a few seconds after a keystroke, and quiet while the cursor
// sits in a field of a window you are actually looking at. Neither can
// wedge. `document.activeElement` keeps naming the last field even after it
// is blurred and even once the window is in the background, which is why
// `hasFocus` is asked as well: nobody is typing into a window that does not
// have the keyboard, and coming back to a stale clock is worse than coming
// back to a box that went back to its default.
(function () {
  //: How long after the last keystroke a refresh keeps its hands off.
  var QUIET_MS = 8000;
  var typedAt = 0;

  function isField(element) {
    if (!element) return false;
    var tag = element.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
    return element.isContentEditable === true;
  }

  // Captured on the document, so they go on working through every swap.
  ["input", "keydown"].forEach(function (name) {
    document.addEventListener(name, function () {
      typedAt = Date.now();
    }, true);
  });

  window.zakvaskaIdle = function () {
    if (Date.now() - typedAt < QUIET_MS) return false;
    if (!document.hasFocus()) return true;
    return !isField(document.activeElement);
  };
})();

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

// --- Finding a recipe ------------------------------------------------------
// The list is all on the page already, so this hides cards rather than asking
// the server for fewer. The bar arrives hidden and is shown from here: with no
// JavaScript there is no dead search box, just the whole list.
(function () {
  var bar = document.querySelector("[data-recipe-find]");
  var list = document.querySelector("[data-recipe-list]");
  if (!bar || !list) return;

  var box = bar.querySelector("[data-recipe-q]");
  var none = document.querySelector("[data-recipe-none]");
  var chips = bar.querySelectorAll("[data-family]");
  var family = "";

  function apply() {
    var words = box.value.toLowerCase().split(/\s+/).filter(Boolean);
    var shown = 0;
    list.querySelectorAll(".recipe-card").forEach(function (card) {
      var text = card.getAttribute("data-find") || "";
      var match =
        (!family || card.getAttribute("data-family") === family) &&
        words.every(function (word) { return text.indexOf(word) !== -1; });
      card.hidden = !match;
      if (match) shown += 1;
    });
    if (none) none.hidden = shown !== 0;
  }

  chips.forEach(function (chip) {
    chip.addEventListener("click", function () {
      family = chip.getAttribute("data-family");
      chips.forEach(function (other) {
        var on = other === chip;
        other.classList.toggle("is-current", on);
        other.setAttribute("aria-pressed", on ? "true" : "false");
      });
      apply();
    });
  });
  box.addEventListener("input", apply);
  bar.hidden = false;
})();

// --- Counter mode ----------------------------------------------------------
// A running bake, reduced to the step in hand (partials/bake_now.html). It is
// a class on <html>, so it survives the live region swapping itself and is
// there before the first paint after a reload. It is remembered for this tab
// and this bake only: tapping Done posts and comes back to the same address,
// and you should come back to the counter, not to the whole page.
//
// While it is on, the screen is asked to stay awake — the reason for the mode
// is a phone you are not touching. Browsers drop that lock whenever the tab
// is hidden, so it is asked for again on the way back.
(function () {
  var KEY = "zakvaska.counter";
  var root = document.documentElement;
  var lock = null;

  function awake() {
    if (!("wakeLock" in navigator) || document.visibilityState !== "visible") return;
    navigator.wakeLock.request("screen").then(function (got) {
      lock = got;
    }).catch(function () { /* low battery, or not allowed: carry on */ });
  }

  function set(on) {
    root.classList.toggle("counter-mode", on);
    try {
      if (on) sessionStorage.setItem(KEY, location.pathname);
      else sessionStorage.removeItem(KEY);
    } catch (e) { /* private mode: it just will not survive the reload */ }
    if (on) awake();
    else if (lock) { lock.release(); lock = null; }
  }

  function remembered() {
    try { return sessionStorage.getItem(KEY) === location.pathname; }
    catch (e) { return false; }
  }

  // Delegated: the buttons live in a region that is replaced as it refreshes.
  document.addEventListener("click", function (event) {
    if (event.target.closest("[data-counter-on]")) set(true);
    else if (event.target.closest("[data-counter-off]")) set(false);
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && root.classList.contains("counter-mode")) set(false);
  });
  document.addEventListener("visibilitychange", function () {
    if (root.classList.contains("counter-mode")) awake();
  });

  function reveal() {
    document.querySelectorAll("[data-counter-on]").forEach(function (button) {
      button.hidden = false;
    });
    // Nothing to show on this page: do not leave a blank screen behind.
    if (root.classList.contains("counter-mode") && !document.querySelector(".counter")) {
      set(false);
    }
  }
  document.addEventListener("DOMContentLoaded", reveal);
  document.body && document.body.addEventListener("htmx:afterSwap", reveal);
  document.addEventListener("htmx:afterSwap", reveal);

  if (remembered()) set(true);
})();

// --- Looking closer at a chart ---------------------------------------------
// Every chart card ([data-chart]) gets a button that opens it to fill the
// window, and Escape or the same button closes it. The charts sit in regions
// that replace themselves as the clock moves, so the button is put back after
// each swap and a chart that was open is opened again — keyed by the card's
// name, which is unique on a page.
(function () {
  var ICON =
    '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8"' +
    ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M9.5 2.5h4v4M13.5 2.5 9 7M6.5 13.5h-4v-4M2.5 13.5 7 9"/></svg>';
  var open = null;

  function label(button, zoomed) {
    button.innerHTML = ICON + "<span>" + (zoomed ? "Close" : "Enlarge") + "</span>";
    button.setAttribute("aria-pressed", zoomed ? "true" : "false");
  }

  function show(key) {
    open = key;
    document.querySelectorAll("[data-chart]").forEach(function (card) {
      var on = key !== null && card.getAttribute("data-chart") === key;
      card.classList.toggle("is-zoomed", on);
      var button = card.querySelector(".chart-zoom");
      if (button) label(button, on);
    });
    var found = key !== null && document.querySelector('[data-chart="' + key + '"]');
    if (!found) open = null;
    else centreOnNow(found);
    document.documentElement.classList.toggle("has-zoom", open !== null);
  }

  // Where an opened chart is wider than the screen and pans, start it on
  // the `now` line rather than at last night.
  function centreOnNow(card) {
    if (card.scrollWidth <= card.clientWidth) return;
    var drawn = Array.prototype.filter.call(
      card.querySelectorAll("svg.fit"),
      function (svg) { return svg.getClientRects().length > 0; }
    )[0];
    var line = drawn && drawn.querySelector(".ribbon-now line");
    if (!line) return;
    var box = line.getBoundingClientRect();
    card.scrollLeft += box.left - card.clientWidth / 2;
  }

  function dress() {
    document.querySelectorAll("[data-chart]").forEach(function (card) {
      if (card.querySelector(".chart-zoom")) return;
      var button = document.createElement("button");
      button.type = "button";
      button.className = "chart-zoom";
      label(button, false);
      var head = card.querySelector(".chart-head");
      if (head) head.appendChild(button);
      else { button.classList.add("chart-zoom--float"); card.appendChild(button); }
    });
    if (open !== null) show(open);
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest(".chart-zoom");
    if (!button) return;
    var key = button.closest("[data-chart]").getAttribute("data-chart");
    show(open === key ? null : key);
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && open !== null) show(null);
  });
  document.addEventListener("DOMContentLoaded", dress);
  document.addEventListener("htmx:afterSwap", dress);
  dress();
})();

