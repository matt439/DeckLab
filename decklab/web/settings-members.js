/* Member setup and emails are private to this home-admin Settings panel. No roster or browser storage. */
"use strict";

function settingsMembersAdmin() {
  return Boolean(state.profile?.id) && state.profile.role === "admin" && state.profile.space === HOME_SPACE;
}

function settingsMembersPanel() {
  if (!settingsMembersAdmin()) return null;
  return el("section", { class: "panel settings-part", id: "settings-members", "aria-labelledby": "settings-members-title" },
    el("h2", { id: "settings-members-title", text: "Members" }),
    el("p", { class: "sub", text: "Add a member with their own space, or replace one of an existing member's sign-in emails." }),
    el("div", { id: "settings-members-content" }, loadingBox("Loading member emails…")));
}

function settingsMemberEmail(value) {
  if (typeof value !== "string") return null;
  const raw = value.trim();
  if (!/^[\x21-\x7e]+$/.test(raw) || raw.length > 254) return null;
  const email = raw.toLowerCase(), parts = email.split("@");
  if (parts.length !== 2) return null;
  const [local, domain] = parts;
  return local.length >= 1 && local.length <= 64 && /^[a-z0-9.!#$%&'*+/=?^_`{|}~-]+$/.test(local)
    && !local.startsWith(".") && !local.endsWith(".") && !local.includes("..")
    && domain.length <= 253 && domain.includes(".")
    && domain.split(".").every(label => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label)) ? email : null;
}

function settingsMembersHash(value) { return typeof value === "string" && /^[a-f0-9]{64}$/.test(value); }

function settingsMemberSaveFailure(failure) {
  const reload = "Reload member emails before reviewing another change.";
  if (failure?.status === 409) return "The saved member settings changed. Your entries are still here. " + reload;
  const reason = typeof failure?.message === "string" ? failure.message.trim() : "";
  if (failure?.status === 400 && reason && reason.length <= 500) return reason + " Your entries are still here. " + reload;
  return "The save couldn't be confirmed. " + reload;
}

function settingsMemberId(value) {
  return typeof value === "string" && value.length <= 40 && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value)
    && !["home", "system", "test", "claude", "casual", "commander", "product", "pairing", "people"].includes(value);
}

function settingsMembersRows(value) {
  if (!Array.isArray(value) || value.length > 1000) return null;
  const ids = new Set(), emails = new Set();
  for (const member of value) {
    if (!member || typeof member !== "object" || !settingsMemberId(member.id)
        || ids.has(member.id) || typeof member.name !== "string" || !member.name.trim()
        || !Array.isArray(member.emails) || !member.emails.length || member.emails.length > 100) return null;
    ids.add(member.id);
    for (const email of member.emails) {
      if (settingsMemberEmail(email) !== email || emails.has(email)) return null;
      emails.add(email);
    }
  }
  return value.map(member => ({ id: member.id, name: member.name, emails: [...member.emails] }));
}

async function loadSettingsMembers(token) {
  const host = byId("settings-members-content"), profile = state.profile;
  if (!host || !settingsMembersAdmin()) return;
  const sequence = host.memberRequest = (host.memberRequest || 0) + 1;
  const here = () => host.isConnected && byId("settings-members-content") === host && token === routeToken
    && sequence === host.memberRequest && state.profile === profile && settingsMembersAdmin() && parseHash().path === "settings";
  clear(host).append(loadingBox("Loading member emails…"));
  try {
    const data = await api("/api/settings/members");
    if (!here()) return;
    const members = settingsMembersRows(data?.members);
    if (data?.editable !== true || !settingsMembersHash(data.config_sha256) || !settingsMembersHash(data.membership_sha256) || !members)
      throw new Error("The member list couldn't be verified.");
    drawSettingsMembers(host, data, members, token, profile, here);
  } catch (error) {
    if (!here()) return;
    clear(host).append(el("p", { class: "form-error", role: "alert", text: "Member emails couldn't be loaded. Reload this panel to try again." }),
      el("button", { type: "button", class: "btn btn-secondary", text: "Reload member emails", onclick: () => { if (here()) loadSettingsMembers(token); } }));
  }
}

