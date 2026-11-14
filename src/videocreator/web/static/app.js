// Shell behaviour shared by every page: theme toggle.
(function () {
  'use strict';

  var root = document.documentElement;
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
})();
