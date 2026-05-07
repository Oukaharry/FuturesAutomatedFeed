(() => {
  function normalize(s) {
    return String(s ?? "")
      .toLowerCase()
      .replace(/\s+/g, " ")
      .trim();
  }

  function setDisabled(el, disabled, reason) {
    if (!el) return;
    el.disabled = !!disabled;
    el.dataset.disabledReason = reason || "";
    if (disabled) {
      el.setAttribute("aria-disabled", "true");
      el.classList.add("rt-disabled");
    } else {
      el.removeAttribute("aria-disabled");
      el.classList.remove("rt-disabled");
    }
  }

  function ensureStyles() {
    if (document.getElementById("rt-search-styles")) return;
    const style = document.createElement("style");
    style.id = "rt-search-styles";
    style.textContent = `
      .rt-search-bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:10px 0 14px}
      .rt-search-input{flex:1 1 320px;min-width:220px;max-width:520px;padding:8px 12px;border-radius:10px;border:1px solid rgba(30,58,138,.35);background:rgba(1,3,10,.55);color:#e8eeff;outline:none;font-family:'IBM Plex Mono',monospace;font-size:.85rem}
      .rt-search-input::placeholder{color:#64748b}
      .rt-search-btn{padding:7px 10px;border-radius:10px;border:1px solid rgba(148,163,184,.22);background:rgba(148,163,184,.08);color:#cbd5e1;cursor:pointer;font-weight:800;font-size:.78rem;letter-spacing:.03em}
      .rt-search-btn:hover{border-color:rgba(96,165,250,.35);background:rgba(96,165,250,.10);color:#93c5fd}
      .rt-search-btn:disabled{opacity:.5;cursor:not-allowed}
      .rt-search-status{font-size:.78rem;color:#94a3b8;font-family:'IBM Plex Mono',monospace}
      tr.rt-search-hit{outline:2px solid rgba(251,191,36,.55);background:rgba(251,191,36,.10)!important}
      tr.rt-search-window{background:rgba(30,58,138,.06)}
      .rt-disabled{opacity:.65}
    `;
    document.head.appendChild(style);
  }

  function getRows(table) {
    const tbody = table?.tBodies?.[0] || table?.querySelector("tbody");
    if (!tbody) return [];
    return Array.from(tbody.querySelectorAll("tr"));
  }

  function rowHaystack(tr) {
    if (!tr) return "";
    // Include control values (inputs often aren't part of textContent/innerText).
    let txt = tr.textContent || "";
    const controls = tr.querySelectorAll("input, textarea, select");
    for (const el of controls) {
      if (el && typeof el.value === "string" && el.value) txt += " " + el.value;
    }
    return normalize(txt);
  }

  function digitsOnly(s) {
    return String(s ?? "").replace(/\D+/g, "");
  }

  function lastNDigits(s, n) {
    const d = digitsOnly(s);
    if (!d) return "";
    return d.length <= n ? d : d.slice(-n);
  }

  function parseRowTarget(q) {
    const n = Number(String(q ?? "").trim());
    if (!Number.isFinite(n)) return null;
    return Math.trunc(n);
  }

  function showWindow(rows, centerIdx, radius) {
    const lo = Math.max(0, centerIdx - radius);
    const hi = Math.min(rows.length - 1, centerIdx + radius);
    rows.forEach((tr, idx) => {
      tr.classList.remove("rt-search-window");
      tr.style.display = idx >= lo && idx <= hi ? "" : "none";
      if (idx >= lo && idx <= hi) tr.classList.add("rt-search-window");
    });
    return { lo, hi };
  }

  function clearWindow(rows) {
    rows.forEach((tr) => {
      tr.style.display = "";
      tr.classList.remove("rt-search-window");
      tr.classList.remove("rt-search-hit");
    });
  }

  function scrollToRow(tr) {
    try {
      tr.scrollIntoView({ block: "center", behavior: "smooth" });
    } catch {
      tr.scrollIntoView(true);
    }
  }

  /**
   * initRealtimeTableSearch({
   *   inputId,
   *   tableSelector,
   *   statusId?,
   *   prevBtnId?,
   *   nextBtnId?,
   *   clearBtnId?,
   *   activeCheckboxId?  // if present and checked => disables search (active-only filter on)
   *   windowRadius?      // default 10
   *   modeSelectId?      // optional <select> with values: 'text' | 'row' | 'acct_last5'
   * })
   */
  function initRealtimeTableSearch(opts) {
    ensureStyles();

    const input = document.getElementById(opts.inputId);
    const statusEl = opts.statusId ? document.getElementById(opts.statusId) : null;
    const prevBtn = opts.prevBtnId ? document.getElementById(opts.prevBtnId) : null;
    const nextBtn = opts.nextBtnId ? document.getElementById(opts.nextBtnId) : null;
    const clearBtn = opts.clearBtnId ? document.getElementById(opts.clearBtnId) : null;
    const activeCb = opts.activeCheckboxId ? document.getElementById(opts.activeCheckboxId) : null;
    const modeSel = opts.modeSelectId ? document.getElementById(opts.modeSelectId) : null;
    const table = document.querySelector(opts.tableSelector);
    const windowRadius = Number.isFinite(opts.windowRadius) ? opts.windowRadius : 10;
    const autoExpand = !!opts.autoExpand;
    const expandFnName = opts.expandFnName ? String(opts.expandFnName) : "";
    const expandMax = Number.isFinite(opts.expandMax) ? Math.max(0, opts.expandMax) : 20; // 20 * 50 = 1000 rows max

    if (!input || !table) return;

    let cachedRows = [];
    let cachedHay = [];
    let matchIdxs = [];
    let matchPtr = 0;
    let lastQuery = "";
    let lastExecutedKey = "";
    let pinnedRowId = "";

    const setStatus = (txt) => {
      if (!statusEl) return;
      statusEl.textContent = txt || "";
    };

    const refreshCache = () => {
      cachedRows = getRows(table);
      cachedHay = cachedRows.map(rowHaystack);
    };

    const currentMode = () => {
      const m = (modeSel && modeSel.value) ? String(modeSel.value) : "text";
      if (m === "row" || m === "acct_last5" || m === "text") return m;
      return "text";
    };

    const applyDisabledState = () => {
      if (!activeCb) return;
      const disabled = !!activeCb.checked;
      setDisabled(input, disabled, disabled ? "Active Only is ON" : "");
      if (prevBtn) setDisabled(prevBtn, disabled);
      if (nextBtn) setDisabled(nextBtn, disabled);
      if (clearBtn) setDisabled(clearBtn, disabled);
      if (disabled) {
        // Keep status quiet when gated by Active Only
        setStatus("");
      } else if (!input.value) {
        setStatus("");
      } else {
        // will be set by search tick
      }
    };

    const goToMatch = (ptr) => {
      if (!matchIdxs.length) return;
      matchPtr = (ptr + matchIdxs.length) % matchIdxs.length;
      const centerIdx = matchIdxs[matchPtr];

      cachedRows.forEach((tr) => tr.classList.remove("rt-search-hit"));
      const tr = cachedRows[centerIdx];
      if (!tr) return;
      tr.classList.add("rt-search-hit");
      pinnedRowId = tr.id || "";

      showWindow(cachedRows, centerIdx, windowRadius);
      scrollToRow(tr);
      // Keep UI quiet on success (no extra wording).
      setStatus("");
    };

    const clearPinned = () => {
      pinnedRowId = "";
    };

    const reapplyPinned = () => {
      if (!pinnedRowId) return;
      if (activeCb && activeCb.checked) return; // gated
      refreshCache();
      const tr = pinnedRowId ? document.getElementById(pinnedRowId) : null;
      if (!tr) return;
      const idx = cachedRows.indexOf(tr);
      if (idx < 0) return;
      matchIdxs = [idx];
      matchPtr = 0;
      goToMatch(0);
    };

    const runSearch = () => {
      if (activeCb && activeCb.checked) return; // gated

      refreshCache();
      const raw = String(input.value ?? "");
      const q = normalize(raw);
      lastQuery = q;
      lastExecutedKey = `${currentMode()}::${q}`;

      if (!q) {
        matchIdxs = [];
        matchPtr = 0;
        clearWindow(cachedRows);
        setStatus("");
        clearPinned();
        return;
      }

      matchIdxs = [];
      const mode = currentMode();

      if (mode === "row") {
        const target = parseRowTarget(raw);
        if (target === null) {
          clearWindow(cachedRows);
          setStatus("Enter a row number.");
          return;
        }
        // First: match the displayed row number (# column) or excel-like row number.
        for (let i = 0; i < cachedRows.length; i++) {
          const tr = cachedRows[i];
          const disp = Number(tr?.dataset?.displayNum);
          const excel = Number(tr?.dataset?.rowNum);
          if (disp === target || excel === target) {
            matchIdxs = [i];
            break;
          }
        }
        // Fallbacks: internal index (eval-row-<index>), 1-based index, excel index (rowNum-3)
        if (!matchIdxs.length) {
          const candidates = [target, target - 1, target - 3].filter((n) => Number.isFinite(n));
          for (const idxNum of candidates) {
            const el = document.getElementById("eval-row-" + idxNum);
            if (!el) continue;
            const idx = cachedRows.indexOf(el);
            if (idx >= 0) {
              matchIdxs = [idx];
              break;
            }
          }
        }
      } else if (mode === "acct_last5") {
        const q5 = lastNDigits(raw, 5);
        if (!q5 || q5.length < 5) {
          clearWindow(cachedRows);
          setStatus("Enter last 5 digits of account.");
          return;
        }
        for (let i = 0; i < cachedHay.length; i++) {
          const hayDigits = digitsOnly(cachedHay[i]);
          if (hayDigits.includes(q5)) matchIdxs.push(i);
        }
      } else {
        for (let i = 0; i < cachedHay.length; i++) {
          if (cachedHay[i].includes(q)) matchIdxs.push(i);
        }
      }

      if (!matchIdxs.length) {
        // If pagination is hiding the row, auto-expand by invoking the page's own loader.
        if (autoExpand && expandFnName && typeof window[expandFnName] === "function") {
          // Only auto-expand for deterministic modes (row/acct_last5) to avoid runaway for free-text.
          if (mode === "row" || mode === "acct_last5") {
            let tries = 0;
            const tryExpand = () => {
              tries++;
              if (tries > expandMax) {
                clearWindow(cachedRows);
                setStatus("No matches.");
                return;
              }
              try {
                window[expandFnName](); // loads next 50 and re-renders
              } catch (_) {}
              // Wait a tick for DOM to update, then re-run search
              setTimeout(() => {
                refreshCache();
                // Re-run the same search without changing lastExecutedKey
                matchIdxs = [];
                if (mode === "row") {
                  const target = parseRowTarget(raw);
                  for (let i = 0; i < cachedRows.length; i++) {
                    const tr = cachedRows[i];
                    const disp = Number(tr?.dataset?.displayNum);
                    const excel = Number(tr?.dataset?.rowNum);
                    if (disp === target || excel === target) { matchIdxs = [i]; break; }
                  }
                } else if (mode === "acct_last5") {
                  const q5 = lastNDigits(raw, 5);
                  for (let i = 0; i < cachedHay.length; i++) {
                    const hayDigits = digitsOnly(cachedHay[i]);
                    if (hayDigits.includes(q5)) matchIdxs.push(i);
                  }
                }
                if (matchIdxs.length) {
                  goToMatch(0);
                  return;
                }
                tryExpand();
              }, 120);
            };
            tryExpand();
            return;
          }
        }

        clearWindow(cachedRows);
        setStatus("No matches.");
        clearPinned();
        return;
      }

      goToMatch(0);
    };

    let debounceT = null;
    const schedule = () => {
      if (debounceT) clearTimeout(debounceT);
      debounceT = setTimeout(runSearch, 60);
    };

    // For deterministic modes (row / last5), don't auto-run on every keystroke.
    // Enter will run the search; Escape clears.
    if (!modeSel) {
      input.addEventListener("input", schedule);
    }
    if (modeSel) modeSel.addEventListener("change", () => runSearch());
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        // If query/mode changed since last execution, run a fresh search.
        const qNow = normalize(String(input.value ?? ""));
        const keyNow = `${currentMode()}::${qNow}`;
        if (!matchIdxs.length || keyNow !== lastExecutedKey) {
          runSearch();
        } else {
          goToMatch(matchPtr + 1);
        }
      } else if (e.key === "Escape") {
        e.preventDefault();
        input.value = "";
        runSearch();
      }
    });

    if (prevBtn) prevBtn.addEventListener("click", () => matchIdxs.length && goToMatch(matchPtr - 1));
    if (nextBtn) nextBtn.addEventListener("click", () => matchIdxs.length && goToMatch(matchPtr + 1));
    if (clearBtn)
      clearBtn.addEventListener("click", () => {
        input.value = "";
        runSearch();
        input.focus();
      });

    if (activeCb) activeCb.addEventListener("change", () => {
      applyDisabledState();
      if (!activeCb.checked) {
        // re-run whatever query was typed while disabled
        if (normalize(input.value) !== lastQuery) runSearch();
        else reapplyPinned();
      } else {
        // when we enable active-only, restore full table
        refreshCache();
        clearWindow(cachedRows);
        clearPinned();
      }
    });

    // Expose an imperative refresh hook (useful for tables populated via JS).
    input.dataset.rtRefresh = "1";
    input.rtRefresh = () => {
      // If user has an active pinned match, keep it pinned across re-renders.
      if (pinnedRowId) reapplyPinned();
      else runSearch();
    };

    // Re-apply highlight after any table body changes (pagination/refresh re-renders).
    try {
      const tbody = table.tBodies && table.tBodies[0] ? table.tBodies[0] : table.querySelector("tbody");
      if (tbody && window.MutationObserver) {
        let moT = null;
        const mo = new MutationObserver(() => {
          if (!pinnedRowId) return;
          if (moT) clearTimeout(moT);
          moT = setTimeout(() => reapplyPinned(), 80);
        });
        mo.observe(tbody, { childList: true, subtree: true });
      }
    } catch (_) {}

    applyDisabledState();
    // Initial cache and clear state
    refreshCache();
    runSearch();
  }

  window.initRealtimeTableSearch = initRealtimeTableSearch;
})();

