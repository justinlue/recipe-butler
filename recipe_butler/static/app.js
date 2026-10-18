"use strict";

// All DOM is built with createElement/textContent: user text (names, notes) must never be parsed as HTML.

const state = { dishes: [], selected: null, showOriginal: false };

// -- helpers ------------------------------------------------------------------

function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "text") el.textContent = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else if (key in el && typeof value !== "string") el[key] = value;
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

function apiError(messages) {
  const error = new Error(messages.join(" "));
  error.messages = messages;
  return error;
}

async function api(method, path, body) {
  const options = { method, headers: {} };
  if (method !== "GET") {
    // The server only accepts writes sent as JSON (this keeps other web pages from changing your data).
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body === undefined ? {} : body);
  }
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw apiError(["Cannot reach Recipe Butler — is it still running?"]);
  }
  let data;
  try {
    data = await response.json();
  } catch {
    throw apiError([`Unexpected reply from the server (HTTP ${response.status}).`]);
  }
  if (!response.ok) throw apiError(data.messages || ["Request failed."]);
  return data;
}

const dishPath = (id) => "/api/dishes/" + encodeURIComponent(id);

function formatTime(iso) {
  const date = new Date(iso);
  return isNaN(date) ? iso : date.toLocaleString();
}

function formatMinutes(minutes) {
  if (minutes === null || minutes === undefined) return null;
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60), rest = minutes % 60;
  return rest ? `${hours} h ${rest} min` : `${hours} h`;
}

const main = () => document.getElementById("main");

function showMain(...children) {
  main().replaceChildren(...children);
  main().scrollTop = 0;
  // On narrow screens the sidebar stacks above the content; bring the content into view.
  if (window.matchMedia("(max-width: 720px)").matches) main().scrollIntoView({ block: "start" });
}

function errorBox(messages) {
  return h("div", { class: "errors", role: "alert" }, h("ul", {}, messages.map((m) => h("li", { text: m }))));
}

function notice(text) {
  return h("div", { class: "notice", role: "status", text });
}

// Errors from actions without their own error area go to a dismissible banner, so they never
// replace what is on screen (such as a half-filled form).
function showBanner(messages) {
  const banner = document.getElementById("banner");
  banner.replaceChildren(errorBox(messages),
    h("button", { type: "button", class: "small", text: "Dismiss", onclick: () => { banner.hidden = true; } }));
  banner.hidden = false;
}

// -- sidebar: dish list -------------------------------------------------------

async function loadDishes() {
  const hidden = document.getElementById("show-hidden").checked ? "?hidden=1" : "";
  state.dishes = await api("GET", "/api/dishes" + hidden);
  renderDishList();
}

function renderDishList() {
  const filter = document.getElementById("filter").value.trim().toLocaleLowerCase();
  const groups = new Map();
  for (const dish of state.dishes) {
    if (filter && !dish.name.toLocaleLowerCase().includes(filter)) continue;
    if (!groups.has(dish.category)) groups.set(dish.category, []);
    groups.get(dish.category).push(dish);
  }
  const list = document.getElementById("dish-list");
  if (groups.size === 0) {
    list.replaceChildren(h("p", { class: "hint", text: filter ? "No dish matches that name." : "No dishes yet." }));
    return;
  }
  list.replaceChildren(
    ...[...groups].map(([category, dishes]) =>
      h("div", { class: "group" },
        h("h2", { text: category }),
        h("ul", {}, dishes.map((dish) =>
          h("li", { class: dish.hidden ? "hidden-dish" : null },
            h("button", {
              type: "button",
              class: "dish-link" + (dish.id === state.selected ? " active" : ""),
              onclick: () => openDish(dish.id),
            }, dish.name, dish.customized ? h("span", { class: "tag", text: "yours" }) : null),
            dish.hidden ? h("button", {
              type: "button", class: "small", text: "Unhide",
              onclick: async () => { await api("POST", dishPath(dish.id) + "/unhide"); await loadDishes(); },
            }) : null,
          ))),
      ))
  );
}

// -- sidebar: ingredient search -------------------------------------------------

