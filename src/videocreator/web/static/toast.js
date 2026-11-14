// Toast notifications: window.toast.success/error/info/warning(message).
(function () {
  'use strict';

  var DURATION_MS = { success: 4000, info: 4000, warning: 6000, error: 8000 };
  var MAX_VISIBLE = 5;
  var ICON_PATHS = {
    success: 'M8 12.5l3 3 5-6',
    error: 'M12 7.5v5.5M12 16.5v.01',
    warning: 'M12 8v5M12 16.5v.01',
    info: 'M12 11v5.5M12 7.5v.01',
  };

  var region = null;

  function getRegion() {
    if (!region) {
      region = document.createElement('div');
      region.className = 'toast-region';
      region.setAttribute('role', 'status');
      region.setAttribute('aria-live', 'polite');
      document.body.appendChild(region);
    }
    return region;
  }

  function svg(pathData, withCircle) {
    var ns = 'http://www.w3.org/2000/svg';
    var el = document.createElementNS(ns, 'svg');
    el.setAttribute('viewBox', '0 0 24 24');
    el.setAttribute('aria-hidden', 'true');
    el.setAttribute('class', 'icon');
    if (withCircle) {
      var circle = document.createElementNS(ns, 'circle');
      circle.setAttribute('cx', '12');
      circle.setAttribute('cy', '12');
      circle.setAttribute('r', '9');
      el.appendChild(circle);
    }
    var path = document.createElementNS(ns, 'path');
    path.setAttribute('d', pathData);
    el.appendChild(path);
    return el;
  }

  function dismiss(item) {
    if (item.dataset.closing) {
      return;
    }
    item.dataset.closing = 'true';
    clearTimeout(item._timer);
    item.classList.add('is-leaving');
    // Removed after the exit transition; the timeout also covers reduced motion (no transition).
    setTimeout(function () {
      item.remove();
    }, 200);
  }

  function show(type, message) {
    var container = getRegion();
    var item = document.createElement('div');
    item.className = 'toast toast-' + type;
    if (type === 'error') {
      item.setAttribute('role', 'alert');
    }

    var text = document.createElement('div');
    text.className = 'toast-message';
    text.textContent = String(message);

    var close = document.createElement('button');
    close.type = 'button';
    close.className = 'toast-close';
    close.setAttribute('aria-label', 'Đóng thông báo');
    close.appendChild(svg('M7 7l10 10M17 7L7 17', false));
    close.addEventListener('click', function () {
      dismiss(item);
    });

    item.appendChild(svg(ICON_PATHS[type], true));
    item.appendChild(text);
    item.appendChild(close);

    function startTimer() {
      item._timer = setTimeout(function () {
        dismiss(item);
      }, DURATION_MS[type]);
    }
    function stopTimer() {
      clearTimeout(item._timer);
    }
    // Reading a toast (pointer over it, or keyboard focus inside it) keeps it open.
    item.addEventListener('mouseenter', stopTimer);
    item.addEventListener('mouseleave', startTimer);
    item.addEventListener('focusin', stopTimer);
    item.addEventListener('focusout', startTimer);

    container.appendChild(item);
    while (container.children.length > MAX_VISIBLE) {
      container.firstElementChild.remove();
    }
    startTimer();
    return item;
  }

  window.toast = {
    success: function (message) { return show('success', message); },
    error: function (message) { return show('error', message); },
    info: function (message) { return show('info', message); },
    warning: function (message) { return show('warning', message); },
  };
})();
