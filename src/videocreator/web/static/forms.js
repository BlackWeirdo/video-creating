// apiFetch (fetch + toast feedback), POST forms sent through it, and server flash messages as toasts.
(function () {
  'use strict';

  var FLASH_PARAMS = ['msg', 'err', 'saved'];

  // FastAPI error bodies: {"detail": "text"} or, for 422, {"detail": [{"loc": [...], "msg": "..."}]}.
  function describeError(response) {
    var fallback = 'Máy chủ báo lỗi (' + response.status + '). Thao tác chưa được thực hiện.';
    return response.text().then(function (bodyText) {
      var body;
      try {
        body = JSON.parse(bodyText);
      } catch (parseError) {
        return fallback;
      }
      var detail = body && (body.detail !== undefined ? body.detail : body.message);
      if (typeof detail === 'string' && detail) {
        return detail;
      }
      if (Array.isArray(detail) && detail.length) {
        return 'Dữ liệu chưa hợp lệ: ' + detail.map(function (item) {
          var field = (item.loc || []).filter(function (part) {
            return part !== 'body' && part !== 'query';
          }).join('.');
          return (field ? field + ': ' : '') + (item.msg || '');
        }).join('; ');
      }
      return fallback;
    }, function () {
      return fallback;
    });
  }

  // fetch() that reports failures as an error toast and rejects; `successMessage` is optional.
  function apiFetch(url, options) {
    options = options || {};
    var request = { credentials: 'same-origin' };
    Object.keys(options).forEach(function (key) {
      if (key !== 'successMessage') {
        request[key] = options[key];
      }
    });
    return fetch(url, request).then(function (response) {
      if (!response.ok) {
        return describeError(response).then(function (message) {
          window.toast.error(message);
          var error = new Error(message);
          error.response = response;
          throw error;
        });
      }
      if (options.successMessage) {
        window.toast.success(options.successMessage);
      }
      return response;
    }, function (networkError) {
      window.toast.error('Không kết nối được tới ứng dụng. Kiểm tra Video Creator còn chạy rồi thử lại.');
      throw networkError;
    });
  }

  function setBusy(form, submitter, busy) {
    form.setAttribute('aria-busy', busy ? 'true' : 'false');
    if (busy) {
      form.dataset.busy = 'true';
    } else {
      delete form.dataset.busy;
    }
    if (submitter) {
      submitter.disabled = busy;
      submitter.classList.toggle('is-loading', busy);
    }
  }

  // Every POST form goes through apiFetch: a redirect is followed (its flash message becomes a
  // toast on the next page), an error is shown as a toast and the page with its inputs stays.
  // Forms marked data-native (file downloads) keep the browser's own submit.
  document.addEventListener('submit', function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement) || form.method.toLowerCase() !== 'post' ||
        form.hasAttribute('data-native')) {
      return;
    }
    event.preventDefault();
    if (form.dataset.busy) {
      return;
    }
    var submitter = event.submitter || null;
    var data = new FormData(form);
    if (submitter && submitter.name) {
      data.append(submitter.name, submitter.value);
    }
    var body = form.querySelector('input[type="file"]') ? data : new URLSearchParams(data);
    setBusy(form, submitter, true);
    apiFetch(form.action, { method: 'POST', body: body }).then(function (response) {
      if (response.redirected) {
        window.location.assign(response.url);
        return;
      }
      setBusy(form, submitter, false);
      window.toast.success('Đã thực hiện xong.');
    }, function () {
      setBusy(form, submitter, false);
    });
  });

  // A page restored from the back/forward cache must not come back with disabled buttons.
  window.addEventListener('pageshow', function (event) {
    if (!event.persisted) {
      return;
    }
    document.querySelectorAll('form[data-busy]').forEach(function (form) {
      setBusy(form, form.querySelector('.is-loading'), false);
    });
  });

  // Flash messages rendered by the server (.alert[data-toast]) are shown as toasts, and the
  // one-shot query parameters are dropped so that a reload does not repeat them.
  function showFlashMessages() {
    document.querySelectorAll('[data-toast]').forEach(function (alertBox) {
      var type = alertBox.getAttribute('data-toast');
      var message = alertBox.textContent.replace(/\s+/g, ' ').trim();
      if (message && window.toast[type]) {
        window.toast[type](message);
      }
      alertBox.remove();
    });
    var url = new URL(window.location.href);
    var hadFlash = false;
    FLASH_PARAMS.forEach(function (name) {
      if (url.searchParams.has(name)) {
        url.searchParams.delete(name);
        hadFlash = true;
      }
    });
    if (hadFlash) {
      window.history.replaceState(null, '', url.pathname + url.search + url.hash);
    }
  }

  window.apiFetch = apiFetch;
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', showFlashMessages);
  } else {
    showFlashMessages();
  }
})();
