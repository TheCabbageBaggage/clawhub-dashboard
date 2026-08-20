/* ============================================================
   ACTA ClawHub Shell — Theme, Sidebar, Navigation, Topbar
   Injiziert Sidebar + Topbar automatisch in jede Subseite.
   ============================================================ */

(function () {
  'use strict';

  // --- Theme (Dark/Light über Button, persistiert) ---
  const THEME_KEY = 'acta-theme';

  function getStoredTheme() {
    try { return localStorage.getItem(THEME_KEY); } catch (e) { return null; }
  }
  function setStoredTheme(t) {
    try { localStorage.setItem(THEME_KEY, t); } catch (e) {}
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    const icon = document.getElementById('themeIcon');
    if (icon) icon.textContent = theme === 'dark' ? '☀️' : '🌙';
  }

  function initTheme() {
    applyTheme(getStoredTheme() || 'light');
  }

  function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
    const next = current === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    setStoredTheme(next);
  }

  // --- Topbar bauen (Titel aus <title>, Theme-Toggle) ---
  function buildTopbar() {
    const main = document.querySelector('.acta-main');
    if (!main) return;
    const pageTitle = document.title.replace(/^ClawHub — /, '') || 'Dashboard';
    const topbar = document.createElement('div');
    topbar.className = 'acta-topbar';
    topbar.innerHTML =
      '<div style="display:flex;align-items:center;gap:0.75rem;">' +
        '<button class="acta-hamburger" id="actaHamburger" aria-label="Menü">' +
          '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M3 12h18M3 18h18"/></svg>' +
        '</button>' +
        '<div class="acta-topbar-title">' + pageTitle + '</div>' +
      '</div>' +
      '<div class="acta-topbar-actions">' +
        '<button class="acta-theme-toggle" id="actaThemeToggle" aria-label="Theme umschalten">' +
          '<span id="themeIcon">🌙</span>' +
        '</button>' +
      '</div>';
    main.prepend(topbar);
  }

  // --- Sidebar injizieren (aus js/sidebar.html) ---
  function injectSidebar() {
    const layout = document.querySelector('.acta-layout');
    if (!layout) return;
    const base = document.querySelector('script[data-shell]')?.getAttribute('data-shell') || '';
    fetch(base + 'js/sidebar.html')
      .then(function (r) { return r.text(); })
      .then(function (html) {
        const wrapper = document.createElement('div');
        wrapper.innerHTML = html;
        const aside = wrapper.querySelector('.acta-sidebar');
        if (aside) layout.prepend(aside);
        initSidebar();
        initNav();
      })
      .catch(function () { /* Sidebar konnte nicht geladen werden */ });
  }

  // --- Sidebar (Mobile Toggle) ---
  function initSidebar() {
    const sidebar = document.getElementById('actaSidebar');
    const hamburger = document.getElementById('actaHamburger');
    if (sidebar && hamburger) {
      hamburger.addEventListener('click', function () {
        sidebar.classList.toggle('open');
      });
    }
  }

  // --- Active Nav Highlight ---
  function initNav() {
    const path = window.location.pathname.split('/').pop() || 'index.html';
    document.querySelectorAll('.acta-nav-item').forEach(function (link) {
      const href = link.getAttribute('href');
      if (href && href.split('/').pop() === path) {
        link.classList.add('active');
      }
    });
  }

  // --- Boot ---
  document.addEventListener('DOMContentLoaded', function () {
    initTheme();
    buildTopbar();
    injectSidebar();
    const toggle = document.getElementById('actaThemeToggle');
    if (toggle) toggle.addEventListener('click', toggleTheme);
  });
})();
