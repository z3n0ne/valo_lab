/* VALO//LAB — local dashboard front-end (no build step, no dependencies). */
(function () {
  "use strict";

  const TABS = ["overview", "agents", "maps", "sides", "matches"];
  const RELIABILITY_LABEL = { high: "Fiabilité élevée", medium: "Fiabilité moyenne", low: "Fiabilité faible" };
  const DAY_OPTIONS = [
    { value: 30, label: "30 j" },
    { value: 90, label: "90 j" },
    { value: 180, label: "6 mois" },
    { value: 0, label: "Tout" },
  ];

  const state = {
    boot: null,
    stats: null,
    tab: "overview",
    mode: localStorage.getItem("valo.mode.v2") || "",
    days: Number(localStorage.getItem("valo.days") || 90),
    sort: {
      agents: { key: "impact", dir: -1 },
      maps: { key: "impact", dir: -1 },
    },
    search: "",
    openMap: null,
    pollTimer: null,
    toastTimer: null,
  };

  const app = document.getElementById("app");
  const noticeStack = document.getElementById("notice-stack");
  const dialog = document.getElementById("settings-dialog");
  const toastEl = document.getElementById("toast");

  /* ------------------------------------------------------------------ utils */
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  const NF = new Intl.NumberFormat("fr-FR");

  function fmtInt(value) {
    return NF.format(Math.round(Number(value) || 0));
  }

  function fmt1(value) {
    return (Number(value) || 0).toFixed(1).replace(".", ",");
  }

  function fmt2(value) {
    return (Number(value) || 0).toFixed(2).replace(".", ",");
  }

  function pct(value, digits) {
    const n = Number(value) || 0;
    return n.toFixed(digits == null ? 0 : digits).replace(".", ",") + " %";
  }

  function signed(value) {
    const n = Math.round(Number(value) || 0);
    return (n > 0 ? "+" : "") + n;
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function initials(name) {
    return String(name || "?")
      .replace(/[^\p{L}\p{N} ]/gu, "")
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map(function (part) { return part[0]; })
      .join("")
      .toUpperCase() || "?";
  }

  function isUuid(value) {
    return typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
  }

  function mediaUrl(kind, id) {
    if (!isUuid(id)) return null;
    if (kind === "agent") return "https://media.valorant-api.com/agents/" + id + "/displayicon.png";
    if (kind === "map") return "https://media.valorant-api.com/maps/" + id + "/listviewicon.png";
    if (kind === "card") return "https://media.valorant-api.com/playercards/" + id + "/wideart.png";
    return null;
  }

  function agentAvatar(id, name, size) {
    const url = mediaUrl("agent", id);
    return (
      '<span class="agent-avatar ' + (size || "") + '">' +
      esc(initials(name)) +
      (url ? '<img src="' + esc(url) + '" alt="" loading="lazy" onerror="this.remove()">' : "") +
      "</span>"
    );
  }

  function mapThumb(id, name) {
    const url = mediaUrl("map", id);
    return (
      '<span class="map-thumb">' +
      (url ? '<img src="' + esc(url) + '" alt="" loading="lazy" onerror="this.remove()">' : "") +
      '<span>' + esc(initials(name)) + "</span>" +
      "</span>"
    );
  }

  function relativeTime(iso) {
    if (!iso) return "jamais";
    const then = new Date(iso).getTime();
    if (!then || Number.isNaN(then)) return "—";
    const diff = Math.max(0, Date.now() - then);
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "à l'instant";
    if (mins < 60) return "il y a " + mins + " min";
    const hours = Math.floor(mins / 60);
    if (hours < 24) return "il y a " + hours + " h";
    const days = Math.floor(hours / 24);
    if (days < 30) return "il y a " + days + " j";
    return new Date(iso).toLocaleDateString("fr-FR");
  }

  function dateShort(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "—";
    return d.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" });
  }

  function impactChip(impact) {
    const delta = Math.round((Number(impact) || 100) - 100);
    const cls = delta >= 3 ? "good" : delta <= -3 ? "bad" : "neutral";
    return '<span class="chip ' + cls + '" title="Indice de performance (base 100)">' + signed(delta) + "</span>";
  }

  function reliability(level, sample, unit) {
    const dots = [0, 1, 2]
      .map(function (i) {
        const on = (level === "high" && i < 3) || (level === "medium" && i < 2) || (level === "low" && i < 1);
        return '<i class="' + (on ? "on" : "") + '"></i>';
      })
      .join("");
    return (
      '<span class="reliability" data-level="' + esc(level) + '">' +
      '<span class="reliability-dots">' + dots + "</span>" +
      RELIABILITY_LABEL[level] + " · " + fmtInt(sample) + " " + (unit || "parties") +
      "</span>"
    );
  }

  function queueLabel(q) {
    if (!q) return "—";
    const known = {
      competitive: "Competitive",
      unrated: "Unrated",
      swiftplay: "Swiftplay",
      spikerush: "Spike Rush",
      deathmatch: "Deathmatch",
      teamdeathmatch: "Team Deathmatch",
      custom: "Custom",
      premier: "Premier",
    };
    const key = String(q).toLowerCase();
    if (known[key]) return known[key];
    return String(q).charAt(0).toUpperCase() + String(q).slice(1);
  }

  function resultClass(match) {
    if (match.draw) return "draw";
    return match.won ? "win" : "loss";
  }

  function resultLetter(match) {
    if (match.draw) return "N";
    return match.won ? "V" : "D";
  }

  function average(list) {
    if (!list || !list.length) return 0;
    return list.reduce(function (sum, value) { return sum + (Number(value) || 0); }, 0) / list.length;
  }

  /* --------------------------------------------------------------- fetching */
  async function fetchJSON(url, options) {
    const opts = Object.assign({ headers: {} }, options || {});
    if (opts.body && !opts.headers["Content-Type"]) {
      opts.headers["Content-Type"] = "application/json";
    }
    const response = await fetch(url, opts);
    let data = null;
    try {
      data = await response.json();
    } catch (err) {
      data = null;
    }
    if (!response.ok) {
      const error = new Error((data && data.error) || "Erreur HTTP " + response.status);
      error.status = response.status;
      error.data = data;
      throw error;
    }
    return data;
  }

  function showToast(message, kind) {
    if (!toastEl) return;
    toastEl.textContent = message;
    toastEl.className = "toast show " + (kind || "");
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(function () {
      toastEl.className = "toast " + (kind || "");
    }, 4200);
  }

  /* --------------------------------------------------------------- bootstrap */
  async function init() {
    const hashTab = location.hash.replace("#", "");
    if (TABS.indexOf(hashTab) >= 0) state.tab = hashTab;
    if (["30", "90", "180", "0"].indexOf(String(state.days)) < 0) state.days = 90;
    bindChrome();
    await reloadAll(true);
    if (state.boot && state.boot.sync && state.boot.sync.state === "running") pollSync();
  }

  async function reloadAll(initial) {
    try {
      const boot = await fetchJSON("/api/bootstrap");
      state.boot = boot;
      const preferred = boot.config && boot.config.queue_mode === "competitive" ? "competitive" : "tactical";
      if (!state.mode) state.mode = preferred;
      if (!modeExists(state.mode) && state.mode !== preferred) state.mode = preferred;
      if (preferred !== "competitive" && !modeExists(state.mode)) state.mode = "tactical";
      localStorage.setItem("valo.mode.v2", state.mode);
      state.stats = await fetchJSON("/api/stats?mode=" + encodeURIComponent(state.mode) + "&days=" + state.days);
      renderAll();
      if (initial && !boot.configured && !boot.demo) {
        setTimeout(openSettings, 500);
      }
    } catch (err) {
      app.innerHTML =
        '<div class="empty-state"><div class="empty-inner">' +
        '<p class="eyebrow">Erreur</p><h2>Dashboard indisponible</h2>' +
        "<p>" + esc(err.message) + "</p>" +
        '<div class="empty-actions"><button class="btn btn-primary" data-action="retry">Réessayer</button></div>' +
        "</div></div>";
      showToast(err.message, "err");
    }
  }

  async function reloadStats() {
    try {
      state.stats = await fetchJSON("/api/stats?mode=" + encodeURIComponent(state.mode) + "&days=" + state.days);
      renderAll();
    } catch (err) {
      showToast(err.message, "err");
    }
  }

  function modeExists(mode) {
    if (mode === "tactical" || mode === "all") return true;
    if (!state.boot || !state.boot.filters) return true;
    return state.boot.filters.queues.some(function (q) { return q.id === mode; });
  }

  /* --------------------------------------------------------------- chrome */
  function bindChrome() {
    $$(".tab").forEach(function (btn) {
      btn.addEventListener("click", function () {
        goTab(btn.dataset.tab);
      });
    });

    window.addEventListener("hashchange", function () {
      const tab = location.hash.replace("#", "");
      if (TABS.indexOf(tab) >= 0 && tab !== state.tab) {
        state.tab = tab;
        updateTabs();
        renderView();
      }
    });

    $("#sync-btn").addEventListener("click", function () {
      startSync(false);
    });

    $("#settings-btn").addEventListener("click", openSettings);
    $("#settings-close").addEventListener("click", function () { dialog.close(); });
    dialog.addEventListener("click", function (event) {
      if (event.target === dialog) dialog.close();
    });

    $("#toggle-key").addEventListener("click", function () {
      const input = $("#field-key");
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      this.textContent = show ? "Masquer" : "Afficher";
    });

    $("#settings-form").addEventListener("submit", function (event) {
      event.preventDefault();
      saveSettings(false);
    });
    $("#save-sync-btn").addEventListener("click", function () { saveSettings(true); });
    $("#test-btn").addEventListener("click", testConnection);
    $("#clear-demo-btn").addEventListener("click", clearDemo);
    $("#full-sync-btn").addEventListener("click", function () {
      if (!state.boot || !state.boot.configured) {
        settingsFeedback("Configure d'abord ton Riot ID et ta clé API.", "err");
        return;
      }
      dialog.close();
      startSync(true);
    });

    app.addEventListener("click", onAppClick);
    app.addEventListener("keydown", function (event) {
      const el = event.target.closest('[data-map-toggle][role="button"]');
      if (!el) return;
      if (event.key === "Enter" || event.key === " " || event.key === "Spacebar") {
        event.preventDefault();
        toggleMap(el.dataset.mapToggle);
      }
    });
    app.addEventListener("input", function (event) {
      if (event.target && event.target.id === "matches-search") {
        state.search = event.target.value;
        refreshMatchesTable();
      }
    });
    noticeStack.addEventListener("click", onAppClick);
    document.addEventListener("click", function (event) {
      const actionEl = event.target.closest("[data-action]");
      if (!actionEl) return;
      const action = actionEl.dataset.action;
      if (action === "open-settings") openSettings();
      if (action === "seed-demo") seedDemo();
      if (action === "clear-demo") clearDemo();
      if (action === "sync") startSync(false);
      if (action === "retry") reloadAll(true);
      if (action === "reload-stats") reloadStats();
    });
  }

  function goTab(tab) {
    if (TABS.indexOf(tab) < 0) tab = "overview";
    state.tab = tab;
    if (location.hash !== "#" + tab) history.replaceState(null, "", "#" + tab);
    updateTabs();
    renderView();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function updateTabs() {
    $$(".tab").forEach(function (btn) {
      btn.classList.toggle("is-active", btn.dataset.tab === state.tab);
    });
  }

  /* ----------------------------------------------------------------- render */
  function renderAll() {
    updateTabs();
    renderNotices();
    renderSyncUI();
    renderView();
    updateSettingsSummary();
  }

  function renderView() {
    if (!state.stats) {
      app.innerHTML = '<div class="loading-screen"><div class="loader"></div><p>Chargement…</p></div>';
      return;
    }
    const renderers = {
      overview: renderOverview,
      agents: renderAgents,
      maps: renderMaps,
      sides: renderSides,
      matches: renderMatches,
    };
    const body = (renderers[state.tab] || renderOverview)();
    app.innerHTML = '<div class="view">' + renderFilterbar() + body + "</div>";
  }

  function hasData() {
    return !!(state.stats && state.stats.meta && state.stats.meta.has_data && state.stats.summary.matches > 0);
  }

  function renderFilterbar() {
    const stats = state.stats;
    const summary = stats ? stats.summary : { matches: 0, rounds: 0 };
    const queues = (state.boot && state.boot.filters && state.boot.filters.queues) || [];
    const queueMode = (state.boot && state.boot.config && state.boot.config.queue_mode) || "tactical";
    let options = '<option value="tactical"' + (state.mode === "tactical" ? " selected" : "") + ">Modes tactiques</option>";
    options += '<option value="all"' + (state.mode === "all" ? " selected" : "") + ">Toutes les parties</option>";
    if (queueMode === "competitive" && !queues.some(function (q) { return q.id === "competitive"; })) {
      options += '<option value="competitive"' + (state.mode === "competitive" ? " selected" : "") + ">Competitive (0)</option>";
    }
    queues.forEach(function (q) {
      if (!q.id || q.id === "unknown") return;
      options +=
        '<option value="' + esc(q.id) + '"' + (state.mode === q.id ? " selected" : "") + ">" +
        esc(queueLabel(q.name || q.id)) + " (" + q.count + ")</option>";
    });
    const periods = DAY_OPTIONS.map(function (opt) {
      return (
        '<button type="button" data-days="' + opt.value + '" class="' + (state.days === opt.value ? "is-active" : "") + '">' +
        opt.label + "</button>"
      );
    }).join("");

    return (
      '<div class="filterbar">' +
      '<div class="filter-group"><span class="filter-label">Mode</span>' +
      '<select class="select" id="mode-select" aria-label="Filtrer par mode">' + options + "</select></div>" +
      '<div class="filter-group"><span class="filter-label">Période</span>' +
      '<div class="segmented" id="period-segmented">' + periods + "</div></div>" +
      '<div class="filter-meta">' +
      "<span><b>" + fmtInt(summary.matches) + "</b> parties</span>" +
      "<span><b>" + fmtInt(summary.rounds) + "</b> rounds</span>" +
      (stats && stats.meta.demo ? '<span class="chip amber">Démo</span>' : "") +
      (state.boot && state.boot.sync && state.boot.sync.last_sync
        ? "<span>Sync " + esc(relativeTime(state.boot.sync.last_sync)) + "</span>"
        : "<span>Jamais synchronisé</span>") +
      "</div></div>"
    );
  }

  function bindFilterEvents() {
    const select = document.getElementById("mode-select");
    if (select) {
      select.addEventListener("change", function () {
        state.mode = this.value;
        localStorage.setItem("valo.mode.v2", state.mode);
        reloadStats();
      });
    }
    const segmented = document.getElementById("period-segmented");
    if (segmented) {
      segmented.addEventListener("click", function (event) {
        const btn = event.target.closest("[data-days]");
        if (!btn) return;
        state.days = Number(btn.dataset.days);
        localStorage.setItem("valo.days", String(state.days));
        $$("[data-days]", segmented).forEach(function (b) {
          b.classList.toggle("is-active", Number(b.dataset.days) === state.days);
        });
        reloadStats();
      });
    }
  }

  // Re-bind filter controls after every innerHTML swap.
  const originalRenderView = renderView;
  renderView = function () {
    originalRenderView();
    bindFilterEvents();
  };

  function emptyState() {
    const configured = state.boot && state.boot.configured;
    const demoDismissed = state.boot && state.boot.demo_dismissed;
    let title = "Connecte ton compte Riot";
    let text = "Ajoute ton Riot ID (Pseudo#TAG) et une clé API HenrikDev gratuite pour importer tes parties automatiquement.";
    let actions =
      '<button class="btn btn-primary" data-action="open-settings">Configurer mon compte</button>' +
      (demoDismissed ? '<button class="btn btn-ghost" data-action="seed-demo">Charger la démo</button>' : "");
    if (configured) {
      title = "Aucune partie sur cette période";
      text = "Élargis la période, change de mode, ou lance une synchronisation pour récupérer tes parties récentes.";
      actions =
        '<button class="btn btn-primary" data-action="sync">Synchroniser</button>' +
        '<button class="btn btn-ghost" data-action="open-settings">Réglages</button>' +
        '<button class="btn btn-ghost" data-action="reload-stats">Actualiser</button>';
    }
    return (
      '<div class="empty-state"><div class="empty-inner">' +
      '<p class="eyebrow">Aucune donnée</p><h2>' + esc(title) + "</h2><p>" + esc(text) + "</p>" +
      '<div class="empty-actions">' + actions + "</div></div></div>"
    );
  }

  /* --------------------------------------------------------------- overview */
  function renderOverview() {
    if (!hasData()) return emptyState();
    const s = state.stats.summary;
    const profile = profileInfo();
    const lastSync = state.boot && state.boot.sync ? state.boot.sync.last_sync : null;
    const cardArt = mediaUrl("card", profile.card);
    const heroArt = cardArt || "/static/logo.png";
    const rank = rankBadge(profile);

    const kpi = [
      kpiCard("Win rate", pct(s.win_rate, 1), s.wins + " V · " + s.losses + " D" + (s.draws ? " · " + s.draws + " N" : ""), s.win_rate >= 50 ? "positive" : "negative"),
      kpiCard("K/D", fmt2(s.kd), "KDA " + fmt2(s.kda) + " · " + fmtInt(s.kills) + " kills", s.kd >= 1.1 ? "positive" : s.kd < 0.95 ? "negative" : ""),
      kpiCard("ACS", fmtInt(s.acs), "score de combat / round", "accent"),
      kpiCard("ADR", fmtInt(s.adr), "dégâts infligés / round", ""),
      kpiCard("Headshot", pct(s.hs_pct, 1), "tirs à la tête", ""),
      kpiCard("Rounds", fmtInt(s.rounds), "ATK " + pct(s.attack.round_win_rate) + " · DEF " + pct(s.defense.round_win_rate), ""),
    ].join("");

    const insights = renderInsights();
    const atk = s.attack;
    const dfn = s.defense;
    const verdict = sideVerdict(atk, dfn);

    return (
      '<section class="hero' + (cardArt ? "" : " hero-logo-card") + '" style="--hero-art:url(\'' + esc(heroArt) + '\')">' +
      '<div class="hero-main">' +
      '<p class="eyebrow">Rapport de performance · ' + esc(modeText()) + "</p>" +
      "<h1>" + esc(profile.name || "Joueur") +
      '<span class="tag">#' + esc(profile.tag || "----") + "</span></h1>" +
      '<div class="hero-meta">' + rank +
      '<span class="meta-divider"></span><span>' + esc((profile.region || "eu").toUpperCase()) + " · " + esc((profile.platform || "pc").toUpperCase()) + "</span>" +
      '<span class="meta-divider"></span><span>' + (state.stats.meta.demo && !lastSync ? "Données de démonstration" : "Dernière sync " + esc(relativeTime(lastSync))) + "</span>" +
      "</div></div>" +
      '<div class="hero-side">' +
      heroStat(pct(s.win_rate, 0), "Win rate") +
      heroStat(fmtInt(s.acs), "ACS") +
      heroStat(fmt2(s.kd), "K/D") +
      heroStat(fmtInt(s.matches), "Parties") +
      "</div></section>" +
      '<div class="kpi-grid">' + kpi + "</div>" +

      '<section class="section"><div class="section-head"><div><p class="eyebrow">Lecture automatique</p><h2>Forces &amp; faiblesses</h2></div>' +
      '<div class="section-note">Comparé à <b>ta moyenne</b> sur la période</div></div>' + insights + "</section>" +

      '<section class="section"><div class="section-head"><div><p class="eyebrow">Régularité</p><h2>Tendance</h2></div>' +
      '<div class="section-note">ACS par partie · moyenne <b>' + fmtInt(s.acs) + "</b></div></div>" +
      '<div class="panel"><div class="trend-wrap">' + trendChart(state.stats.trend) + "</div>" +
      '<div class="trend-legend"><span><i class="dot win"></i>Victoire</span><span><i class="dot loss"></i>Défaite</span><span><i class="dot draw"></i>Nul</span>' +
      '<span class="spacer"></span><span>Les <b>10 dernières</b> : ACS ' + fmtInt(average(state.stats.trend.slice(-10).map(function (t) { return t.acs; }))) + "</span></div></div></section>" +

      '<section class="section"><div class="section-head"><div><p class="eyebrow">Par agent &amp; par map</p><h2>Où tu performes</h2></div>' +
      '<div class="section-note">Barres ACS · repère = ta moyenne</div></div><div class="charts-two">' +
      '<div class="panel"><div class="panel-head"><h3>Agents</h3><p>ACS et indice de performance</p></div><div class="panel-body">' + agentBars(state.stats.agents) + "</div></div>" +
      '<div class="panel"><div class="panel-head"><h3>Maps</h3><p>Win rate · repère 50 %</p></div><div class="panel-body map-bars">' + mapBars(state.stats.maps) + "</div></div>" +
      "</div></section>" +

      '<section class="section"><div class="section-head"><div><p class="eyebrow">Splits de round</p><h2>Attaque / Défense</h2></div>' +
      '<div class="section-note">Basé sur <b>' + fmtInt(atk.rounds + dfn.rounds) + "</b> rounds</div></div>" +
      '<div class="side-grid">' + sideCard("attack", atk) + sideCard("defense", dfn) + "</div>" +
      (verdict ? '<div class="side-verdict"><span class="verdict-mark"></span><div>' + verdict + "</div></div>" : "") +
      "</section>" +

      '<section class="section"><div class="section-head"><div><p class="eyebrow">Dernières parties</p><h2>Matchs récents</h2></div>' +
      '<div class="section-note"><button class="btn btn-ghost btn-small" data-action="all-matches">Voir tout</button></div></div>' +
      '<div class="panel">' + matchesTable(state.stats.recent.slice(0, 10), false) + "</div></section>"
    );
  }

  function profileInfo() {
    const p = (state.boot && state.boot.profile) || (state.stats && state.stats.profile) || {};
    const cfg = (state.boot && state.boot.config) || {};
    return {
      name: p.name || cfg.riot_name || "Joueur",
      tag: p.tag || cfg.riot_tag || "----",
      region: p.region || cfg.region || "eu",
      platform: cfg.platform || "pc",
      rank: p.rank || "",
      rr: p.rr,
      peak: p.peak || "",
      card: p.card || "",
      level: p.level || 0,
      demo: !!p.demo,
    };
  }

  function rankBadge(profile) {
    if (!profile.rank) return '<span class="rank-badge is-unranked">Non classé</span>';
    const rr = profile.rr != null ? '<span class="rr">' + fmtInt(profile.rr) + " RR</span>" : "";
    return '<span class="rank-badge" title="' + esc(profile.peak ? "Peak : " + profile.peak : "Rang actuel") + '">' + esc(profile.rank) + " " + rr + "</span>";
  }

  function heroStat(value, label) {
    return '<div class="hero-stat"><span class="value">' + value + '</span><span class="label">' + esc(label) + "</span></div>";
  }

  function kpiCard(label, value, sub, tone) {
    return (
      '<div class="kpi ' + (tone ? "is-" + tone : "") + '">' +
      '<span class="kpi-label">' + esc(label) + "</span>" +
      '<span class="kpi-value">' + value + "</span>" +
      '<div class="kpi-sub">' + sub + "</div></div>"
    );
  }

  function renderInsights() {
    const list = (state.stats.insights || []).slice(0, 6);
    if (!list.length) return '<div class="panel"><div class="panel-body">Pas encore assez de données.</div></div>';
    return (
      '<div class="insights-grid">' +
      list.map(function (item) {
        const unit = item.tag === "CÔTÉ" || item.tag === "OUVERTURE" ? "rounds" : "parties";
        return (
          '<article class="insight ' + esc(item.kind) + '">' +
          '<div class="insight-top"><span class="insight-tag">' + esc(item.tag) + "</span>" +
          '<span class="chip ' + (item.kind === "strength" ? "good" : item.kind === "weakness" ? "bad" : "blue") + '">' +
          (item.kind === "strength" ? "Force" : item.kind === "weakness" ? "À travailler" : "Info") + "</span></div>" +
          "<h3>" + esc(item.title) + "</h3><p>" + esc(item.detail) + "</p>" +
          '<div class="insight-foot">' + reliability(item.confidence, item.sample, unit) + "</div></article>"
        );
      }).join("") +
      "</div>"
    );
  }

  function modeText() {
    if (state.mode === "tactical") return "Modes tactiques";
    if (state.mode === "all") return "Toutes les parties";
    return queueLabel(state.mode);
  }

  function updateSettingsSummary() {
    const summary = document.getElementById("data-summary");
    if (!summary || !state.boot) return;
    const counts = state.boot.counts || {};
    const last = state.boot.sync ? state.boot.sync.last_sync : null;
    summary.textContent =
      fmtInt(counts.real || 0) + " parties réelles · " + fmtInt(counts.demo || 0) + " parties de démo · " +
      "dernière sync " + relativeTime(last) + ".";
    const clearBtn = document.getElementById("clear-demo-btn");
    if (clearBtn) clearBtn.style.display = state.boot.demo ? "" : "none";
    const fullBtn = document.getElementById("full-sync-btn");
    if (fullBtn) fullBtn.disabled = !state.boot.configured;
  }

  /* ----------------------------------------------------------------- charts */
  function trendChart(trend) {
    if (!trend || trend.length < 2) {
      return '<div class="chart-empty">Pas assez de parties pour afficher une tendance.</div>';
    }
    const width = 960;
    const height = 250;
    const pad = { l: 40, r: 16, t: 20, b: 28 };
    const values = trend.map(function (t) { return Number(t.acs) || 0; });
    let min = Math.min.apply(null, values);
    let max = Math.max.apply(null, values);
    const spread = Math.max(25, max - min);
    min = Math.max(0, min - spread * 0.28);
    max = max + spread * 0.28;
    const x = function (i) { return pad.l + (i / (trend.length - 1)) * (width - pad.l - pad.r); };
    const y = function (v) { return pad.t + (1 - (v - min) / (max - min)) * (height - pad.t - pad.b); };
    const avg = average(values);

    let grid = "";
    for (let i = 0; i <= 4; i++) {
      const value = min + ((max - min) * i) / 4;
      const yy = y(value);
      grid +=
        '<line x1="' + pad.l + '" y1="' + yy.toFixed(1) + '" x2="' + (width - pad.r) + '" y2="' + yy.toFixed(1) + '" stroke="rgba(255,255,255,0.055)" stroke-width="1"/>' +
        '<text x="' + (pad.l - 8) + '" y="' + (yy + 3).toFixed(1) + '" fill="#617384" font-size="9" text-anchor="end" font-family="Barlow, sans-serif">' + Math.round(value) + "</text>";
    }

    let path = "";
    trend.forEach(function (t, i) {
      path += (i === 0 ? "M" : "L") + x(i).toFixed(1) + "," + y(t.acs).toFixed(1) + " ";
    });
    const area = path + "L" + x(trend.length - 1).toFixed(1) + "," + (height - pad.b) + " L" + x(0).toFixed(1) + "," + (height - pad.b) + " Z";

    const dots = trend.map(function (t, i) {
      const color = t.draw ? "#8798a9" : t.won ? "#3ddc97" : "#ff5b64";
      return (
        '<circle cx="' + x(i).toFixed(1) + '" cy="' + y(t.acs).toFixed(1) + '" r="3.1" fill="' + color + '" stroke="#0d151e" stroke-width="1">' +
        "<title>" + esc(t.label + " · " + t.agent + " sur " + t.map + " · " + t.score + " · ACS " + Math.round(t.acs)) + "</title></circle>"
      );
    }).join("");

    const labelIndices = [0, Math.floor((trend.length - 1) / 2), trend.length - 1];
    const labels = labelIndices.map(function (i) {
      return '<text x="' + x(i).toFixed(1) + '" y="' + (height - 8) + '" fill="#617384" font-size="9" text-anchor="' + (i === 0 ? "start" : i === trend.length - 1 ? "end" : "middle") + '" font-family="Barlow, sans-serif">' + esc(trend[i].label) + "</text>";
    }).join("");

    return (
      '<svg class="trend-svg" viewBox="0 0 ' + width + " " + height + '" role="img" aria-label="Évolution de l\'ACS par partie">' +
      '<defs><linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0%" stop-color="#ff4655" stop-opacity="0.26"/><stop offset="100%" stop-color="#ff4655" stop-opacity="0"/>' +
      "</linearGradient></defs>" +
      grid +
      '<line x1="' + pad.l + '" y1="' + y(avg).toFixed(1) + '" x2="' + (width - pad.r) + '" y2="' + y(avg).toFixed(1) + '" stroke="rgba(236,232,225,0.28)" stroke-width="1" stroke-dasharray="4 4"/>' +
      '<text x="' + (width - pad.r) + '" y="' + (y(avg) - 5).toFixed(1) + '" fill="#8798a9" font-size="9" text-anchor="end" font-family="Barlow, sans-serif">moy. ' + Math.round(avg) + "</text>" +
      '<path d="' + area + '" fill="url(#trendFill)"/>' +
      '<path d="' + path + '" fill="none" stroke="#ff4655" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/>' +
      dots + labels + "</svg>"
    );
  }

  function agentBars(agents) {
    if (!agents || !agents.length) return '<div class="chart-empty">Aucune partie par agent.</div>';
    const list = agents.slice(0, 6);
    const max = Math.max.apply(null, list.map(function (a) { return a.acs; }).concat([1]));
    const baseline = clamp((state.stats.summary.acs / max) * 100, 0, 100);
    return '<div class="bars">' + list.map(function (a) {
      const width = clamp((a.acs / max) * 100, 1, 100);
      const tone = a.impact >= 103 ? "good" : a.impact <= 97 ? "bad" : "neutral";
      return (
        '<div class="bar-row">' +
        '<div class="bar-label">' + agentAvatar(a.id, a.name) +
        '<span><span class="name">' + esc(a.name) + '</span><span class="count"> · ' + a.matches + " parties</span></span></div>" +
        '<div class="bar-track"><span class="bar-fill ' + tone + '" style="width:' + width.toFixed(1) + '%"></span>' +
        '<span class="bar-baseline" style="left:' + baseline.toFixed(1) + '%"></span></div>' +
        '<div class="bar-value">' + fmtInt(a.acs) + "</div>" +
        '<div style="text-align:right">' + impactChip(a.impact) + "</div></div>"
      );
    }).join("") + "</div>";
  }

  function mapBars(maps) {
    if (!maps || !maps.length) return '<div class="chart-empty">Aucune partie par map.</div>';
    return '<div class="bars">' + maps.map(function (m) {
      const wr = m.win_rate;
      const tone = wr >= 52 ? "good" : wr <= 47 ? "bad" : "neutral";
      return (
        '<div class="bar-row">' +
        '<div class="bar-label"><span class="name">' + esc(m.name) + '</span><span class="count"> · ' + m.matches + "</span></div>" +
        '<div class="bar-track"><span class="bar-fill ' + tone + '" style="width:' + clamp(wr, 1, 100).toFixed(1) + '%"></span>' +
        '<span class="bar-baseline" style="left:50%"></span></div>' +
        '<div class="bar-value">' + pct(wr) + "</div>" +
        '<div style="text-align:right">' + impactChip(m.impact) + "</div></div>"
      );
    }).join("") + "</div>";
  }

  /* ------------------------------------------------------------------- sides */
  function sideCard(kind, side) {
    const isAtk = kind === "attack";
    const circumference = 2 * Math.PI * 52;
    const offset = circumference * (1 - clamp(side.round_win_rate, 0, 100) / 100);
    const lost = Math.max(0, side.rounds - side.wins);
    return (
      '<div class="panel side-card ' + kind + '">' +
      '<div class="side-top"><div class="ring"><svg viewBox="0 0 116 116" aria-hidden="true">' +
      '<circle class="track" cx="58" cy="58" r="52"/>' +
      '<circle class="value" cx="58" cy="58" r="52" stroke-dasharray="' + circumference.toFixed(2) + '" stroke-dashoffset="' + offset.toFixed(2) + '"/>' +
      "</svg><div class=\"ring-center\"><b>" + pct(side.round_win_rate) + '</b><span>rounds gagnés</span></div></div>' +
      '<div class="side-title"><p class="eyebrow">' + (isAtk ? "Côté attaque" : "Côté défense") + "</p>" +
      "<h3>" + (isAtk ? "Attaque" : "Défense") + "</h3>" +
      "<p>" + fmtInt(side.wins) + " rounds gagnés · " + fmtInt(lost) + " perdus</p></div></div>" +
      '<div class="side-stats">' +
      sideStat(fmt2(side.kd), "K/D") +
      sideStat(fmtInt(side.acs), "ACS") +
      sideStat(fmtInt(side.adr), "ADR") +
      sideStat(pct(side.first_blood_pct), "Ouverture") +
      "</div></div>"
    );
  }

  function sideStat(value, label) {
    return '<div class="side-stat"><span class="v">' + value + '</span><span class="k">' + esc(label) + "</span></div>";
  }

  function sideVerdict(atk, dfn) {
    const insight = (state.stats.insights || []).find(function (i) { return i.tag === "CÔTÉ"; });
    if (insight) {
      return "<strong>" + esc(insight.title) + ".</strong> " + esc(insight.detail);
    }
    if (!atk.rounds && !dfn.rounds) return "";
    const gap = atk.round_win_rate - dfn.round_win_rate;
    if (Math.abs(gap) < 3) {
      return "<strong>Tes deux côtés sont équilibrés.</strong> Continue à travailler les mêmes fondamentaux des deux côtés.";
    }
    const weak = gap > 0 ? "défense" : "attaque";
    const strong = gap > 0 ? "attaque" : "défense";
    return "<strong>Ton côté " + weak + " est le plus fragile.</strong> Tu gagnes " + pct(Math.abs(gap)) + " de rounds en moins qu'en " + strong + ".";
  }

  /* ------------------------------------------------------------------ agents */
  function renderAgents() {
    if (!hasData()) return emptyState();
    const agents = state.stats.agents;
    const candidates = agents.filter(function (a) { return a.matches >= 3; });
    const pool = candidates.length ? candidates : agents;
    const best = pool.slice().sort(function (a, b) { return b.impact - a.impact; })[0];
    const worst = pool.slice().sort(function (a, b) { return a.impact - b.impact; })[0];
    const volume = pool.slice().sort(function (a, b) { return b.acs - a.acs; })[0];
    const cards = [];
    if (best) cards.push(spotlight("best", "Meilleur indice", best, "Force"));
    if (volume && (!best || volume.id !== best.id)) cards.push(spotlight("volume", "Meilleur volume", volume, "ACS"));
    if (worst && best && worst.id !== best.id) cards.push(spotlight("worst", "À travailler", worst, "Priorité"));

    return (
      '<div class="spotlight-grid">' + cards.slice(0, 3).join("") + "</div>" +
      '<div class="panel"><div class="panel-head"><h3>Détail par agent</h3>' +
      '<p>Indice = 45 % ACS + 30 % K/D + 25 % win rate · base 100</p></div>' +
      '<div class="table-wrap">' + agentsTable(agents) + "</div>" +
      '<div class="table-foot"><span>Clique sur un en-tête pour trier.</span><span>ATK / DEF = win rate de round par côté.</span><span class="only-mobile">Glisse pour voir toutes les colonnes.</span></div></div>'
    );
  }

  function spotlight(kind, kicker, agent, badge) {
    return (
      '<article class="spotlight ' + kind + '">' + agentAvatar(agent.id, agent.name, "lg") +
      '<div class="spot-body"><div class="spot-kicker"><span class="marker"></span>' + esc(kicker) + "</div>" +
      "<h3>" + esc(agent.name) + "</h3>" +
      '<div class="spot-stats"><span><b>' + pct(agent.win_rate) + "</b> WR</span>" +
      "<span><b>" + fmt2(agent.kd) + "</b> K/D</span>" +
      "<span><b>" + fmtInt(agent.acs) + "</b> ACS</span></div>" +
      '<div class="spot-stats" style="margin-top:5px"><span>' + agent.matches + " parties</span>" +
      '<span class="chip ' + (agent.impact >= 100 ? "good" : "bad") + '">' + esc(badge) + " " + signed(agent.impact - 100) + "</span></div>" +
      "</div></article>"
    );
  }

  function agentsTable(agents) {
    const sort = state.sort.agents;
    const rows = agents.slice().sort(function (a, b) {
      return compare(a, b, sort.key, sort.dir, agentSortValue);
    });
    return (
      '<table class="data"><thead><tr>' +
      th("Agent", "name", "agents") +
      th("Parties", "matches", "agents", "num") +
      th("WR", "win_rate", "agents", "num") +
      th("K/D", "kd", "agents", "num") +
      th("KDA", "kda", "agents", "num") +
      th("ACS", "acs", "agents", "num") +
      th("ADR", "adr", "agents", "num") +
      th("HS %", "hs_pct", "agents", "num") +
      th("ATK WR", "atk_wr", "agents", "num") +
      th("DEF WR", "def_wr", "agents", "num") +
      th("Indice", "impact", "agents", "num") +
      "</tr></thead><tbody>" +
      rows.map(function (a) {
        return (
          "<tr>" +
          '<td><div class="agent-cell">' + agentAvatar(a.id, a.name) +
          '<span><span class="strong">' + esc(a.name) + "</span></span></div></td>" +
          '<td class="num muted">' + a.matches + "</td>" +
          '<td class="num ' + (a.win_rate >= 50 ? "strong" : "muted") + '">' + pct(a.win_rate) + "</td>" +
          '<td class="num">' + fmt2(a.kd) + "</td>" +
          '<td class="num muted">' + fmt2(a.kda) + "</td>" +
          '<td class="num strong">' + fmtInt(a.acs) + "</td>" +
          '<td class="num muted">' + fmtInt(a.adr) + "</td>" +
          '<td class="num muted">' + pct(a.hs_pct) + "</td>" +
          '<td class="num">' + sideRate(a.attack) + "</td>" +
          '<td class="num">' + sideRate(a.defense) + "</td>" +
          '<td class="num">' + impactChip(a.impact) + "</td>" +
          "</tr>"
        );
      }).join("") +
      "</tbody></table>"
    );
  }

  function sideRate(side) {
    if (!side || !side.rounds) return '<span class="muted">—</span>';
    return pct(side.round_win_rate);
  }

  /* -------------------------------------------------------------------- maps */
  function renderMaps() {
    if (!hasData()) return emptyState();
    const maps = state.stats.maps;
    const pool = maps.filter(function (m) { return m.matches >= 2; });
    const chosen = pool.length ? pool : maps;
    const best = chosen.slice().sort(function (a, b) { return b.impact - a.impact; })[0];
    const worst = chosen.slice().sort(function (a, b) { return a.impact - b.impact; })[0];
    const most = chosen.slice().sort(function (a, b) { return b.matches - a.matches; })[0];
    const cards = [];
    if (best) cards.push(mapSpotlight("best", "Meilleure map", best, "Force"));
    if (most && (!best || most.id !== best.id)) cards.push(mapSpotlight("volume", "Map la plus jouée", most, "Volume"));
    if (worst && best && worst.id !== best.id) cards.push(mapSpotlight("worst", "À travailler", worst, "Priorité"));

    return (
      '<div class="spotlight-grid">' + cards.slice(0, 3).join("") + "</div>" +
      '<div class="panel"><div class="panel-head"><h3>Win rate par map</h3><p>Repère à 50 % · indice de performance</p></div>' +
      '<div class="panel-body map-bars">' + mapBars(maps) + "</div></div>" +
      '<div class="panel" style="margin-top:12px"><div class="panel-head"><h3>Détail par map</h3>' +
      '<p>Clique sur une map pour voir tes stats par agent · ATK / DEF = win rate de round par côté</p></div><div class="table-wrap">' + mapsTable(maps) + "</div>" +
      (state.openMap ? mapDetail(maps.find(function (m) { return m.id === state.openMap; })) : "") +
      '<div class="table-foot"><span>Les maps avec peu de parties ont un indice moins fiable.</span><span>Clique sur un en-tête pour trier.</span><span class="only-mobile">Glisse pour voir toutes les colonnes.</span></div></div>'
    );
  }

  function mapSpotlight(kind, kicker, map, badge) {
    const open = state.openMap === map.id;
    return (
      '<article class="spotlight is-clickable ' + kind + '" data-map-toggle="' + esc(map.id) + '" role="button" tabindex="0" aria-expanded="' + (open ? "true" : "false") + '" aria-label="Voir les agents sur ' + esc(map.name) + '">' +
      mapThumb(map.id, map.name) +
      '<div class="spot-body"><div class="spot-kicker"><span class="marker"></span>' + esc(kicker) + "</div>" +
      "<h3>" + esc(map.name) + "</h3>" +
      '<div class="spot-stats"><span><b>' + pct(map.win_rate) + "</b> WR</span>" +
      "<span><b>" + fmtInt(map.acs) + "</b> ACS</span>" +
      "<span><b>" + fmt2(map.kd) + "</b> K/D</span></div>" +
      '<div class="spot-stats" style="margin-top:5px"><span>' + map.matches + " parties</span>" +
      '<span class="chip ' + (map.impact >= 100 ? "good" : "bad") + '">' + esc(badge) + " " + signed(map.impact - 100) + "</span>" +
      '<span class="spot-open">Agents →</span></div>' +
      "</div></article>"
    );
  }

  function mapsTable(maps) {
    const sort = state.sort.maps;
    const rows = maps.slice().sort(function (a, b) {
      return compare(a, b, sort.key, sort.dir, mapSortValue);
    });
    return (
      '<table class="data"><thead><tr>' +
      th("Map", "name", "maps") +
      th("Parties", "matches", "maps", "num") +
      th("WR", "win_rate", "maps", "num") +
      th("K/D", "kd", "maps", "num") +
      th("ACS", "acs", "maps", "num") +
      th("ADR", "adr", "maps", "num") +
      th("ATK WR", "atk_wr", "maps", "num") +
      th("DEF WR", "def_wr", "maps", "num") +
      th("Indice", "impact", "maps", "num") +
      "</tr></thead><tbody>" +
      rows.map(function (m) {
        const open = state.openMap === m.id;
        return (
          '<tr class="map-row' + (open ? " is-open" : "") + '" data-map-toggle="' + esc(m.id) + '">' +
          '<td><div class="map-cell"><div class="agent-cell">' + mapThumb(m.id, m.name) + '<span class="strong">' + esc(m.name) + "</span></div>" +
          '<button class="row-toggle" type="button" data-map-toggle="' + esc(m.id) + '" aria-expanded="' + (open ? "true" : "false") + '" aria-controls="map-detail-panel" aria-label="' + (open ? "Masquer" : "Afficher") + " les agents sur " + esc(m.name) + '">' + (open ? "−" : "+") + "</button></div></td>" +
          '<td class="num muted">' + m.matches + "</td>" +
          '<td class="num ' + (m.win_rate >= 50 ? "strong" : "muted") + '">' + pct(m.win_rate) + "</td>" +
          '<td class="num">' + fmt2(m.kd) + "</td>" +
          '<td class="num strong">' + fmtInt(m.acs) + "</td>" +
          '<td class="num muted">' + fmtInt(m.adr) + "</td>" +
          '<td class="num">' + sideRate(m.attack) + "</td>" +
          '<td class="num">' + sideRate(m.defense) + "</td>" +
          '<td class="num">' + impactChip(m.impact) + "</td>" +
          "</tr>"
        );
      }).join("") +
      "</tbody></table>"
    );
  }

  function mapDetail(m) {
    if (!m) return "";
    const agents = m.agents || [];
    if (!agents.length) {
      return '<div class="map-detail" id="map-detail-panel"><p class="muted">Pas encore assez de parties sur cette map.</p></div>';
    }
    const best = agents.find(function (a) { return a.matches >= 2; }) || null;
    return (
      '<div class="map-detail" id="map-detail-panel">' +
      '<div class="map-detail-head"><div><p class="eyebrow">Détail de la map</p><h4>Agents sur ' + esc(m.name) + "</h4></div>" +
      '<p class="map-detail-note">Indice calculé par rapport à ta moyenne sur cette map.</p></div>' +
      '<div class="table-wrap"><table class="data compact"><thead><tr>' +
      "<th>Agent</th><th class=\"num\">Parties</th><th class=\"num\">WR</th><th class=\"num\">K/D</th><th class=\"num\">ACS</th><th class=\"num\">ADR</th><th class=\"num\">ATK WR</th><th class=\"num\">DEF WR</th><th class=\"num\">Indice</th>" +
      "</tr></thead><tbody>" +
      agents.map(function (a) {
        const isBest = best && a.id === best.id;
        return (
          "<tr><td><div class=\"agent-cell\">" + agentAvatar(a.id, a.name) +
          '<span class="strong">' + esc(a.name) + "</span>" +
          (isBest ? '<span class="chip good">Meilleur</span>' : "") + "</div></td>" +
          '<td class="num muted">' + a.matches + "</td>" +
          '<td class="num ' + (a.win_rate >= 50 ? "strong" : "muted") + '">' + pct(a.win_rate) + "</td>" +
          '<td class="num">' + fmt2(a.kd) + "</td>" +
          '<td class="num strong">' + fmtInt(a.acs) + "</td>" +
          '<td class="num muted">' + fmtInt(a.adr) + "</td>" +
          '<td class="num">' + sideRate(a.attack) + "</td>" +
          '<td class="num">' + sideRate(a.defense) + "</td>" +
          '<td class="num">' + impactChip(a.impact) + "</td></tr>"
        );
      }).join("") +
      "</tbody></table></div></div>"
    );
  }

  function toggleMap(id) {
    if (!id) return;
    state.openMap = state.openMap === id ? null : id;
    renderView();
    if (state.openMap) {
      const target = document.getElementById("map-detail-panel");
      if (target) {
        window.requestAnimationFrame(function () {
          target.scrollIntoView({ behavior: "smooth", block: "center" });
        });
      }
    }
  }

  /* ------------------------------------------------------------------- sides */
  function renderSides() {
    if (!hasData()) return emptyState();
    const s = state.stats.summary;
    const atk = s.attack;
    const dfn = s.defense;
    if (!atk.rounds && !dfn.rounds) {
      return (
        '<div class="empty-state"><div class="empty-inner"><p class="eyebrow">Données de round</p>' +
        "<h2>Pas de split attaque / défense</h2>" +
        "<p>Ce mode ne fournit pas de rounds exploitables. Filtre sur un mode tactique pour analyser les côtés.</p></div></div>"
      );
    }
    const verdict = sideVerdict(atk, dfn);

    const mapRows = state.stats.maps
      .filter(function (m) { return m.attack.rounds > 0 && m.defense.rounds > 0; })
      .map(function (m) {
        const gap = m.attack.round_win_rate - m.defense.round_win_rate;
        return { map: m, gap: gap };
      })
      .sort(function (a, b) { return b.gap - a.gap; });

    const agentRows = state.stats.agents
      .filter(function (a) { return a.attack.rounds > 0 && a.defense.rounds > 0; })
      .map(function (a) {
        const gap = a.attack.round_win_rate - a.defense.round_win_rate;
        return { agent: a, gap: gap };
      })
      .sort(function (a, b) { return b.gap - a.gap; });

    return (
      '<div class="side-grid">' + sideCard("attack", atk) + sideCard("defense", dfn) + "</div>" +
      (verdict ? '<div class="side-verdict"><span class="verdict-mark"></span><div>' + verdict + "</div></div>" : "") +

      '<section class="section"><div class="section-head"><div><p class="eyebrow">Priorités</p><h2>Écart par map</h2></div>' +
      '<div class="section-note">WR attaque − WR défense · positif = attaque plus forte</div></div>' +
      '<div class="panel"><div class="table-wrap"><table class="data"><thead><tr>' +
      "<th>Map</th><th class=\"num\">Rounds ATK</th><th class=\"num\">WR ATK</th><th class=\"num\">Rounds DEF</th><th class=\"num\">WR DEF</th><th class=\"num\">Écart</th>" +
      "</tr></thead><tbody>" +
      (mapRows.length
        ? mapRows.map(function (row) {
            return (
              "<tr><td class=\"strong\">" + esc(row.map.name) + "</td>" +
              '<td class="num muted">' + fmtInt(row.map.attack.rounds) + "</td>" +
              '<td class="num">' + pct(row.map.attack.round_win_rate) + "</td>" +
              '<td class="num muted">' + fmtInt(row.map.defense.rounds) + "</td>" +
              '<td class="num">' + pct(row.map.defense.round_win_rate) + "</td>" +
              '<td class="num">' + gapChip(row.gap) + "</td></tr>"
            );
          }).join("")
        : '<tr><td colspan="6" class="muted">Pas assez de rounds par map.</td></tr>') +
      "</tbody></table></div>" +
      '<div class="table-foot"><span>Les maps en haut sont celles où ta défense décroche le plus.</span><span>Minimum 1 round de chaque côté.</span><span class="only-mobile">Glisse pour voir toutes les colonnes.</span></div></div></section>' +

      '<section class="section"><div class="section-head"><div><p class="eyebrow">Par agent</p><h2>Écart par agent</h2></div>' +
      '<div class="section-note">Identifie les agents qui souffrent d\'un côté</div></div>' +
      '<div class="panel"><div class="table-wrap"><table class="data"><thead><tr>' +
      "<th>Agent</th><th class=\"num\">Parties</th><th class=\"num\">Rounds ATK</th><th class=\"num\">WR ATK</th><th class=\"num\">Rounds DEF</th><th class=\"num\">WR DEF</th><th class=\"num\">Écart</th>" +
      "</tr></thead><tbody>" +
      (agentRows.length
        ? agentRows.map(function (row) {
            return (
              "<tr><td>" + '<div class="agent-cell">' + agentAvatar(row.agent.id, row.agent.name) + '<span class="strong">' + esc(row.agent.name) + "</span></div></td>" +
              '<td class="num muted">' + row.agent.matches + "</td>" +
              '<td class="num muted">' + fmtInt(row.agent.attack.rounds) + "</td>" +
              '<td class="num">' + pct(row.agent.attack.round_win_rate) + "</td>" +
              '<td class="num muted">' + fmtInt(row.agent.defense.rounds) + "</td>" +
              '<td class="num">' + pct(row.agent.defense.round_win_rate) + "</td>" +
              '<td class="num">' + gapChip(row.gap) + "</td></tr>"
            );
          }).join("")
        : '<tr><td colspan="7" class="muted">Pas assez de rounds par agent.</td></tr>') +
      "</tbody></table></div></div></section>"
    );
  }

  function gapChip(gap) {
    const value = Number(gap) || 0;
    const cls = Math.abs(value) < 3 ? "neutral" : "bad";
    return '<span class="chip ' + cls + '">' + signed(value) + "</span>";
  }

  /* ----------------------------------------------------------------- matches */
  function renderMatches() {
    if (!hasData()) return emptyState();
    const count = state.stats.recent.length;
    const highlight = state.stats.highlight;
    return (
      (highlight ? recordCard(highlight) : "") +
      '<div class="panel"><div class="panel-head"><h3>Historique récent</h3><p>' + count + " dernières parties de la période</p></div>" +
      '<div class="panel-body">' +
      '<div class="match-toolbar"><input class="search" id="matches-search" type="search" placeholder="Filtrer par map, agent ou file…" value="' + esc(state.search) + '" autocomplete="off">' +
      '<span class="filter-meta" style="margin-left:auto"><span id="matches-count">' + count + " parties</span></span></div>" +
      '<div id="matches-table-zone">' + matchesTable(filteredMatches(), true) + "</div>" +
      "</div></div>"
    );
  }

  function filteredMatches() {
    const term = state.search.trim().toLowerCase();
    if (!term) return state.stats.recent;
    return state.stats.recent.filter(function (m) {
      return (m.map + " " + m.agent + " " + m.queue + " " + m.score).toLowerCase().indexOf(term) >= 0;
    });
  }

  function refreshMatchesTable() {
    const zone = document.getElementById("matches-table-zone");
    if (!zone) return;
    const rows = filteredMatches();
    zone.innerHTML = matchesTable(rows, true);
    const count = document.getElementById("matches-count");
    if (count) count.textContent = rows.length + " partie" + (rows.length > 1 ? "s" : "");
  }

  function recordCard(m) {
    const cls = resultClass(m);
    const atkLost = Math.max(0, m.attack_rounds - m.attack_wins);
    const defLost = Math.max(0, m.defense_rounds - m.defense_wins);
    return (
      '<article class="record-card">' +
      '<div class="record-kicker"><span class="marker"></span>Meilleure partie · plus haut ACS</div>' +
      '<div class="record-grid">' +
      '<div class="record-who">' + agentAvatar(m.agent_id, m.agent, "xl") +
      '<div class="record-id"><h3>' + esc(m.agent) + "</h3>" +
      "<p>" + esc(m.map) + " · " + esc(dateShort(m.date)) + "</p>" +
      '<div class="record-tags"><span class="result-badge ' + cls + '">' + resultLetter(m) + "</span>" +
      '<span class="score-main ' + cls + '">' + esc(m.score) + "</span>" +
      '<span class="queue-tag">' + esc(queueLabel(m.queue_id || m.queue)) + "</span></div></div></div>" +
      '<div class="record-acs"><span class="value">' + fmtInt(m.acs) + '</span><span class="label">ACS</span></div>' +
      '<div class="record-stats">' +
      recordStat(m.kills + " / " + m.deaths + " / " + m.assists, "K / D / A") +
      recordStat(fmt2(m.kd), "K/D") +
      recordStat(m.attack_wins + "-" + atkLost, "ATK") +
      recordStat(m.defense_wins + "-" + defLost, "DEF") +
      "</div></div></article>"
    );
  }

  function recordStat(value, label) {
    return '<div class="record-stat"><span class="v">' + value + '</span><span class="k">' + esc(label) + "</span></div>";
  }

  function matchesTable(rows, detailed) {
    if (!rows || !rows.length) {
      return '<div class="chart-empty">Aucune partie ne correspond à ce filtre.</div>';
    }
    return (
      '<div class="table-wrap"><table class="data"><thead><tr>' +
      "<th>Date</th><th>Map</th><th>Agent</th><th>Résultat</th><th class=\"num\">Score</th><th class=\"num\">K / D / A</th><th class=\"num\">ACS</th>" +
      (detailed ? "<th class=\"num\">ATK</th><th class=\"num\">DEF</th><th>File</th>" : "") +
      "</tr></thead><tbody>" +
      rows.map(function (m) {
        const cls = resultClass(m);
        const atkLost = Math.max(0, m.attack_rounds - m.attack_wins);
        const defLost = Math.max(0, m.defense_rounds - m.defense_wins);
        return (
          "<tr>" +
          '<td class="muted">' + esc(dateShort(m.date)) + "</td>" +
          '<td><div class="agent-cell">' + mapThumb(m.map_id, m.map) + '<span class="strong">' + esc(m.map) + "</span></div></td>" +
          '<td><div class="agent-cell">' + agentAvatar(m.agent_id, m.agent) + '<span class="muted">' + esc(m.agent) + "</span></div></td>" +
          '<td><span class="result-badge ' + cls + '">' + resultLetter(m) + "</span></td>" +
          '<td class="num"><span class="score-main ' + cls + '">' + esc(m.score) + "</span></td>" +
          '<td class="num muted">' + m.kills + " / " + m.deaths + " / " + m.assists + "</td>" +
          '<td class="num strong">' + fmtInt(m.acs) + "</td>" +
          (detailed
            ? '<td class="num"><div class="side-mini"><span class="atk">' + m.attack_wins + "-" + atkLost + "</span></div></td>" +
              '<td class="num"><div class="side-mini"><span class="def">' + m.defense_wins + "-" + defLost + "</span></div></td>" +
              '<td><span class="queue-tag">' + esc(queueLabel(m.queue_id || m.queue)) + "</span></td>"
            : "") +
          "</tr>"
        );
      }).join("") +
      "</tbody></table></div>"
    );
  }

  /* ------------------------------------------------------------------ sorting */
  function agentSortValue(agent, key) {
    if (key === "name") return agent.name;
    if (key === "atk_wr") return agent.attack.round_win_rate;
    if (key === "def_wr") return agent.defense.round_win_rate;
    return agent[key];
  }

  function mapSortValue(map, key) {
    if (key === "name") return map.name;
    if (key === "atk_wr") return map.attack.round_win_rate;
    if (key === "def_wr") return map.defense.round_win_rate;
    return map[key];
  }

  function compare(a, b, key, dir, getter) {
    let va = getter(a, key);
    let vb = getter(b, key);
    if (typeof va === "string" || typeof vb === "string") {
      return String(va).localeCompare(String(vb), "fr") * dir;
    }
    va = Number(va) || 0;
    vb = Number(vb) || 0;
    return (va - vb) * dir;
  }

  function th(label, key, table, cls) {
    const sort = state.sort[table];
    const active = sort && sort.key === key;
    const ind = active ? (sort.dir === -1 ? "▼" : "▲") : "";
    return (
      '<th class="sortable ' + (cls || "") + '" data-sort-table="' + table + '" data-sort-key="' + key + '">' +
      esc(label) + (ind ? ' <span class="sort-ind">' + ind + "</span>" : "") + "</th>"
    );
  }

  function onAppClick(event) {
    const mapEl = event.target.closest("[data-map-toggle]");
    if (mapEl) {
      toggleMap(mapEl.dataset.mapToggle);
      return;
    }
    const sortEl = event.target.closest("[data-sort-table]");
    if (sortEl) {
      const table = sortEl.dataset.sortTable;
      const key = sortEl.dataset.sortKey;
      const current = state.sort[table];
      if (current && current.key === key) {
        current.dir = current.dir === -1 ? 1 : -1;
      } else {
        state.sort[table] = { key: key, dir: key === "name" ? 1 : -1 };
      }
      renderView();
      return;
    }
    const actionEl = event.target.closest("[data-action]");
    if (actionEl) return; // handled by the document-level listener
  }

  // "Voir tout" on the overview.
  document.addEventListener("click", function (event) {
    const el = event.target.closest('[data-action="all-matches"]');
    if (el) goTab("matches");
  });

  /* ------------------------------------------------------------------- sync */
  function renderSyncUI() {
    const pill = document.getElementById("sync-pill");
    const label = document.getElementById("sync-label");
    const btn = document.getElementById("sync-btn");
    if (!pill || !label || !btn) return;
    const sync = (state.boot && state.boot.sync) || { state: "idle" };
    let uiState = sync.state === "running" ? "running" : sync.state === "error" ? "error" : "idle";
    let text = "Prêt";
    if (sync.state === "running") {
      text = sync.total > 1 ? "Sync " + Math.min(sync.progress + 1, sync.total) + "/" + sync.total : "Sync…";
    } else if (sync.state === "error") {
      text = "Erreur";
    } else if (sync.last_sync) {
      text = sync.stale ? "À sync" : "À jour";
      uiState = sync.stale ? "idle" : "success";
    }
    pill.dataset.state = uiState;
    label.textContent = text;
    btn.disabled = sync.state === "running";
    btn.classList.toggle("is-loading", sync.state === "running");
    const btnLabel = btn.querySelector(".btn-label");
    if (btnLabel) btnLabel.textContent = sync.state === "running" ? "Synchronisation…" : "Synchroniser";
  }

  async function startSync(full) {
    if (!state.boot || !state.boot.configured) {
      openSettings();
      showToast("Configure d'abord ton Riot ID et ta clé API.", "err");
      return;
    }
    try {
      const result = await fetchJSON("/api/sync", {
        method: "POST",
        body: JSON.stringify({ full: !!full }),
      });
      state.boot.sync = result.sync;
      renderSyncUI();
      showToast(full ? "Synchronisation complète lancée." : "Synchronisation lancée.", "ok");
      pollSync();
    } catch (err) {
      if (err.status === 409 && err.data && err.data.sync) {
        state.boot.sync = err.data.sync;
        renderSyncUI();
        pollSync();
        return;
      }
      showToast(err.message, "err");
    }
  }

  function pollSync() {
    if (state.pollTimer) clearInterval(state.pollTimer);
    const tick = async function () {
      try {
        const sync = await fetchJSON("/api/sync/status");
        state.boot.sync = sync;
        renderSyncUI();
        if (sync.state === "running") return;
        clearInterval(state.pollTimer);
        state.pollTimer = null;
        if (sync.state === "success") {
          showToast(sync.message || "Synchronisation terminée.", "ok");
          await reloadAll(false);
        } else if (sync.state === "error") {
          renderNotices();
          showToast(sync.error || "Synchronisation impossible.", "err");
          await reloadBootstrap();
        }
      } catch (err) {
        clearInterval(state.pollTimer);
        state.pollTimer = null;
        showToast(err.message, "err");
      }
    };
    tick();
    state.pollTimer = setInterval(tick, 1300);
  }

  async function reloadBootstrap() {
    try {
      state.boot = await fetchJSON("/api/bootstrap");
      renderNotices();
      renderSyncUI();
      updateSettingsSummary();
    } catch (err) {
      // ignore
    }
  }

  /* ---------------------------------------------------------------- notices */
  function renderNotices() {
    if (!noticeStack) return;
    const notices = [];
    if (state.boot && state.boot.demo) {
      notices.push(
        '<div class="notice demo"><span class="notice-text"><strong>Mode démo.</strong> Ces parties sont fictives : connecte ton compte pour importer tes vraies statistiques.</span>' +
        '<span class="notice-actions"><button class="link-btn" data-action="open-settings">Connecter mon compte</button>' +
        '<button class="link-btn" data-action="clear-demo">Effacer la démo</button></span></div>'
      );
    }
    const sync = state.boot && state.boot.sync;
    if (sync && sync.state === "error" && sync.error) {
      notices.push(
        '<div class="notice error"><span class="notice-text"><strong>Synchronisation impossible.</strong> ' + esc(sync.error) + "</span>" +
        '<span class="notice-actions"><button class="link-btn" data-action="sync">Réessayer</button>' +
        '<button class="link-btn" data-action="open-settings">Réglages</button></span></div>'
      );
    }
    if (state.boot && !state.boot.configured && !state.boot.demo) {
      notices.push(
        '<div class="notice demo"><span class="notice-text">Aucun compte connecté. Ajoute ton Riot ID et ta clé API pour démarrer.</span>' +
        '<span class="notice-actions"><button class="link-btn" data-action="open-settings">Configurer</button></span></div>'
      );
    }
    noticeStack.innerHTML = notices.join("");
  }

  /* ---------------------------------------------------------------- settings */
  function openSettings() {
    if (!state.boot) return;
    const cfg = state.boot.config || {};
    $("#field-name").value = cfg.riot_name || "";
    $("#field-tag").value = cfg.riot_tag || "";
    $("#field-region").value = cfg.region || "eu";
    $("#field-platform").value = cfg.platform || "pc";
    $("#field-backfill").value = String(cfg.backfill || 40);
    $("#field-queue-mode").value = cfg.queue_mode || "competitive";
    const key = $("#field-key");
    key.value = "";
    key.type = "password";
    key.placeholder = cfg.has_api_key ? "Clé enregistrée — laisser vide" : "Coller la clé ici";
    $("#toggle-key").textContent = "Afficher";
    settingsFeedback("", "");
    updateSettingsSummary();
    if (!dialog.open) dialog.showModal();
  }

  function settingsPayload() {
    return {
      riot_name: $("#field-name").value.trim(),
      riot_tag: $("#field-tag").value.trim(),
      region: $("#field-region").value,
      platform: $("#field-platform").value,
      api_key: $("#field-key").value.trim(),
      backfill: Number($("#field-backfill").value) || 40,
      queue_mode: $("#field-queue-mode").value,
    };
  }

  function settingsFeedback(message, kind) {
    const el = $("#settings-feedback");
    if (!el) return;
    el.textContent = message || "";
    el.className = "form-feedback " + (kind || "");
  }

  async function testConnection() {
    const btn = $("#test-btn");
    const payload = settingsPayload();
    if (!payload.riot_name || !payload.riot_tag) {
      settingsFeedback("Renseigne un Riot ID complet (Pseudo#TAG).", "err");
      return;
    }
    const old = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Test en cours…";
    settingsFeedback("Connexion à l'API…", "");
    try {
      const result = await fetchJSON("/api/test", { method: "POST", body: JSON.stringify(payload) });
      const p = result.profile || {};
      settingsFeedback(
        "Connexion OK : " + (p.name || payload.riot_name) + "#" + (p.tag || payload.riot_tag) +
        (p.rank ? " · " + p.rank + (p.rr != null ? " (" + p.rr + " RR)" : "") : "") + ".",
        "ok"
      );
    } catch (err) {
      settingsFeedback(err.message, "err");
    } finally {
      btn.disabled = false;
      btn.textContent = old;
    }
  }

  async function saveSettings(andSync) {
    const payload = settingsPayload();
    if (!payload.riot_name || !payload.riot_tag) {
      settingsFeedback("Renseigne ton Riot ID (Pseudo) et ton tag.", "err");
      return;
    }
    if (!payload.api_key && !(state.boot && state.boot.config.has_api_key)) {
      settingsFeedback("Ajoute une clé API HenrikDev pour synchroniser.", "err");
      return;
    }
    const saveBtn = $("#save-btn");
    const syncBtn = $("#save-sync-btn");
    const previousQueueMode = (state.boot && state.boot.config && state.boot.config.queue_mode) || "competitive";
    saveBtn.disabled = true;
    syncBtn.disabled = true;
    settingsFeedback("Enregistrement…", "");
    try {
      const result = await fetchJSON("/api/settings", { method: "POST", body: JSON.stringify(payload) });
      const queueModeChanged = previousQueueMode !== result.config.queue_mode;
      state.boot = result.bootstrap;
      $("#field-key").value = "";
      $("#field-key").placeholder = result.config.has_api_key ? "Clé enregistrée — laisser vide" : "Coller la clé ici";
      settingsFeedback(result.configured ? "Réglages enregistrés." : "Réglages enregistrés, mais il manque la clé API.", result.configured ? "ok" : "err");
      renderNotices();
      renderSyncUI();
      updateSettingsSummary();
      if (result.identity_changed || queueModeChanged) {
        if (queueModeChanged) {
          state.mode = result.config.queue_mode === "competitive" ? "competitive" : "tactical";
          localStorage.setItem("valo.mode.v2", state.mode);
        }
        state.stats = await fetchJSON("/api/stats?mode=" + encodeURIComponent(state.mode) + "&days=" + state.days);
        renderView();
      }
      if (queueModeChanged && result.purged) {
        showToast(result.purged + " partie" + (result.purged > 1 ? "s" : "") + " non compétitive" + (result.purged > 1 ? "s" : "") + " supprimée" + (result.purged > 1 ? "s" : "") + ".", "ok");
      }
      if (andSync && result.configured) {
        dialog.close();
        await startSync(false);
      } else {
        await reloadAll(false);
      }
    } catch (err) {
      settingsFeedback(err.message, "err");
    } finally {
      saveBtn.disabled = false;
      syncBtn.disabled = false;
    }
  }

  async function clearDemo() {
    if (!window.confirm("Supprimer les données de démonstration ? Tes vraies données ne seront pas touchées.")) return;
    try {
      const result = await fetchJSON("/api/demo/clear", { method: "POST", body: "{}" });
      state.boot = result.bootstrap;
      state.stats = await fetchJSON("/api/stats?mode=" + encodeURIComponent(state.mode) + "&days=" + state.days);
      renderAll();
      showToast("Données de démo supprimées.", "ok");
    } catch (err) {
      showToast(err.message, "err");
    }
  }

  async function seedDemo() {
    try {
      const result = await fetchJSON("/api/demo/seed", { method: "POST", body: "{}" });
      state.boot = result.bootstrap;
      state.stats = await fetchJSON("/api/stats?mode=" + encodeURIComponent(state.mode) + "&days=" + state.days);
      renderAll();
      showToast("Données de démo chargées.", "ok");
    } catch (err) {
      showToast(err.message, "err");
    }
  }

  /* ------------------------------------------------------------------- start */
  if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", init);
    } else {
      init();
    }
  }
})();
