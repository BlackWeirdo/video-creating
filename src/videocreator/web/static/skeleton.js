// While a list page is loading, <main> shows a skeleton shaped like the page being opened.
// It appears only if the server takes longer than DELAY_MS; nothing is delayed artificially.
(function () {
  'use strict';

  var DELAY_MS = 200;
  var main = document.getElementById('main');
  var timer = null;

  function el(className, children) {
    var node = document.createElement('div');
    node.className = className;
    (children || []).forEach(function (child) {
      node.appendChild(child);
    });
    return node;
  }

  function line(width) {
    return el('skeleton skeleton-line w' + width);
  }

  function repeat(count, build) {
    var nodes = [];
    for (var i = 0; i < count; i++) {
      nodes.push(build(i));
    }
    return nodes;
  }

  // A table row of a video / footage / post / trend list: id, title + meta, status, notes, action.
  function tableRow() {
    return el('skeleton-row', [
      el('skeleton skeleton-line w100'),
      el('', [line(90), line(45)]),
      el('skeleton skeleton-badge'),
      el('', [line(70), line(45)]),
      el('skeleton skeleton-button'),
    ]);
  }

  // A shot card: heading, thumbnail, description / tags fields, save button.
  function shotCard() {
    return el('card', [line(70), el('skeleton skeleton-thumb'), line(90), line(70), line(45),
      el('skeleton skeleton-button')]);
  }

  // An approval card: title + meta, portrait video on the left, caption fields on the right.
  function reviewCard() {
    var fields = repeat(4, function () {
      return el('skeleton-field', [line(30), el('skeleton skeleton-input')]);
    });
    fields.push(el('skeleton skeleton-button'));
    return el('card card-highlight', [line(45), line(70),
      el('skeleton-review', [el('skeleton skeleton-video'), el('', fields)])]);
  }

  var VARIANTS = {
    rows: function () {
      return [el('skeleton skeleton-title'), el('card', [line(30)].concat(repeat(6, tableRow)))];
    },
    cards: function () {
      return [el('skeleton skeleton-title'), el('card', [line(70)]), el('grid-3', repeat(6, shotCard))];
    },
    review: function () {
      return [el('skeleton skeleton-title')].concat(repeat(2, reviewCard));
    },
  };

  function show(variant) {
    var skeleton = el('page-skeleton', VARIANTS[variant]());
    skeleton.setAttribute('aria-hidden', 'true');
    main.appendChild(skeleton);
    main.classList.add('is-loading');
    main.setAttribute('aria-busy', 'true');
    main.scrollTop = 0;
  }

  function hide() {
    clearTimeout(timer);
    main.classList.remove('is-loading');
    main.removeAttribute('aria-busy');
    var skeleton = main.querySelector('.page-skeleton');
    if (skeleton) {
      skeleton.remove();
    }
  }

  document.addEventListener('click', function (event) {
    var link = event.target.closest ? event.target.closest('a[data-skeleton]') : null;
    if (!link || event.defaultPrevented || event.button !== 0 ||
        event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) {
      return;
    }
    var variant = link.getAttribute('data-skeleton');
    if (!VARIANTS[variant]) {
      return;
    }
    clearTimeout(timer);
    timer = setTimeout(function () {
      show(variant);
    }, DELAY_MS);
  });

  // Coming back through the back/forward cache must show the real content again.
  window.addEventListener('pageshow', hide);
})();
