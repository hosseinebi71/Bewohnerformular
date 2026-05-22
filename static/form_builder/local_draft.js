(function () {
  "use strict";

  const PREFIX = "bewohnerformular.localDraft.";
  const SENSITIVE_TYPES = new Set(["password", "file", "hidden"]);

  function now() {
    return Date.now();
  }

  function storageKey(form) {
    return PREFIX + (form.dataset.localDraftKey || form.id || window.location.pathname);
  }

  function ttlMs(form) {
    const hours = Number(form.dataset.localDraftTtlHours || 24);
    return Math.max(1, Math.min(hours, 168)) * 60 * 60 * 1000;
  }

  function isStorable(control) {
    if (!control.name || control.disabled) return false;
    if (control.name === "csrfmiddlewaretoken") return false;
    const type = (control.type || "").toLowerCase();
    return !SENSITIVE_TYPES.has(type);
  }

  function readForm(form) {
    const data = {};
    form.querySelectorAll("input, select, textarea").forEach(function (control) {
      if (!isStorable(control)) return;
      const type = (control.type || "").toLowerCase();
      if (type === "checkbox") {
        data[control.name] = control.checked;
      } else if (type === "radio") {
        if (control.checked) data[control.name] = control.value;
      } else if (control.tagName === "SELECT" && control.multiple) {
        data[control.name] = Array.from(control.selectedOptions).map(function (option) {
          return option.value;
        });
      } else {
        data[control.name] = control.value;
      }
    });
    return data;
  }

  function writeForm(form, data) {
    form.querySelectorAll("input, select, textarea").forEach(function (control) {
      if (!isStorable(control) || !Object.prototype.hasOwnProperty.call(data, control.name)) return;
      const value = data[control.name];
      const type = (control.type || "").toLowerCase();
      if (type === "checkbox") {
        control.checked = Boolean(value);
      } else if (type === "radio") {
        control.checked = control.value === value;
      } else if (control.tagName === "SELECT" && control.multiple && Array.isArray(value)) {
        Array.from(control.options).forEach(function (option) {
          option.selected = value.includes(option.value);
        });
      } else {
        control.value = value == null ? "" : value;
      }
      control.dispatchEvent(new Event("change", { bubbles: true }));
      control.dispatchEvent(new Event("input", { bubbles: true }));
    });
  }

  function load(key) {
    try {
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : null;
    } catch (_error) {
      return null;
    }
  }

  function save(key, payload) {
    try {
      localStorage.setItem(key, JSON.stringify(payload));
    } catch (_error) {
      // Browser storage may be unavailable. Form submission still works server-side.
    }
  }

  function clear(key) {
    try {
      localStorage.removeItem(key);
    } catch (_error) {
      // Ignore unavailable storage.
    }
  }

  function init(form) {
    const key = storageKey(form);
    const banner = form.querySelector("[data-local-draft-banner]");
    const restore = form.querySelector("[data-local-draft-restore]");
    const discard = form.querySelector("[data-local-draft-discard]");
    let dirty = false;
    let timer = null;

    function existingDraft() {
      const draft = load(key);
      if (!draft || !draft.savedAt || now() - draft.savedAt > ttlMs(form)) {
        clear(key);
        return null;
      }
      return draft;
    }

    function scheduleSave() {
      dirty = true;
      window.clearTimeout(timer);
      timer = window.setTimeout(function () {
        save(key, { savedAt: now(), path: window.location.pathname, data: readForm(form) });
      }, 250);
    }

    const draft = existingDraft();
    if (draft && banner) banner.hidden = false;
    if (restore) {
      restore.addEventListener("click", function () {
        const latest = existingDraft();
        if (latest) {
          writeForm(form, latest.data || {});
          dirty = true;
        }
        if (banner) banner.hidden = true;
      });
    }
    if (discard) {
      discard.addEventListener("click", function () {
        clear(key);
        if (banner) banner.hidden = true;
      });
    }

    form.addEventListener("input", scheduleSave);
    form.addEventListener("change", scheduleSave);
    form.addEventListener("submit", function (event) {
      const submitter = event.submitter;
      if (submitter && submitter.hasAttribute("data-local-draft-clear")) {
        clear(key);
        dirty = false;
      }
    });
    window.addEventListener("beforeunload", function (event) {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = "";
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("form[data-local-draft='true']").forEach(init);
  });
})();
