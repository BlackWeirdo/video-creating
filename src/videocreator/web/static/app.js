// Shell behaviour shared by every page: theme toggle and the sidebar drawer on narrow windows.
(function () {
  'use strict';

  var root = document.documentElement;

  // ---- Theme -------------------------------------------------------------
  var themeToggle = document.getElementById('theme-toggle');

  function currentTheme() {
    return root.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
  }

  function syncThemeToggle() {
    themeToggle.setAttribute('aria-pressed', currentTheme() === 'dark' ? 'true' : 'false');
  }

  themeToggle.addEventListener('click', function () {
    var next = currentTheme() === 'dark' ? 'light' : 'dark';
    // The class enables a short colour transition for the switch only (see style.css).
    root.classList.add('theme-switching');
    root.setAttribute('data-theme', next);
    try {
      localStorage.setItem('vc-theme', next);
    } catch (storageError) {
      // Storage can be unavailable (private mode); the theme still applies to this page.
    }
    syncThemeToggle();
    setTimeout(function () {
      root.classList.remove('theme-switching');
    }, 250);
  });

  syncThemeToggle();

  // ---- Sidebar drawer (window narrower than 900px) -------------------------
  var shell = document.getElementById('app-shell');
  var sidebar = document.getElementById('sidebar');
  var backdrop = document.getElementById('sidebar-backdrop');
  var appBody = document.getElementById('app-body');
  var menuToggle = document.getElementById('menu-toggle');
  var wideWindow = window.matchMedia('(min-width: 900px)');

  function isDrawerOpen() {
    return sidebar.classList.contains('is-open');
  }

  function openDrawer() {
    sidebar.classList.add('is-open');
    shell.classList.add('drawer-open');
    backdrop.hidden = false;
    // The page behind the drawer cannot be focused, clicked or scrolled while it is open.
    appBody.inert = true;
    menuToggle.setAttribute('aria-expanded', 'true');
    (sidebar.querySelector('[aria-current="page"]') || sidebar.querySelector('a')).focus();
  }

  function closeDrawer(returnFocus) {
    if (!isDrawerOpen()) {
      return;
    }
    sidebar.classList.remove('is-open');
    shell.classList.remove('drawer-open');
    backdrop.hidden = true;
    appBody.inert = false;
    menuToggle.setAttribute('aria-expanded', 'false');
    if (returnFocus) {
      menuToggle.focus();
    }
  }

  menuToggle.addEventListener('click', openDrawer);
  backdrop.addEventListener('click', function () {
    closeDrawer(true);
  });
  document.getElementById('sidebar-close').addEventListener('click', function () {
    closeDrawer(true);
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
      closeDrawer(true);
    }
  });
  // Widening the window turns the drawer back into the fixed sidebar.
  wideWindow.addEventListener('change', function (event) {
    if (event.matches) {
      closeDrawer(false);
    }
  });
})();
