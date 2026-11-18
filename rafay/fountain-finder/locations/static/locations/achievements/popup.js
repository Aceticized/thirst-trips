(() => {
  const assets = document.currentScript.dataset.assets;
  const style = document.createElement("style");
  style.textContent = `
    .achievement-pop {position:fixed;inset:0;z-index:10000;display:grid;place-content:center;justify-items:center;gap:10px;padding:max(16px,env(safe-area-inset-top)) 16px max(16px,env(safe-area-inset-bottom));background:rgba(23,57,31,.5);-webkit-backdrop-filter:blur(3px);backdrop-filter:blur(3px);animation:achievement-fade .25s ease-out;font:16px "Playpen Sans",system-ui,sans-serif}
    .achievement-pop .badge {display:block;width:min(560px,calc(100vw - 32px));padding:0;background:none;border:0;cursor:pointer;-webkit-tap-highlight-color:transparent;animation:achievement-pop .6s cubic-bezier(.2,1.4,.4,1)}
    .achievement-pop .badge img {display:block;width:100%;height:auto;filter:drop-shadow(0 14px 22px rgba(0,0,0,.4));-webkit-user-select:none;user-select:none;-webkit-touch-callout:none}
    .achievement-pop .hint {margin:0;color:#fff;font-weight:600;text-shadow:0 1px 6px rgba(0,0,0,.5)}
    .achievement-pop .text-card {width:min(420px,calc(100vw - 32px));box-sizing:border-box;padding:22px 24px;color:#17391f;background:#f5fff0;border:2px solid #89bd70;border-radius:24px;box-shadow:0 12px 40px #17391f40;text-align:center;cursor:pointer;font:inherit}
    .achievement-pop .text-card small {text-transform:uppercase;letter-spacing:.12em;color:#37652c}
    .achievement-pop .text-card strong {display:block;font-size:24px;margin:8px 0}
    .achievement-pop .text-card p {margin:8px 0;line-height:1.5}
    @keyframes achievement-fade {from{opacity:0}}
    @keyframes achievement-pop {from{opacity:0;transform:scale(.55) rotate(-4deg)}}
    @media (prefers-reduced-motion: reduce) {.achievement-pop,.achievement-pop .badge {animation:none}}
  `;
  document.head.append(style);

  const audio = new Audio(assets + "unlock.mp3");
  audio.volume = 0.5;
  audio.preload = "auto";
  let busy = false;
  let priming = null;
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  const gestures = ["pointerdown", "keydown", "touchstart"];

  // Browsers only let a page start sound after the visitor has touched it. The first tap anywhere quietly
  // "warms up" the sound, so a later popup (the visitor is usually still on the same page) can play on its own.
  function prime() {
    gestures.forEach(type => window.removeEventListener(type, prime, true));
    audio.muted = true;
    priming = audio.play().then(() => { audio.pause(); audio.currentTime = 0; }).catch(() => {}).finally(() => {
      audio.muted = false;
      priming = null;
    });
  }
  gestures.forEach(type => window.addEventListener(type, prime, {capture: true, passive: true}));

  function textCard(item) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "text-card";
    const heading = document.createElement("small");
    heading.textContent = "★ Achievement unlocked";
    const name = document.createElement("strong");
    name.textContent = item.name;
    const description = document.createElement("p");
    description.textContent = item.description;
    card.append(heading, name, description);
    return card;
  }

  // The achievement's own picture (named after its code). Resolves to null if there isn't one.
  function badgeFor(item) {
    return new Promise(resolve => {
      if (!item.code) return resolve(null);
      const image = new Image();
      image.alt = "";
      image.draggable = false;
      image.onload = () => {
        const badge = document.createElement("button");
        badge.type = "button";
        badge.className = "badge";
        badge.append(image);
        resolve(badge);
      };
      image.onerror = () => resolve(null);
      image.src = assets + encodeURIComponent(item.code) + ".png";
    });
  }

  async function show(item) {
    const picture = (await badgeFor(item)) || textCard(item);
    const overlay = document.createElement("div");
    overlay.className = "achievement-pop";
    overlay.setAttribute("role", "status");
    overlay.setAttribute("aria-live", "polite");
    picture.setAttribute("aria-label", "Achievement unlocked: " + item.name + ". " + item.description + " Press to close.");
    const hint = document.createElement("p");
    hint.className = "hint";
    hint.textContent = "Tap to close";
    overlay.append(picture, hint);
    document.body.append(overlay);

    window.dispatchEvent(new Event("achievements:popup")); // lets other sounds on the page (the check-in one) stop
    if (priming) await priming;
    audio.muted = false;
    audio.volume = 0.5;
    audio.currentTime = 0;
    let soundBlocked = false;
    try { await audio.play(); } catch { soundBlocked = true; }
    if (soundBlocked) hint.textContent = "🔊 Tap to hear the sound";

    // A tap closes the popup, unless the browser held the sound back: then the first tap plays it instead.
    await Promise.race([
      wait(6500),
      new Promise(resolve => overlay.addEventListener("click", () => {
        if (soundBlocked) {
          soundBlocked = false;
          hint.textContent = "Tap to close";
          audio.play().catch(() => {});
          return;
        }
        resolve();
      })),
    ]);

    for (let step = 1; step <= 5 && !audio.paused; step++) { // fade the sound out instead of cutting it
      audio.volume = Math.max(0, 0.5 * (1 - step / 5));
      await wait(60);
    }
    audio.pause();
    overlay.remove();
    await wait(250);
  }

  async function check() {
    if (busy || document.visibilityState === "hidden") return;
    busy = true;
    try {
      // Do not consume notifications for signed-out users.
      const me = await fetch("/api/me/", {credentials:"same-origin", cache:"no-store"});
      if (!me.ok) return;
      const csrf = await fetch("/api/auth/csrf/", {credentials:"same-origin", cache:"no-store"});
      if (!csrf.ok) return;
      const {csrfToken} = await csrf.json();
      const response = await fetch("/api/achievements/notifications/claim/", {
        method:"POST", credentials:"same-origin", cache:"no-store",
        headers:{"Content-Type":"application/json", "X-CSRFToken":csrfToken}, body:"{}",
      });
      if (!response.ok) return;
      for (const item of (await response.json()).notifications) await show(item);
    } catch { /* The next page load or action can retry an unreachable server. */ }
    finally { busy = false; }
  }
  window.addEventListener("achievements:check", check);
  window.addEventListener("focus", check);
  check();
})();
