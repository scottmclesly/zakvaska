// Register the service worker so the app is installable on a phone.
// Kept deliberately tiny — no build step (see CLAUDE.md).
if ("serviceWorker" in navigator) {
  window.addEventListener("load", function () {
    navigator.serviceWorker.register("/sw.js").catch(function (err) {
      console.warn("jar-log: service worker registration failed", err);
    });
  });
}