/** All fetched addresses and request receipts stay inside this form's lifetime. */
function drawSettingsMembers(host, data, members, token, profile, owner) {
  if (!members.length) {
    const empty = emptyBox("No members have their own space and an email yet.", el("button", { type: "button", class: "btn btn-secondary", text: "Add member", onclick: () => {
      if (owner() && empty.isConnected && host.contains(empty)) drawSettingsMemberAdd(host, data, members, token, profile, owner);
    } }));
    clear(host).append(empty);
    return;
  }
  let reviewed = null, pending = false, retired = false;
  const form = el("form", { class: "settings-fields settings-members-form", autocomplete: "off", onsubmit: event => {
    event.preventDefault(); review();
  } });
  const here = () => owner() && form.isConnected && host.contains(form);
  const person = el("select", { id: "settings-member-id" }, members.map(member => el("option", { value: member.id, text: member.name })));
  person.value = members[0].id;
  const old = el("select", { id: "settings-member-old-email" });
  const next = el("input", { id: "settings-member-new-email", type: "email", autocomplete: "off", spellcheck: "false",
    autocapitalize: "none", maxlength: 254, "aria-describedby": "settings-member-email-hint" });
  const error = el("p", { class: "form-error", role: "alert" });
  const status = el("p", { class: "sub", role: "status" });
  const preview = el("div", { class: "box box-info settings-member-review", hidden: true });
  const reviewButton = el("button", { type: "button", class: "btn btn-secondary", text: "Review email change", onclick: review });
  const save = el("button", { type: "button", class: "btn btn-primary", text: "Save email change", hidden: true, onclick: commit });
  const reload = el("button", { type: "button", class: "btn btn-secondary", text: "Reload member emails", hidden: true,
    onclick: () => { if (here() && !pending) loadSettingsMembers(token); } });
  const addMember = el("button", { type: "button", class: "btn btn-secondary", text: "Add member", onclick: () => {
    if (here() && !pending && !retired) drawSettingsMemberAdd(host, data, members, token, profile, owner);
  } });
  const field = (label, control) => el("label", { class: "field", for: control.id }, el("span", { text: label }), control);
  const selected = () => members.find(member => member.id === person.value);
  const reset = () => {
    if (!here() || pending || retired) return;
    reviewed = null; preview.hidden = true; clear(preview); save.hidden = true; error.textContent = ""; status.textContent = "";
  };
  const aliases = () => {
    const member = selected(); clear(old);
    if (member) old.append(...member.emails.map(email => el("option", { value: email, text: email })));
    old.value = member?.emails[0] || "";
  };
  person.addEventListener("change", () => { if (!here() || pending || retired) return; reset(); aliases(); next.value = ""; });
  old.addEventListener("change", reset); next.addEventListener("input", reset);
  form.append(field("Member", person), field("Email to replace", old), field("New sign-in email", next),
    el("p", { class: "field-hint", id: "settings-member-email-hint", text: "Use the exact address the member will use to sign in. Saving also needs a separate Cloudflare Access policy update." }),
    error, status, preview, el("div", { class: "actions" }, reviewButton, save, reload, addMember));
  aliases(); clear(host).append(form);

  function review() {
    if (!here() || pending || retired) return;
    const member = selected(), email = settingsMemberEmail(next.value);
    if (!member || !member.emails.includes(old.value) || !email) {
      error.textContent = "Choose an existing member email and enter a valid new email address."; return;
    }
    if (members.some(row => row.id !== member.id && row.emails.includes(email)) || member.emails.some(alias => alias === email && alias !== old.value)) {
      error.textContent = "That email is already listed. Choose a different address."; return;
    }
    reviewed = { member, oldEmail: old.value, newEmail: email };
    error.textContent = ""; status.textContent = "Review this exact replacement before saving.";
    clear(preview).append(el("p", {}, el("strong", { text: member.name })),
      el("p", {}, el("strong", { text: "Replace: " }), old.value),
      el("p", {}, el("strong", { text: "With: " }), email),
      el("p", { text: "Other aliases, their space and their records stay as they are." }));
    preview.hidden = false; save.hidden = false;
  }

  function receipt(reply, request) {
    const member = settingsMembersRows([reply?.member])?.[0];
    const expected = request.member.emails.map(email => email === request.oldEmail ? request.newEmail : email).sort();
    if (!member || member.id !== request.member.id || member.name !== request.member.name
        || JSON.stringify([...member.emails].sort()) !== JSON.stringify(expected)
        || reply.replaced?.old_email !== request.oldEmail || reply.replaced?.new_email !== request.newEmail
        || !settingsMembersHash(reply.config_sha256) || !settingsMembersHash(reply.membership_sha256)
        || reply.access_policy_required !== true) return false;
    if (request.oldEmail === request.newEmail) return reply.saved === false && reply.noop === true && reply.change_set_id === null
      && reply.config_sha256 === data.config_sha256 && reply.membership_sha256 === data.membership_sha256;
    return reply.saved === true && reply.noop === false && Number.isSafeInteger(reply.change_set_id) && reply.change_set_id > 0
      && reply.config_sha256 !== data.config_sha256 && reply.membership_sha256 !== data.membership_sha256;
  }

  async function commit() {
    if (!here() || pending || retired || !reviewed) return;
    const request = reviewed;
    if (person.value !== request.member.id || old.value !== request.oldEmail || settingsMemberEmail(next.value) !== request.newEmail) {
      reset(); error.textContent = "The form changed. Review the replacement again."; return;
    }
    pending = true; error.textContent = ""; status.textContent = "Saving email change.";
    for (const control of [person, old, next, reviewButton, save, reload, addMember]) control.disabled = true;
    try {
      const reply = await apiWrite("/api/settings/member-email", { profile: profile.id, member_id: request.member.id,
        old_email: request.oldEmail, new_email: request.newEmail, config_sha256: data.config_sha256,
        membership_sha256: data.membership_sha256 }, "POST");
      if (!here()) return;
      if (!receipt(reply, request)) throw new Error("Unverified receipt");
      retired = true; preview.hidden = true; clear(preview); reviewButton.hidden = true; save.hidden = true;
      status.textContent = reply.noop ? "This email is already recorded. No change was saved." : "Member email change saved.";
      form.append(el("div", { class: "box box-info settings-member-result" },
        el("p", {}, "Add ", el("strong", { text: request.newEmail }), " to the Cloudflare Access policy, then check sign-in with that address."),
        el("p", { text: "Deck Lab hasn't verified the Access policy or the member's sign-in." })));
    } catch (failure) {
      if (!here()) return;
      retired = true; status.textContent = "";
      error.textContent = settingsMemberSaveFailure(failure);
      reviewButton.hidden = true; save.hidden = true;
    } finally {
      pending = false;
      if (here()) { reload.hidden = false; reload.disabled = false; }
    }
  }
}