async function runSearch(event) {
  event.preventDefault();
  const q = document.getElementById("search-input").value;
  const out = document.getElementById("search-results");
  let result;
  try {
    result = await api("GET", "/api/search?q=" + encodeURIComponent(q));
  } catch (error) {
    out.replaceChildren(errorBox(error.messages || [error.message]));
    return;
  }
  if (result.terms.length === 0) {
    out.replaceChildren(h("p", { class: "hint", text: "Type at least one ingredient." }));
    return;
  }
  if (result.hits.length === 0) {
    out.replaceChildren(h("p", { class: "hint", text: "No dish uses all of: " + result.terms.join(", ") }));
    return;
  }
  out.replaceChildren(
    h("p", { class: "hint", text: `${result.hits.length} dish${result.hits.length === 1 ? "" : "es"}` }),
    h("ul", { class: "hits" }, result.hits.map((hit) =>
      h("li", {},
        h("button", { type: "button", class: "dish-link", onclick: () => openDish(hit.dish_id) }, hit.name),
        h("div", { class: "matched" }, "matched: ",
          Object.entries(hit.matches).map(([term, names]) => `${term} → ${names.join(", ")}`).join("; ")),
      ))),
  );
}

function selectTab(which) {
  const isSearch = which === "search";
  document.getElementById("tab-dishes").setAttribute("aria-selected", String(!isSearch));
  document.getElementById("tab-search").setAttribute("aria-selected", String(isSearch));
  document.getElementById("panel-dishes").hidden = isSearch;
  document.getElementById("panel-search").hidden = !isSearch;
  if (isSearch) document.getElementById("search-input").focus();
}

// -- dish view ------------------------------------------------------------------

async function openDish(id, banner) {
  state.selected = id;
  state.showOriginal = false;
  renderDishList();
  try {
    renderDish(await api("GET", dishPath(id)), banner);
  } catch (error) {
    showMain(errorBox(error.messages || [error.message]));
  }
}

function ingredientList(ingredients, changed) {
  return h("ul", { class: "ingredients" }, ingredients.map((ing, i) =>
    h("li", { class: changed && changed[i] ? "changed" : null },
      ing.amount ? h("span", { class: "amount", text: ing.amount }) : null,
      h("span", { text: ing.name }))));
}

function stepList(steps, changed) {
  return h("ol", { class: "steps" }, steps.map((step, i) =>
    h("li", { class: changed && changed[i] ? "changed" : null, text: step })));
}

function renderDish(view, banner) {
  const dish = view.dish;
  const isSeed = view.source === "seed";
  const facts = [
    dish.servings ? `Serves ${dish.servings}` : null,
    formatMinutes(dish.total_minutes),
    dish.category,
  ].filter(Boolean).join(" · ");

  const actions = h("div", { class: "actions" });
  if (isSeed) {
    actions.append(h("button", { type: "button", text: view.customized ? "Edit my version" : "Customize",
      onclick: () => renderForm(view) }));
    if (view.customized) {
      actions.append(
        h("button", { type: "button", text: state.showOriginal ? "Show my version" : "View original",
          onclick: () => { state.showOriginal = !state.showOriginal; renderDish(view); } }),
        h("button", { type: "button", class: "danger", text: "Revert to original", onclick: async () => {
          if (!confirm(`Revert "${dish.name}" to the original recipe? Your version will be discarded; notes are kept.`)) return;
          await api("POST", dishPath(dish.id) + "/revert");
          await loadDishes();
          await openDish(dish.id);
        } }));
    }
    actions.append(h("button", { type: "button", text: view.hidden ? "Unhide" : "Hide", onclick: async () => {
      await api("POST", dishPath(dish.id) + (view.hidden ? "/unhide" : "/hide"));
      await loadDishes();
      await openDish(dish.id);
    } }));
  } else {
    actions.append(
      h("button", { type: "button", text: "Edit", onclick: () => renderForm(view) }),
      h("button", { type: "button", class: "danger", text: "Delete", onclick: async () => {
        if (!confirm(`Delete "${dish.name}" and its notes? This cannot be undone.`)) return;
        await api("DELETE", dishPath(dish.id));
        state.selected = null;
        await loadDishes();
        showMain(notice(`Deleted "${dish.name}".`));
      } }));
  }

  const showing = view.customized && state.showOriginal ? view.original : dish;
  const changedIng = view.customized && !state.showOriginal ? view.changed_ingredients : null;
  const changedSteps = view.customized && !state.showOriginal ? view.changed_steps : null;

  const badges = h("div", { class: "badges" },
    view.customized ? h("span", { class: "badge", text: state.showOriginal ? "Original recipe" : "Your version" }) : null,
    view.hidden ? h("span", { class: "badge muted", text: "Hidden" }) : null,
    view.original_updated ? h("button", { type: "button", class: "badge warn",
      text: "Original updated since you customized this",
      onclick: () => { state.showOriginal = true; renderDish(view); } }) : null,
  );

  showMain(
    banner || "",
    h("article", { class: "dish" },
      h("h2", { text: dish.name }),
      badges,
      dish.description ? h("p", { class: "description", text: dish.description }) : null,
      facts ? h("p", { class: "facts", text: facts }) : null,
      actions,
      h("div", { class: "columns" },
        h("section", {}, h("h3", { text: "Ingredients" }), ingredientList(showing.ingredients, changedIng)),
        h("section", {}, h("h3", { text: "Steps" }), stepList(showing.steps, changedSteps))),
      renderNotes(view)),
  );
}

