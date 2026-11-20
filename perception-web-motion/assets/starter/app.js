(() => {
  "use strict";
  const content = window.PERCEPTION_CONTENT;
  if (!content?.tasks?.length) return; // Preserve static HTML if data initialization failed.
  const $ = (selector) => document.querySelector(selector);
  const root = document.documentElement;
  const hero = $(".hero");
  const demo = $("#demo");
  const canvas = $("#signal-field");
  const ctx = canvas.getContext("2d");
  const output = $("#response");
  const geometry = $("#geometry");
  const tablist = $("#task-tabs");
  tablist.replaceChildren(...content.tasks.map((task, index) => {
    const button = document.createElement("button");
    button.id = `tab-${task.id}`;
    button.type = "button";
    button.setAttribute("role", "tab");
    button.setAttribute("aria-controls", "demo-panel");
    button.setAttribute("aria-selected", String(index === 0));
    button.tabIndex = index === 0 ? 0 : -1;
    button.textContent = task.label;
    return button;
  }));
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  const motionButton = $("#motion-toggle");
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const finePointer = matchMedia("(hover: hover) and (pointer: fine)");
  const lifetime = new AbortController();
  const observers = [];
  const on = (target, type, handler) => target.addEventListener(type, handler, { signal: lifetime.signal });
  let userMotionOff = false;
  let disposed = false;
  let heroVisible = false;
  let demoVisible = false;
  let activeIndex = 0;
  let manual = false;
  let runVersion = 0;
  let runController = null;
  let typerController = null;
  let raf = 0;
  let width = 0;
  let height = 0;
  let lastSpawn = 0;
  let particles = [];
  const pointer = { x: -1000, y: -1000 };
  const moving = () => !userMotionOff && !reduced.matches;
  const foreground = () => !document.hidden && !disposed;
  const canReplay = () => moving() && foreground() && demoVisible;
  const canDraw = () => moving() && foreground() && heroVisible;

  // Every wait is abortable; no detached timers survive a task switch or teardown.
  function delay(ms, signal) {
    return new Promise((resolve) => {
      if (signal.aborted) return resolve(false);
      const done = () => { signal.removeEventListener("abort", cancel); resolve(true); };
      const timer = setTimeout(done, ms);
      const cancel = () => { clearTimeout(timer); signal.removeEventListener("abort", cancel); resolve(false); };
      signal.addEventListener("abort", cancel, { once: true });
    });
  }
  function cancelRun() {
    runVersion += 1;
    runController?.abort();
    runController = null;
  }
  function svgElement(name, attributes) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", name);
    Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
    return node;
  }
  function drawAnnotation(mode, numbers, label) {
    if (numbers.some((n) => !Number.isFinite(n) || n < 0 || n > 1000)) return;
    const group = svgElement("g", { class: `annotation ${mode}` });
    if (mode === "box") {
      const [x0, y0, x1, y1] = numbers;
      if (x1 <= x0 || y1 <= y0) return;
      group.append(svgElement("rect", { x: x0, y: y0, width: x1 - x0, height: y1 - y0 }));
    } else {
      group.append(svgElement("circle", { cx: numbers[0], cy: numbers[1], r: 8 }));
      group.append(svgElement("circle", { cx: numbers[0], cy: numbers[1], r: 28, class: "point-ring" }));
    }
    const text = svgElement("text", {
      x: Math.max(12, Math.min(numbers[0], 770)),
      y: Math.max(30, numbers[1] - 17)
    });
    text.textContent = label;
    group.append(text);
    geometry.append(group);
  }
  function makeParser(task) {
    let mode = null;
    let values = [];
    let label = "";
    let readingLabel = false;
    let invalid = false;
    return (token) => {
      const span = document.createElement("span");
      span.textContent = token; // Never interpret model or sample strings as HTML.
      span.className = /^<\d+>$/.test(token) ? "token-number" : token === "<OBJ>" ? "token-obj" : token.startsWith("<") ? "token-tag" : "";
      output.append(span);
      if (token === "<ref>") { label = ""; readingLabel = true; }
      else if (token === "</ref>") readingLabel = false;
      else if (readingLabel) label += token;
      else if (token === "<box>" || token === "<point>") {
        mode = token === "<box>" ? "box" : "point";
        values = [];
        invalid = false;
      } else if (token === "</box>" || token === "</point>") mode = null;
      else if (token === "<OBJ>") {
        const mask = task.maskId ? document.getElementById(task.maskId) : null;
        if (mask) mask.removeAttribute("hidden");
      } else if (mode && /^<\d+>$/.test(token)) {
        values.push(Number(token.slice(1, -1)));
        const needed = mode === "box" ? 4 : 2;
        if (!invalid && values.length === needed) drawAnnotation(mode, values, label);
      } else if (mode && token.trim()) invalid = true;
    };
  }
  function tokensFor(task) {
    return task.response.match(/<[^>]*>|[^<]{1,4}/g) || [];
  }
  function resetTask(task) {
    output.replaceChildren();
    geometry.replaceChildren();
    content.tasks.forEach((sample) => {
      const mask = sample.maskId ? document.getElementById(sample.maskId) : null;
      if (mask) mask.setAttribute("hidden", "");
    });
    $("#task-name").textContent = task.name;
    $("#prompt").textContent = task.prompt;
    tabs.forEach((tab, i) => {
      tab.setAttribute("aria-selected", String(i === activeIndex));
      tab.tabIndex = i === activeIndex ? 0 : -1;
    });
    $("#demo-panel").setAttribute("aria-labelledby", tabs[activeIndex].id);
  }
  function renderComplete() {
    cancelRun();
    const task = content.tasks[activeIndex];
    resetTask(task);
    const emit = makeParser(task);
    tokensFor(task).forEach(emit);
    $("#playback-state").textContent = "complete";
    $("#demo-status").textContent = task.summary;
  }
  async function replay() {
    cancelRun();
    if (!canReplay()) {
      if (!moving()) renderComplete();
      return;
    }
    const mine = runVersion;
    const controller = new AbortController();
    runController = controller;
    const signal = controller.signal;
    const current = () => mine === runVersion && !signal.aborted && canReplay();
    const task = content.tasks[activeIndex];
    try {
      resetTask(task);
      $("#playback-state").textContent = "preparing";
      $("#demo-status").textContent = `${task.label}：准备回放预设输出。`;
      if (!await delay(280, signal) || !current()) return;
      $("#playback-state").textContent = "replaying";
      const emit = makeParser(task);
      for (const token of tokensFor(task)) {
        if (!await delay(token.startsWith("<") ? 115 : 48, signal) || !current()) return;
        emit(token);
      }
      if (!current()) return;
      $("#playback-state").textContent = "complete";
      $("#demo-status").textContent = task.summary;
      if (!manual && await delay(4000, signal) && current()) {
        activeIndex = (activeIndex + 1) % content.tasks.length;
        void replay();
      }
    } catch (error) {
      if (!current()) return;
      $("#playback-state").textContent = "error";
      $("#demo-status").textContent = "回放失败；请重播，或关闭动效查看结果。";
      console.error("Replay failed:", error);
    }
  }
  function selectTask(index) {
    manual = true;
    activeIndex = index;
    if (canReplay()) void replay();
    else renderComplete();
  }
  tabs.forEach((tab, index) => {
    on(tab, "click", () => selectTask(index));
    on(tab, "keydown", (event) => {
      let next = index;
      if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
      else if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = tabs.length - 1;
      else return;
      event.preventDefault();
      tabs[next].focus();
      selectTask(next);
    });
  });
  on($("#replay"), "click", () => {
    manual = true;
    if (canReplay()) void replay();
    else renderComplete();
  });

  function sizeCanvas() {
    if (!ctx) return;
    const rect = canvas.getBoundingClientRect();
    width = rect.width;
    height = rect.height;
    const dpr = Math.min(devicePixelRatio || 1, 2);
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    particles = [];
    if (!raf) paint(performance.now(), false);
  }
  function paint(now, animate) {
    if (!ctx) return;
    ctx.clearRect(0, 0, width, height);
    const gap = width < 700 ? 44 : 34;
    for (let x = 15; x < width; x += gap) {
      for (let y = 15; y < height; y += gap) {
        const strength = animate ? Math.max(0, 1 - Math.hypot(x - pointer.x, y - pointer.y) / 170) : 0;
        ctx.fillStyle = `rgba(149,245,207,${.13 + strength * .6})`;
        ctx.beginPath();
        ctx.arc(x, y, .8 + strength * 1.4, 0, Math.PI * 2);
        ctx.fill();
      }
    }
    if (!animate) return;
    if (now - lastSpawn > 900 && particles.length < 5) {
      const leftSide = Math.random() < .5;
      const w = 45 + Math.random() * 55;
      particles.push({
        x: leftSide ? 10 + Math.random() * width * .12 : width * .8 + Math.random() * width * .08,
        y: 80 + Math.random() * Math.max(10, height - 200), w, h: 40 + Math.random() * 70,
        born: now, life: 4200 + Math.random() * 1400
      });
      lastSpawn = now;
    }
    particles = particles.filter((item) => now - item.born < item.life);
    particles.forEach((item) => {
      const age = now - item.born;
      ctx.globalAlpha = Math.max(0, Math.min(age / 600, (item.life - age) / 900, .65));
      ctx.strokeStyle = "#95f5cf";
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 5]);
      ctx.strokeRect(item.x, item.y, item.w, item.h);
      ctx.setLineDash([]);
      ctx.font = "9px monospace";
      ctx.fillStyle = "#bceedd";
      ctx.fillText("signal", item.x, item.y - 7);
      ctx.beginPath();
      ctx.moveTo(item.x, item.y + 10);
      ctx.lineTo(item.x, item.y);
      ctx.lineTo(item.x + 10, item.y);
      ctx.stroke();
    });
    ctx.globalAlpha = 1;
  }
  function tick(now) {
    raf = 0;
    if (!canDraw()) return;
    paint(now, true);
    raf = requestAnimationFrame(tick);
  }
  function syncCanvas() {
    if (canDraw()) {
      if (!raf) { lastSpawn = performance.now(); raf = requestAnimationFrame(tick); }
    } else {
      cancelAnimationFrame(raf);
      raf = 0;
      particles = [];
      paint(performance.now(), false);
    }
    hero.dataset.running = String(canDraw());
  }
  async function typeCommands(signal) {
    let index = 0;
    const el = $("#hero-command");
    while (!signal.aborted) {
      const text = content.commands[index % content.commands.length];
      for (let i = 0; i <= text.length; i++) {
        if (signal.aborted) return;
        el.textContent = text.slice(0, i);
        if (!await delay(46, signal)) return;
      }
      if (!await delay(1800, signal)) return;
      for (let i = text.length; i >= 0; i--) {
        el.textContent = text.slice(0, i);
        if (!await delay(20, signal)) return;
      }
      index += 1;
    }
  }
  function syncTyper() {
    typerController?.abort();
    typerController = null;
    if (canDraw()) {
      typerController = new AbortController();
      void typeCommands(typerController.signal);
    } else $("#hero-command").textContent = content.commands[0];
  }
  function syncDemo() {
    demo.dataset.running = String(canReplay());
    if (!moving()) renderComplete();
    else if (canReplay()) void replay();
    else {
      cancelRun();
      $("#playback-state").textContent = "paused";
      $("#demo-status").textContent = "暂停：进入视口并回到此标签页后重新回放。";
    }
  }
  function updateMotion() {
    root.dataset.motion = moving() ? "on" : "off";
    motionButton.disabled = reduced.matches;
    motionButton.setAttribute("aria-pressed", String(!moving()));
    motionButton.textContent = reduced.matches ? "已遵循系统减少动态设置" : userMotionOff ? "开启动态演示" : "关闭动效并显示结果";
    if (!moving()) document.querySelectorAll(".reveal-pending").forEach((el) => el.classList.remove("reveal-pending"));
    syncCanvas();
    syncTyper();
    syncDemo();
  }
  on(motionButton, "click", () => { userMotionOff = !userMotionOff; updateMotion(); });
  on(reduced, "change", updateMotion);
  on(document, "visibilitychange", () => {
    root.dataset.paused = String(document.hidden);
    syncCanvas();
    syncTyper();
    syncDemo();
  });
  on(hero, "pointermove", (event) => {
    if (!canDraw() || !finePointer.matches) return;
    const rect = hero.getBoundingClientRect();
    pointer.x = event.clientX - rect.left;
    pointer.y = event.clientY - rect.top;
  });
  on(hero, "pointerleave", () => { pointer.x = pointer.y = -1000; });
  document.querySelectorAll(".spotlight-card").forEach((card) => {
    on(card, "pointermove", (event) => {
      if (!moving() || !finePointer.matches) return;
      const rect = card.getBoundingClientRect();
      card.style.setProperty("--mx", `${event.clientX - rect.left}px`);
      card.style.setProperty("--my", `${event.clientY - rect.top}px`);
    });
  });
  function updateReadingProgress() {
    const distance = root.scrollHeight - innerHeight;
    $(".reading-progress").style.transform = `scaleX(${distance > 0 ? Math.min(1, scrollY / distance) : 0})`;
  }
  on(window, "scroll", updateReadingProgress);
  on(window, "resize", updateReadingProgress);
  if ("ResizeObserver" in window) {
    const resize = new ResizeObserver(sizeCanvas);
    resize.observe(hero);
    observers.push(resize);
  } else on(window, "resize", sizeCanvas);
  if ("IntersectionObserver" in window) {
    const heroObserver = new IntersectionObserver(([entry]) => {
      heroVisible = entry.isIntersecting;
      syncCanvas();
      syncTyper();
    });
    heroObserver.observe(hero);
    const demoObserver = new IntersectionObserver(([entry]) => {
      const next = entry.isIntersecting;
      if (demoVisible !== next) { demoVisible = next; syncDemo(); }
    }, { threshold: .2 });
    demoObserver.observe(demo);
    const revealObserver = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.remove("reveal-pending");
        revealObserver.unobserve(entry.target);
      });
    }, { threshold: .1 });
    document.querySelectorAll(".reveal").forEach((el) => {
      if (moving()) el.classList.add("reveal-pending");
      revealObserver.observe(el);
    });
    observers.push(heroObserver, demoObserver, revealObserver);
  } else heroVisible = demoVisible = true;

  function dispose() {
    disposed = true;
    cancelRun();
    typerController?.abort();
    cancelAnimationFrame(raf);
    observers.forEach((observer) => observer.disconnect());
    lifetime.abort();
  }
  // BFCache needs a fresh lifecycle when the page returns after pagehide cleanup.
  on(window, "pagehide", (event) => {
    dispose();
    if (event.persisted) window.addEventListener("pageshow", (show) => {
      if (show.persisted) location.reload();
    }, { once: true });
  });
  document.querySelectorAll("[data-brand]").forEach((el) => { el.textContent = content.brand; });
  $("[data-title]").textContent = content.title;
  $("[data-title-accent]").textContent = content.titleAccent;
  $("[data-intro]").textContent = content.intro;
  tabs.forEach((tab, i) => { tab.textContent = content.tasks[i].label; });
  [motionButton, $("#task-tabs"), $("#replay")].forEach((el) => { el.hidden = false; });
  sizeCanvas();
  updateReadingProgress();
  updateMotion();
})();