/** A new member has a permanent id and an empty private space; no home/admin choices are offered. */
function drawSettingsMemberAdd(host, data, members, token, profile, owner) {
  let reviewed = null, pending = false, retired = false;
  const form = el("form", { class: "settings-fields settings-members-form settings-member-add-form", autocomplete: "off",
    onsubmit: event => { event.preventDefault(); review(); } });
  const here = () => owner() && form.isConnected && host.contains(form);
  const name = el("input", { id: "settings-member-add-name", type: "text", maxlength: 240, autocomplete: "off" });
  const id = el("input", { id: "settings-member-add-id", type: "text", maxlength: 40, autocomplete: "off", spellcheck: "false",
    autocapitalize: "none", "aria-describedby": "settings-member-add-id-hint" });
  const email = el("input", { id: "settings-member-add-email", type: "email", maxlength: 254, autocomplete: "off", spellcheck: "false", autocapitalize: "none" });
  const error = el("p", { class: "form-error", role: "alert" }), status = el("p", { class: "sub", role: "status" });
  const preview = el("div", { class: "box box-info settings-member-review", hidden: true });
  const reviewButton = el("button", { type: "button", class: "btn btn-secondary", text: "Review new member", onclick: review });
  const save = el("button", { type: "button", class: "btn btn-primary", text: "Save new member", hidden: true, onclick: commit });
  const reload = el("button", { type: "button", class: "btn btn-secondary", text: "Reload member emails", hidden: true,
    onclick: () => { if (here() && !pending) loadSettingsMembers(token); } });
  const back = el("button", { type: "button", class: "btn btn-quiet", text: "Back to email changes", onclick: () => {
    if (!here() || pending || retired) return;
    drawSettingsMembers(host, data, members, token, profile, owner);
    if (owner()) byId("settings-member-id")?.focus();
  } });
  const field = (label, control) => el("label", { class: "field", for: control.id }, el("span", { text: label }), control);
  const reset = () => {
    if (!here() || pending || retired) return;
    reviewed = null; preview.hidden = true; clear(preview); save.hidden = true; error.textContent = ""; status.textContent = "";
  };
  for (const input of [name, id, email]) input.addEventListener("input", reset);
  form.append(el("h3", { text: "Add a member" }), field("Display name", name), field("Permanent member id", id),
    el("p", { class: "field-hint", id: "settings-member-add-id-hint", text: "Use lowercase letters, numbers and single hyphens, up to 40 characters. This id also names the member's own space and can't be changed here." }),
    field("Sign-in email", email), el("p", { class: "sub", text: "The new member starts with an empty space. Its collection, decks and games start Private." }),
    error, status, preview, el("div", { class: "actions" }, reviewButton, save, reload, back));
  clear(host).append(form); if (here()) name.focus();

  function entered() {
    return { member_id: id.value.trim(), name: name.value.trim(), email: settingsMemberEmail(email.value) };
  }

  function review() {
    if (!here() || pending || retired) return;
    const request = entered();
    if (!request.name || [...request.name].length > 120 || /[\x00-\x1f\x7f]/.test(request.name)) {
      error.textContent = "Enter a display name of up to 120 characters on one line."; return;
    }
    if (!settingsMemberId(request.member_id)) {
      error.textContent = "Choose a non-reserved member id using lowercase letters, numbers and single hyphens, up to 40 characters."; return;
    }
    if (!request.email) { error.textContent = "Enter a valid sign-in email address."; return; }
    if (members.some(member => member.id === request.member_id || member.emails.includes(request.email))) {
      error.textContent = "That member id or email is already listed. Choose a different one."; return;
    }
    reviewed = request; error.textContent = ""; status.textContent = "Review this member before saving.";
    clear(preview).append(el("p", {}, el("strong", { text: "Name: " }), request.name),
      el("p", {}, el("strong", { text: "Permanent id and own space: " }), request.member_id),
      el("p", {}, el("strong", { text: "Sign-in email: " }), request.email),
      el("p", { text: "Role: Member. The space starts empty, with collection, decks and games set to Private." }));
    preview.hidden = false; save.hidden = false;
  }

  function receipt(reply, request) {
    const member = settingsMembersRows([reply?.member])?.[0];
    return Boolean(member && member.id === request.member_id && member.name === request.name
      && member.emails.length === 1 && member.emails[0] === request.email && reply.saved === true && reply.noop === false
      && settingsMembersHash(reply.config_sha256) && reply.config_sha256 !== data.config_sha256
      && settingsMembersHash(reply.membership_sha256) && reply.membership_sha256 !== data.membership_sha256
      && Number.isSafeInteger(reply.change_set_id) && reply.change_set_id > 0 && reply.access_policy_required === true);
  }

  async function commit() {
    if (!here() || pending || retired || !reviewed) return;
    const request = reviewed;
    if (JSON.stringify(entered()) !== JSON.stringify(request)) {
      reset(); error.textContent = "The form changed. Review the member again."; return;
    }
    pending = true; error.textContent = ""; status.textContent = "Adding member.";
    for (const control of [name, id, email, reviewButton, save, reload, back]) control.disabled = true;
    try {
      const reply = await apiWrite("/api/settings/member", { profile: profile.id, ...request,
        config_sha256: data.config_sha256, membership_sha256: data.membership_sha256 }, "POST");
      if (!here()) return;
      if (!receipt(reply, request)) throw new Error("Unverified receipt");
      retired = true; preview.hidden = true; clear(preview); reviewButton.hidden = true; save.hidden = true;
      status.textContent = "Member added.";
      form.append(el("div", { class: "box box-info settings-member-result" },
        el("p", {}, el("strong", { text: request.name }), " now has the private space ", el("strong", { text: request.member_id }), "."),
        el("p", {}, "Add ", el("strong", { text: request.email }), " to the Cloudflare Access policy, then check sign-in with that address."),
        el("p", { text: "Deck Lab hasn't verified the Access policy or the member's sign-in." })));
    } catch (failure) {
      if (!here()) return;
      retired = true; status.textContent = ""; reviewButton.hidden = true; save.hidden = true;
      error.textContent = settingsMemberSaveFailure(failure);
    } finally {
      pending = false;
      if (here()) { reload.hidden = false; reload.disabled = false; }
    }
  }
}
