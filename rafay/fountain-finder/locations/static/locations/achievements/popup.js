(() => {
  const assets = document.currentScript.dataset.assets;
  const style = document.createElement("style");
  style.textContent = `
    .achievement-toast {position:fixed;z-index:10000;top:max(20px,env(safe-area-inset-top));left:50%;transform:translateX(-50%);width:min(420px,calc(100vw - 32px));box-sizing:border-box;padding:22px 24px;color:#17391f;background:#f5fff0;border:2px solid #89bd70;border-radius:24px;box-shadow:0 12px 40px #17391f40;font:16px system-ui,sans-serif;text-align:center}
    .achievement-toast strong {display:block;font-size:24px;margin:8px 0}
    .achievement-toast p {margin:8px 0;line-height:1.5}
    .achievement-toast button {border:0;border-radius:12px;padding:8px 14px;margin:4px;background:#d8edcd;color:#17391f;cursor:pointer;font:inherit}
    .achievement-toast small {text-transform:uppercase;letter-spacing:.12em;color:#37652c}
  `;
  document.head.append(style);
  const audio = new Audio(assets + "unlock.mp3");
  audio.volume = 0.5;
  let busy = false;
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

  async function show(item) {
    const toast = document.createElement("section");
    toast.className = "achievement-toast";
    toast.setAttribute("role", "status");
    toast.setAttribute("aria-live", "polite");
    const heading = document.createElement("small");
    heading.textContent = "★ Achievement unlocked";
    const name = document.createElement("strong");
    name.textContent = item.name;
    const description = document.createElement("p");
    description.textContent = item.description;
    const sound = document.createElement("button");
    sound.textContent = "Play celebration sound";
    sound.hidden = true;
    sound.addEventListener("click", () => audio.play().then(() => sound.hidden = true).catch(() => {}));
    const close = document.createElement("button");
    close.textContent = "Dismiss";
    toast.append(heading, name, description, sound, close);
    document.body.append(toast);
    audio.currentTime = 0;
    try { await audio.play(); } catch { sound.hidden = false; }
    await Promise.race([wait(6500), new Promise(resolve => close.addEventListener("click", resolve, {once:true}))]);
    audio.pause();
    toast.remove();
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