// -- notes ------------------------------------------------------------------------

function renderNotes(view) {
  const box = h("textarea", { rows: 3, placeholder: "Add a note: what worked, what to change next time…",
    "aria-label": "New note" });
  const errors = h("div");
  return h("section", { class: "notes" },
    h("h3", { text: "Notes" }),
    view.notes.length === 0 ? h("p", { class: "hint", text: "No notes yet." }) : null,
    h("ul", {}, view.notes.map((note) => noteItem(view, note))),
    h("form", { class: "note-form", onsubmit: async (event) => {
      event.preventDefault();
      try {
        await api("POST", dishPath(view.dish.id) + "/notes", { body: box.value });
        await openDish(view.dish.id);
      } catch (error) {
        errors.replaceChildren(errorBox(error.messages || [error.message]));
      }
    } }, errors, box, h("button", { type: "submit", text: "Add note" })),
  );
}

function noteItem(view, note) {
  const stamp = "Added " + formatTime(note.created_at) + (note.edited_at ? " · edited " + formatTime(note.edited_at) : "");
  const item = h("li", { class: "note" });
  const showNote = () => item.replaceChildren(
    h("p", { class: "note-body", text: note.body }),
    h("div", { class: "note-meta" },
      h("span", { text: stamp }),
      h("button", { type: "button", class: "small", text: "Edit", onclick: editNote }),
      h("button", { type: "button", class: "small danger", text: "Delete", onclick: async () => {
        if (!confirm("Delete this note?")) return;
        await api("DELETE", "/api/notes/" + note.id);
        await openDish(view.dish.id);
      } })));
  const editNote = () => {
    const box = h("textarea", { rows: 3, "aria-label": "Edit note" });
    box.value = note.body;
    const errors = h("div");
    item.replaceChildren(h("form", { class: "note-form", onsubmit: async (event) => {
      event.preventDefault();
      try {
        await api("PUT", "/api/notes/" + note.id, { body: box.value });
        await openDish(view.dish.id);
      } catch (error) {
        errors.replaceChildren(errorBox(error.messages || [error.message]));
      }
    } }, errors, box,
      h("div", { class: "actions" },
        h("button", { type: "submit", class: "primary", text: "Save" }),
        h("button", { type: "button", text: "Cancel", onclick: showNote }))));
    box.focus();
  };
  showNote();
  return item;
}

// -- edit form (new dish, edit own dish, customize seed) -------------------------------

function rowList(items, makeRow, addLabel) {
  const list = h("ol", { class: "rows" });
  const add = (item) => {
    const row = h("li", {}, makeRow(item),
      h("button", { type: "button", class: "small", text: "Remove", "aria-label": "Remove row",
        onclick: () => row.remove() }));
    list.append(row);
    return row;
  };
  items.forEach(add);
  const addButton = h("button", { type: "button", class: "small", text: addLabel, onclick: () => {
    const row = add(null);
    row.querySelector("input, textarea").focus();
  } });
  return { element: h("div", {}, list, addButton), list };
}

