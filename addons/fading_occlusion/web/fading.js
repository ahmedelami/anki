(function(global) {
  console.log("[FadingOcclusion] fading.js loaded", Date.now());
  const cards = new Map();
  let activeCardId = null;

  function log(...args) {
    try {
      console.log("[FadingOcclusion]", ...args);
    } catch (_) {
      // ignore
    }
  }

  function processRegistration(data) {
    if (!data || !data.cardId || !data.overlayId) {
      log("Invalid registration payload", data);
      return;
    }
    log("Processing registration for", data.cardId, data.context);

    const overlay = document.getElementById(data.overlayId);
    if (!overlay) {
      log("Overlay element not found:", data.overlayId);
      return;
    }

    const stepMap = new Map();
    overlay.querySelectorAll(".fo-cover").forEach((cover) => {
      const step = Number(cover.dataset.step || 0);
      if (!stepMap.has(step)) {
        stepMap.set(step, []);
      }
      stepMap.get(step).push(cover);
    });

    const steps = Array.isArray(data.steps) && data.steps.length
      ? data.steps.slice()
      : Array.from(stepMap.keys()).sort((a, b) => a - b);

    cards.set(data.cardId, {
      overlay,
      stepMap,
      steps,
      index: -1,
    });

    if (data.context === "reviewQuestion") {
      activeCardId = data.cardId;
      resetCard(data.cardId);
    } else {
      if (activeCardId === data.cardId) {
        activeCardId = null;
      }
      revealAll(data.cardId);
    }
  }

  function hideStep(state, stepNumber) {
    const covers = state.stepMap.get(stepNumber);
    if (!covers) {
      return;
    }
    covers.forEach((cover) => {
      cover.style.display = "none";
    });
  }

  function revealAll(cardId) {
    const state = cards.get(cardId);
    if (!state) {
      return;
    }
    state.stepMap.forEach((covers) => {
      covers.forEach((cover) => {
        cover.style.display = "none";
      });
    });
    state.index = state.steps.length - 1;
  }

  function resetCard(cardId) {
    const state = cards.get(cardId);
    if (!state) {
      return;
    }
    state.stepMap.forEach((covers) => {
      covers.forEach((cover) => {
        cover.style.display = "";
      });
    });
    state.index = -1;
  }

  function onKeyDown(event) {
    if (event.key !== " " || event.defaultPrevented) {
      return;
    }
    if (event.target && ["INPUT", "TEXTAREA"].includes(event.target.tagName)) {
      return;
    }
    if (!activeCardId) {
      return;
    }
    const state = cards.get(activeCardId);
    if (!state || !state.steps.length) {
      return;
    }

    if (state.index + 1 < state.steps.length) {
      event.preventDefault();
      event.stopPropagation();
      state.index += 1;
      hideStep(state, state.steps[state.index]);
      log("Hidden step", state.steps[state.index], "card", activeCardId);
      return false;
    }

    activeCardId = null;
  }

  function initQueue() {
    const pending = global.ankiFadingQueue || [];
    function push(item) {
      processRegistration(item);
    }
    global.ankiFadingQueue = { push };
    pending.forEach(push);
  }

  document.addEventListener("keydown", onKeyDown, true);
  initQueue();
})(window);
