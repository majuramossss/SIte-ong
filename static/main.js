"use strict";

// The navigation and gallery remain fully available without JavaScript.
const menuButton = document.querySelector(".menu-toggle");
const navigation = document.getElementById("menu-principal");
if (menuButton && navigation) {
  menuButton.hidden = false;
  const mobile = window.matchMedia("(max-width: 62rem)");
  const setMenu = (open) => {
    menuButton.setAttribute("aria-expanded", String(open));
    navigation.hidden = mobile.matches && !open;
  };
  setMenu(false);
  menuButton.addEventListener("click", () => {
    setMenu(menuButton.getAttribute("aria-expanded") !== "true");
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && mobile.matches && !navigation.hidden) {
      setMenu(false);
      menuButton.focus();
    }
  });
  document.addEventListener("click", (event) => {
    if (mobile.matches && !navigation.hidden &&
        !navigation.contains(event.target) && !menuButton.contains(event.target)) {
      setMenu(false);
    }
  });
  mobile.addEventListener("change", () => {
    const focusWasInside = navigation.contains(document.activeElement);
    setMenu(false);
    if (mobile.matches && focusWasInside) menuButton.focus();
  });
}

document.querySelectorAll("[data-gallery]").forEach((gallery) => {
  const controls = gallery.querySelector("[data-filters]");
  const cards = Array.from(gallery.querySelectorAll("[data-animal]"));
  const selects = Array.from(gallery.querySelectorAll("[data-filter]"));
  const count = gallery.querySelector("[data-results]");
  const empty = gallery.querySelector("[data-empty]");
  const update = () => {
    const filters = Object.fromEntries(selects.map((select) => [select.dataset.filter, select.value]));
    let visible = 0;
    cards.forEach((card) => {
      const months = Number(card.dataset.age);
      const age = months <= 12 ? "filhote" : months <= 84 ? "adulto" : "idoso";
      const matches = (!filters.age || age === filters.age) &&
        (!filters.size || card.dataset.size === filters.size) &&
        (!filters.temperament || card.dataset.temperament === filters.temperament);
      card.hidden = !matches;
      if (matches) visible += 1;
    });
    count.textContent = `${visible} ${visible === 1 ? "gato encontrado" : "gatos encontrados"} de ${cards.length} disponíveis`;
    empty.hidden = visible !== 0;
  };
  controls.hidden = false;
  selects.forEach((select) => select.addEventListener("change", update));
  gallery.querySelector("[data-reset-filters]").addEventListener("click", () => {
    selects.forEach((select) => { select.value = ""; });
    update();
  });
  update();
});

document.querySelectorAll("[data-copy-target]").forEach((button) => {
  const input = document.getElementById(button.dataset.copyTarget);
  const status = document.getElementById(button.dataset.copyStatus);
  if (!input || !status) return;
  button.hidden = false;
  button.addEventListener("click", async () => {
    try {
      if (!navigator.clipboard || !window.isSecureContext) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(input.value);
      status.textContent = "Chave PIX copiada. Confira o destinatário antes de transferir.";
    } catch {
      input.focus();
      input.select();
      input.setSelectionRange(0, input.value.length);
      let copied = false;
      try { copied = document.execCommand("copy"); } catch { /* Manual selection remains available. */ }
      status.textContent = copied
        ? "Chave PIX copiada. Confira o destinatário antes de transferir."
        : "Não foi possível copiar automaticamente. A chave está selecionada: use Copiar no celular ou Ctrl+C / Command+C.";
    }
  });
});

// Native details + explicit submit still require deliberate action without JS.
document.querySelectorAll("form[data-confirm]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  });
});