function renderForm(view) {
  const isNew = !view;
  const isSeed = view && view.source === "seed";
  const dish = view ? view.dish : { name: "", description: "", servings: null, total_minutes: null, category: "",
    ingredients: [{ name: "", amount: "" }], steps: [""] };

  const field = (label, input) => h("label", { class: "field" }, h("span", { text: label }), input);
  const name = h("input", { type: "text", value: dish.name });
  const description = h("input", { type: "text", value: dish.description });
  const category = h("input", { type: "text", value: dish.category === "Uncategorized" ? "" : dish.category,
    list: "categories" });
  const servings = h("input", { type: "number", min: "1", value: dish.servings ?? "" });
  const minutes = h("input", { type: "number", min: "0", value: dish.total_minutes ?? "" });
  const categories = h("datalist", { id: "categories" },
    [...new Set(state.dishes.map((d) => d.category))].map((c) => h("option", { value: c })));

  const ingredients = rowList(dish.ingredients, (ing) => h("span", { class: "ingredient-row" },
    h("input", { type: "text", class: "amount-input", placeholder: "Amount", value: ing ? ing.amount : "",
      "aria-label": "Amount" }),
    h("input", { type: "text", class: "name-input", placeholder: "Ingredient", value: ing ? ing.name : "",
      "aria-label": "Ingredient name" })), "+ Ingredient");
  const steps = rowList(dish.steps, (step) => {
    const box = h("textarea", { rows: 2, placeholder: "Describe this step", "aria-label": "Step" });
    box.value = step || "";
    return box;
  }, "+ Step");

  const errors = h("div");
  const title = isNew ? "New dish" : isSeed ? `Your version of ${dish.name}` : `Edit ${dish.name}`;

  const form = h("form", { class: "dish-form", novalidate: true, onsubmit: async (event) => {
    event.preventDefault();
    const payload = {
      ingredients: [...ingredients.list.children].map((row) => ({
        amount: row.querySelector(".amount-input").value,
        name: row.querySelector(".name-input").value,
      })),
      steps: [...steps.list.children].map((row) => row.querySelector("textarea").value),
    };
    if (!isSeed) {
      Object.assign(payload, {
        name: name.value, description: description.value, category: category.value,
        servings: servings.value === "" ? null : Number(servings.value),
        total_minutes: minutes.value === "" ? null : Number(minutes.value),
      });
    }
    try {
      let id = view && dish.id, warnings;
      if (isNew) ({ id, warnings } = await api("POST", "/api/dishes", payload));
      else ({ warnings } = await api("PUT", dishPath(id), payload));
      await loadDishes();
      await openDish(id, warnings.length ? notice(warnings.join(" ")) : null);
    } catch (error) {
      errors.replaceChildren(errorBox(error.messages || [error.message]));
      errors.scrollIntoView({ block: "nearest" });
    }
  } },
    h("h2", { text: title }),
    isSeed ? h("p", { class: "hint", text: "Your changes are saved as your own version. The original recipe stays available, and you can revert any time." }) : null,
    errors,
    isSeed ? null : h("div", { class: "grid" },
      field("Name", name), field("Category", category), field("Description", description),
      field("Servings", servings), field("Total time (minutes)", minutes), categories),
    h("h3", { text: "Ingredients" }), ingredients.element,
    h("h3", { text: "Steps" }), steps.element,
    h("div", { class: "actions" },
      h("button", { type: "submit", class: "primary", text: "Save" }),
      h("button", { type: "button", text: "Cancel",
        onclick: () => (isNew ? showMain(h("div", { class: "empty", text: "Cancelled." })) : openDish(dish.id)) })),
  );
  showMain(form);
  (isSeed ? form.querySelector(".name-input") : name).focus();
}

// -- wiring -----------------------------------------------------------------------

function start() {
  document.getElementById("tab-dishes").addEventListener("click", () => selectTab("dishes"));
  document.getElementById("tab-search").addEventListener("click", () => selectTab("search"));
  document.getElementById("filter").addEventListener("input", renderDishList);
  document.getElementById("show-hidden").addEventListener("change", loadDishes);
  document.getElementById("search-form").addEventListener("submit", runSearch);
  document.getElementById("new-dish").addEventListener("click", () => {
    state.selected = null;
    renderDishList();
    renderForm(null);
  });
  window.addEventListener("unhandledrejection", (event) => {
    const error = event.reason || {};
    showBanner(error.messages || [error.message || "Something went wrong."]);
  });
  loadDishes();
}

start();
