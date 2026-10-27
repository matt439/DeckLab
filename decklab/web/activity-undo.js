/* One explicitly reviewed inverse inventory edit. Audit display rows are never write authority. */
"use strict";

const ACTIVITY_UNDO_FIELDS = {
  collection: ["name", "set", "collector_number", "finish", "quantity", "condition", "language", "notes"],
  tokens: ["front", "back", "set", "front_collector_number", "back_collector_number", "finish", "quantity", "front_details", "back_details", "notes"],
  wishlist: ["name", "set", "number", "notes", "source"],
  accessory: ["id", "kind", "owner", "brand", "name", "colour", "notes", "link", "image_source", "capacity"],
};
const ACTIVITY_UNDO_EDITABLE = { collection: ["quantity", "condition", "language", "notes"], tokens: ["quantity", "notes"], wishlist: ["set", "number", "notes", "source"], accessory: ["brand", "name", "colour", "notes", "link", "image_source", "capacity"] };
const ACTIVITY_UNDO_ACCESSORY_QUANTITY_FIELDS = [...ACTIVITY_UNDO_FIELDS.accessory, "quantity"];
const ACTIVITY_UNDO_ACCESSORY_STOCK_FIELDS = ["id", "kind", "owner", "brand", "name", "colour", "notes", "link", "image_source", "quantity", "capacity", "image", "crop"];

function activityUndoRow(row, kind) {
  if (!["collection", "tokens", "wishlist", "accessory"].includes(kind)) return false;
  const fields = ACTIVITY_UNDO_FIELDS[kind];
  return fields && row && typeof row === "object" && !Array.isArray(row)
    && Object.keys(row).sort().join(",") === [...fields].sort().join(",")
    && fields.every(field => field === "quantity" ? Number.isSafeInteger(row[field]) && row[field] > 0 && row[field] <= 9999 : typeof row[field] === "string")
    && Boolean((row.name || row.front || "").trim());
}

function activityUndoBatchKey(key, row = null) {
  const fields = ["set", "collector_number", "finish"];
  if (!key || typeof key !== "object" || Array.isArray(key) || Object.keys(key).sort().join(",") !== "collector_number,finish,set"
      || fields.some(field => typeof key[field] !== "string" || !key[field] || row && key[field] !== row[field])) return null;
  return JSON.stringify(fields.map(field => key[field]));
}

function activityUndoBatchEvidence(data) {
  const stock = data.action === "batch_update";
  if (!["batch_metadata", "batch_update"].includes(data.action) || data.kind !== "collection" || !Number.isSafeInteger(data.row_count) || data.row_count < 2 || data.row_count > 50
      || !Array.isArray(data.rows) || data.rows.length !== data.row_count
      || Object.keys(data).sort().join(",") !== "action,available,expect,id,kind,label,row_count,rows,space") return false;
  const keys = new Set(), allowed = stock ? ["quantity", "condition", "language", "notes"] : ["condition", "language", "notes"];
  let quantityChanged = false;
  for (const item of data.rows) {
    if (!item || typeof item !== "object" || Object.keys(item).sort().join(",") !== "current,fields,key,label,restored"
        || typeof item.label !== "string" || !item.label.trim() || !activityUndoRow(item.current, "collection") || !activityUndoRow(item.restored, "collection")) return false;
    const key = activityUndoBatchKey(item.key, item.current);
    if (!key || keys.has(key)) return false;
    keys.add(key);
    const changed = ACTIVITY_UNDO_FIELDS.collection.filter(field => item.current[field] !== item.restored[field]);
    if (!changed.length || changed.some(field => !allowed.includes(field)) || !Array.isArray(item.fields)
        || item.fields.length !== changed.length || new Set(item.fields.map(field => field?.field)).size !== changed.length
        || [...item.fields].some(field => !field || Object.keys(field).sort().join(",") !== "after,before,field" || !changed.includes(field.field)
          || field.before !== item.current[field.field] || field.after !== item.restored[field.field])) return false;
    quantityChanged = quantityChanged || changed.includes("quantity");
  }
  return stock === quantityChanged;
}

function activityUndoPhysicalBatchEvidence(data) {
  const adding = data.action === "batch_add", flag = adding ? "physical_confirmation_required" : "reason_required";
  if (!["batch_add", "batch_remove"].includes(data.action) || data.kind !== "collection" || data[flag] !== true
      || !Number.isSafeInteger(data.row_count) || data.row_count < 2 || data.row_count > 50
      || !Array.isArray(data.rows) || data.rows.length !== data.row_count
      || Object.keys(data).sort().join(",") !== ["action", "available", "expect", "id", "kind", "label", flag, "row_count", "rows", "space"].sort().join(",")) return false;
  const keys = new Set();
  for (const item of data.rows) {
    const row = adding ? item?.restored : item?.current;
    if (!item || typeof item !== "object" || Object.keys(item).sort().join(",") !== "current,key,label,restored"
        || item[adding ? "current" : "restored"] !== null || typeof item.label !== "string" || !item.label.trim() || !activityUndoRow(row, "collection")) return false;
    const key = activityUndoBatchKey(item.key, row);
    if (!key || keys.has(key)) return false;
    keys.add(key);
  }
  return true;
}

function activityUndoWishlistEvidence(data, profile) {
  const adding = data.action === "wishlist_add", removing = data.action === "wishlist_remove", updating = data.action === "wishlist_update";
  const keys = ["action", "available", "current", "expect", "id", "kind", "label", "profile", "restored", ...(updating ? ["fields"] : [])];
  if (!adding && !removing && !updating || data.profile !== profile || typeof profile !== "string" || !profile
      || Object.keys(data).sort().join(",") !== keys.sort().join(",")) return false;
  const rows = adding ? [data.restored] : removing ? [data.current] : [data.current, data.restored];
  if (rows.some(row => !activityUndoRow(row, "wishlist") || Boolean(row.set) !== Boolean(row.number)
      || row.set && (!/^[a-z0-9]{2,8}$/.test(row.set) || [...row.number].length > 16 || /[\u0000-\u001f\u007f]/.test(row.number)))
      || data.label !== rows[0].name) return false;
  if (adding) return data.current === null;
  if (removing) return data.restored === null;
  if (data.current.name !== data.restored.name) return false;
  const changed = ACTIVITY_UNDO_EDITABLE.wishlist.filter(field => data.current[field] !== data.restored[field]);
  return changed.length > 0 && Array.isArray(data.fields) && data.fields.length === changed.length
    && new Set(data.fields.map(item => item?.field)).size === changed.length
    && [...data.fields].every(item => item && Object.keys(item).sort().join(",") === "after,before,field" && changed.includes(item.field)
      && item.before === data.current[item.field] && item.after === data.restored[item.field]);
}

function activityUndoAccessoryUrl(value, limit) {
  // Match the ordinary Python URL form/whitespace and codepoint limit, without URL normalization.
  return typeof value === "string" && [...value].length <= limit && !/[\u0000\ud800-\udfff]/u.test(value)
    && (value === "" || /^https?:\/\/[^\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/iu.test(value));
}

function activityUndoAccessoryCapacity(row) {
  return typeof row?.capacity === "string" && (row.capacity === "" || row.kind === "deck_box" && /^[1-9][0-9]{0,3}(?![\s\S])/.test(row.capacity));
}

function activityUndoAccessoryQuantity(value) {
  return typeof value === "string" && /^(?:0|[1-9][0-9]{0,3})(?![\s\S])/.test(value);
}

function activityUndoAccessoryCount(row) {
  return row && typeof row === "object" && !Array.isArray(row)
    && Object.keys(row).sort().join(",") === [...ACTIVITY_UNDO_ACCESSORY_QUANTITY_FIELDS].sort().join(",")
    && activityUndoRow(Object.fromEntries(ACTIVITY_UNDO_FIELDS.accessory.map(field => [field, row[field]])), "accessory")
    && activityUndoAccessoryQuantity(row.quantity) && activityUndoAccessoryCapacity(row);
}

function activityUndoAccessoryCrop(value) {
  if (value === "") return [0, 0, 1, 1];
  if (typeof value !== "string" || !/^(?:0|1|0\.\d{1,4})(?:,(?:0|1|0\.\d{1,4})){3}(?![\s\S])/.test(value)) return null;
  const parts = value.split(",").map(Number), [x, y, w, h] = parts;
  if (w < .02 || h < .02 || x + w > 1.00005 || y + h > 1.00005
      || parts.map(n => n.toFixed(4).replace(/0+$/, "").replace(/\.$/, "")).join(",") !== value) return null;
  return parts;
}

function activityUndoAccessoryPhotoRow(row) {
  return row && typeof row === "object" && !Array.isArray(row)
    && Object.keys(row).sort().join(",") === [...ACTIVITY_UNDO_ACCESSORY_STOCK_FIELDS].sort().join(",")
    && ACTIVITY_UNDO_ACCESSORY_STOCK_FIELDS.every(field => typeof row[field] === "string" && !/[\u0000\ud800-\udfff]/u.test(row[field]))
    && activityUndoAccessoryCount(Object.fromEntries(ACTIVITY_UNDO_ACCESSORY_QUANTITY_FIELDS.map(field => [field, row[field]])))
    && row.id.length <= 40 && /^[a-z0-9]+(?:-[a-z0-9]+)*(?![\s\S])/.test(row.id)
    && ["sleeves", "deck_box", "playmat"].includes(row.kind)
    && ["jpg", "png", "webp"].some(ext => row.image === row.id + "." + ext)
    && activityUndoAccessoryCrop(row.crop) !== null
    && activityUndoAccessoryUrl(row.link, 500) && activityUndoAccessoryUrl(row.image_source, 2000);
}

function activityUndoAccessoryPhoto(photo, row) {
  return photo && typeof photo === "object" && !Array.isArray(photo)
    && Object.keys(photo).sort().join(",") === "name,sha256,size,version" && photo.name === row.image
    && Number.isSafeInteger(photo.size) && photo.size > 0 && photo.size <= 4 * 1024 * 1024
    && typeof photo.sha256 === "string" && /^[a-f0-9]{64}(?![\s\S])/.test(photo.sha256)
    && typeof photo.version === "string" && /^[a-f0-9]{8}(?![\s\S])/.test(photo.version);
}

function activityUndoAccessoryCropEvidence(data, space, profile) {
  if (space !== "home" || typeof profile !== "string" || !profile
      || Object.keys(data).sort().join(",") !== "action,available,current,expect,fields,id,kind,label,photo,photo_confirmation_required,restored"
      || data.photo_confirmation_required !== true || !activityUndoAccessoryPhotoRow(data.current) || !activityUndoAccessoryPhotoRow(data.restored)
      || ![profile, "shared"].includes(data.current.owner) || data.label !== data.current.name
      || !activityUndoAccessoryPhoto(data.photo, data.current) || data.current.crop === data.restored.crop
      || ACTIVITY_UNDO_ACCESSORY_STOCK_FIELDS.some(field => field !== "crop" && data.current[field] !== data.restored[field])
      || !Array.isArray(data.fields) || data.fields.length !== 1) return false;
  const field = data.fields[0];
  return field && Object.keys(field).sort().join(",") === "after,before,field" && field.field === "crop"
    && field.before === data.current.crop && field.after === data.restored.crop;
}

function activityUndoAccessoryEvidence(data, space, profile) {
  if (data.action === "accessory_crop_update") return activityUndoAccessoryCropEvidence(data, space, profile);
  const removing = data.action === "accessory_remove", adding = data.action === "accessory_add";
  const counting = data.action === "accessory_stock_update";
  const owning = data.action === "accessory_owner_update", retyping = data.action === "accessory_kind_update", correcting = data.action === "accessory_record_update";
  const recorded = counting || owning || retyping || correcting;
  const stock = removing || adding, row = adding ? data.restored : data.current;
  const keys = ["action", "available", "current", "expect", "id", "kind", "label", "restored", removing ? "reason_required" : adding ? "confirmation_required" : "fields", ...(counting ? ["stock_confirmation_required"] : owning ? ["owner_confirmation_required"] : retyping ? ["kind_confirmation_required"] : correcting ? ["record_confirmation_required"] : [])];
  if ((!stock && !recorded && data.action !== "accessory_update") || space !== "home" || typeof profile !== "string" || !profile
      || Object.keys(data).sort().join(",") !== keys.sort().join(",")
      || (stock ? !activityUndoAccessoryStock(row) : recorded ? !activityUndoAccessoryCount(data.current) || !activityUndoAccessoryCount(data.restored)
        : !activityUndoRow(data.current, "accessory") || !activityUndoRow(data.restored, "accessory"))
      || (stock ? [row] : [data.current, data.restored]).some(item => !activityUndoAccessoryUrl(item.link, 500) || !activityUndoAccessoryUrl(item.image_source, 2000))
      || !stock && [data.current, data.restored].some(item => !activityUndoAccessoryCapacity(item))
      || !row.id.trim() || !["sleeves", "deck_box", "playmat"].includes(row.kind)
      || ![profile, "shared"].includes(row.owner) || data.label !== row.name) return false;
  if (removing) return data.reason_required === true && data.restored === null;
  if (adding) return data.confirmation_required === true && data.current === null;
  if (counting && data.stock_confirmation_required !== true) return false;
  if (owning && (data.owner_confirmation_required !== true || data.current.owner === data.restored.owner
      || ![profile, "shared"].includes(data.restored.owner) || data.current.quantity !== data.restored.quantity)) return false;
  if (retyping && (data.kind_confirmation_required !== true || data.current.kind === data.restored.kind
      || !["sleeves", "deck_box", "playmat"].includes(data.restored.kind) || data.current.quantity !== data.restored.quantity)) return false;
  if (correcting && (data.record_confirmation_required !== true || !["sleeves", "deck_box", "playmat"].includes(data.restored.kind)
      || ![profile, "shared"].includes(data.restored.owner)
      || ["owner", "kind", "quantity"].filter(field => data.current[field] !== data.restored[field]).length < 2)) return false;
  if (["id", ...(!retyping && !correcting ? ["kind"] : []), ...(!owning && !correcting ? ["owner"] : [])].some(field => data.current[field] !== data.restored[field])) return false;
  const allowed = [...(correcting ? ["kind", "owner"] : owning ? ["owner"] : retyping ? ["kind"] : []), ...ACTIVITY_UNDO_EDITABLE.accessory, ...(counting || correcting ? ["quantity"] : [])];
  const changed = allowed.filter(field => data.current[field] !== data.restored[field]);
  return changed.length > 0 && (correcting || counting === changed.includes("quantity") && owning === changed.includes("owner") && retyping === changed.includes("kind")) && Array.isArray(data.fields) && data.fields.length === changed.length
    && new Set(data.fields.map(item => item?.field)).size === changed.length
    && [...data.fields].every(item => item && Object.keys(item).sort().join(",") === "after,before,field" && changed.includes(item.field)
      && item.before === data.current[item.field] && item.after === data.restored[item.field]);
}

function activityUndoAccessoryStock(row) {
  return row && typeof row === "object" && !Array.isArray(row)
    && Object.keys(row).sort().join(",") === [...ACTIVITY_UNDO_ACCESSORY_STOCK_FIELDS].sort().join(",")
    && ACTIVITY_UNDO_ACCESSORY_STOCK_FIELDS.every(field => typeof row[field] === "string")
    && activityUndoRow(Object.fromEntries(ACTIVITY_UNDO_FIELDS.accessory.map(field => [field, row[field]])), "accessory")
    && activityUndoAccessoryQuantity(row.quantity) && row.image === "" && row.crop === ""
    && activityUndoAccessoryCapacity(row);
}

function activityUndoAuditVersion(value) {
  return typeof value === "string" && /^[1-9][0-9]{0,18}$/.test(value) && (value.length < 19 || value <= "9223372036854775807");
}

function activityUndoEvidence(data, id, space, profile = state.profile?.id) {
  if (!data || data.available !== true || data.id !== id
      || typeof data.expect !== "string" || !/^[a-f0-9]{64}$/.test(data.expect)
      || typeof data.label !== "string" || !data.label.trim()) return null;
  if (data.kind === "wishlist") return activityUndoWishlistEvidence(data, profile) ? data : null;
  if (data.kind === "accessory") return activityUndoAccessoryEvidence(data, space, profile) ? data : null;
  if (data.space !== space || !["collection", "tokens"].includes(data.kind)) return null;
  if (["batch_metadata", "batch_update"].includes(data.action)) return activityUndoBatchEvidence(data) ? data : null;
  if (["batch_add", "batch_remove"].includes(data.action)) return activityUndoPhysicalBatchEvidence(data) ? data : null;
  if (data.action === "add") return data.kind === "collection" && data.physical_confirmation_required === true && data.current === null
    && activityUndoRow(data.restored, "collection") && Object.keys(data).sort().join(",") === "action,available,current,expect,id,kind,label,physical_confirmation_required,restored,space" ? data : null;
  if (!activityUndoRow(data.current, data.kind)) return null;
  if (data.action === "remove") {
    if (data.reason_required !== true || data.restored !== null || Object.hasOwn(data, "fields")) return null;
    const keys = Object.keys(data).sort().join(",");
    if (data.kind === "tokens") return Number.isSafeInteger(data.token_row_id) && data.token_row_id > 0
      && keys === "action,available,current,expect,id,kind,label,reason_required,restored,space,token_row_id" ? data : null;
    return keys === "action,available,current,expect,id,kind,label,reason_required,restored,space" ? data : null;
  }
  if (Object.hasOwn(data, "action") || Object.hasOwn(data, "reason_required") || Object.hasOwn(data, "physical_confirmation_required")
      || Object.hasOwn(data, "rows") || Object.hasOwn(data, "row_count") || Object.hasOwn(data, "token_row_id")
      || !activityUndoRow(data.restored, data.kind) || !Array.isArray(data.fields) || !data.fields.length) return null;
  const allowed = ACTIVITY_UNDO_EDITABLE[data.kind], changed = ACTIVITY_UNDO_FIELDS[data.kind].filter(field => data.current[field] !== data.restored[field]);
  if (changed.some(field => !allowed.includes(field)) || changed.length !== data.fields.length
      || new Set(data.fields.map(item => item?.field)).size !== data.fields.length
      || data.fields.some(item => !item || !changed.includes(item.field) || item.before !== data.current[item.field]
        || item.after !== data.restored[item.field])) return null;
  return data;
}

function activityUndoReceipt(answer, preview) {
  if (preview.kind === "accessory") {
    const removing = preview.action === "accessory_remove", adding = preview.action === "accessory_add";
    const counting = preview.action === "accessory_stock_update";
    const owning = preview.action === "accessory_owner_update";
    const retyping = preview.action === "accessory_kind_update";
    const correcting = preview.action === "accessory_record_update";
    const cropping = preview.action === "accessory_crop_update";
    const keys = ["action", "expect", "kind", "restored", "revision", "saved", "sha256", "source_id", "summary", ...(removing ? ["removed_id"] : adding ? ["added_id"] : cropping ? ["photo"] : [])];
    return Boolean(answer && answer.saved === true && answer.source_id === preview.id && answer.expect === preview.expect
      && answer.kind === "accessory" && answer.action === preview.action && ["accessory_update", "accessory_stock_update", "accessory_owner_update", "accessory_kind_update", "accessory_record_update", "accessory_crop_update", "accessory_remove", "accessory_add"].includes(preview.action)
      && Object.keys(answer).sort().join(",") === keys.sort().join(",")
      && typeof answer.sha256 === "string" && /^[a-f0-9]{64}$/.test(answer.sha256) && activityUndoAuditVersion(answer.revision)
      && typeof answer.summary === "string" && answer.summary.trim()
      && (cropping ? activityUndoAccessoryPhotoRow(answer.restored) && activityUndoAccessoryPhoto(answer.photo, answer.restored)
          && ACTIVITY_UNDO_ACCESSORY_STOCK_FIELDS.every(field => answer.restored[field] === preview.restored[field])
          && ["name", "size", "sha256", "version"].every(field => answer.photo[field] === preview.photo[field])
        : removing ? answer.restored === null && answer.removed_id === preview.current.id
        : adding ? answer.added_id === preview.restored.id && activityUndoAccessoryStock(answer.restored)
          && ACTIVITY_UNDO_ACCESSORY_STOCK_FIELDS.every(field => answer.restored[field] === preview.restored[field])
          : counting || owning || retyping || correcting ? activityUndoAccessoryCount(answer.restored) && ACTIVITY_UNDO_ACCESSORY_QUANTITY_FIELDS.every(field => answer.restored[field] === preview.restored[field])
          : activityUndoRow(answer.restored, "accessory") && ACTIVITY_UNDO_FIELDS.accessory.every(field => answer.restored[field] === preview.restored[field])));
  }
  if (preview.kind === "wishlist") {
    const removing = preview.action === "wishlist_remove";
    const keys = ["action", "expect", "kind", "profile", "restored", "revision", "saved", "sha256", "source_id", "summary", ...(removing ? ["removed_name"] : [])];
    const confirmed = answer && answer.saved === true && answer.source_id === preview.id
      && answer.expect === preview.expect && answer.kind === "wishlist" && answer.action === preview.action && answer.profile === preview.profile
      && ["wishlist_add", "wishlist_remove", "wishlist_update"].includes(preview.action)
      && Object.keys(answer).sort().join(",") === keys.sort().join(",")
      && typeof answer.sha256 === "string" && /^[a-f0-9]{64}$/.test(answer.sha256)
      && activityUndoAuditVersion(answer.revision)
      && typeof answer.summary === "string" && answer.summary.trim();
    return Boolean(confirmed && (removing ? answer.restored === null && typeof answer.removed_name === "string" && answer.removed_name === preview.current?.name
      : activityUndoRow(answer.restored, "wishlist") && ACTIVITY_UNDO_FIELDS.wishlist.every(field => answer.restored[field] === preview.restored[field])));
  }
  const confirmed = answer && answer.saved === true && answer.source_id === preview.id && answer.expect === preview.expect
    && answer.kind === preview.kind && answer.space === preview.space && typeof answer.sha256 === "string"
    && /^[a-f0-9]{64}$/.test(answer.sha256) && typeof answer.revision === "string" && answer.revision.trim()
    && typeof answer.summary === "string" && answer.summary.trim();
  if (!confirmed) return false;
  if (!(preview.action === "remove" && preview.kind === "tokens") && Object.hasOwn(answer, "removed_token_row_id")) return false;
  if (preview.action === "batch_remove") {
    if (answer.action !== "batch_remove" || answer.row_count !== preview.row_count || answer.restored !== null
        || !Array.isArray(answer.removed_keys) || answer.removed_keys.length !== preview.row_count
        || ["restored_rows", "added_key", "removed_key"].some(field => Object.hasOwn(answer, field))) return false;
    const expected = new Set(preview.rows.map(item => activityUndoBatchKey(item.key))), seen = new Set();
    for (const raw of answer.removed_keys) {
      const key = activityUndoBatchKey(raw);
      if (!key || !expected.has(key) || seen.has(key)) return false;
      seen.add(key);
    }
    return seen.size === expected.size;
  }
  if (Object.hasOwn(answer, "removed_keys")) return false;
  if (["batch_metadata", "batch_update", "batch_add"].includes(preview.action)) {
    if (answer.action !== preview.action || answer.row_count !== preview.row_count || !Array.isArray(answer.restored_rows)
        || answer.restored_rows.length !== preview.row_count || ["restored", "added_key", "removed_key"].some(field => Object.hasOwn(answer, field))) return false;
    const expected = new Map(preview.rows.map(item => [activityUndoBatchKey(item.key), item.restored])), seen = new Set();
    for (const item of answer.restored_rows) {
      if (!item || typeof item !== "object" || Object.keys(item).sort().join(",") !== "key,row" || !activityUndoRow(item.row, "collection")) return false;
      const key = activityUndoBatchKey(item.key, item.row), row = expected.get(key);
      if (!key || !row || seen.has(key) || ACTIVITY_UNDO_FIELDS.collection.some(field => item.row[field] !== row[field])) return false;
      seen.add(key);
    }
    return seen.size === expected.size;
  }
  if (Object.hasOwn(answer, "row_count") || Object.hasOwn(answer, "restored_rows")) return false;
  if (preview.action === "add") {
    const key = answer.added_key;
    return preview.kind === "collection" && answer.action === "add" && !Object.hasOwn(answer, "removed_key")
      && activityUndoRow(answer.restored, "collection") && ACTIVITY_UNDO_FIELDS.collection.every(field => answer.restored[field] === preview.restored[field])
      && key && typeof key === "object" && !Array.isArray(key) && Object.keys(key).sort().join(",") === "collector_number,finish,set"
      && ["set", "collector_number", "finish"].every(field => key[field] === preview.restored[field]);
  }
  if (preview.action === "remove") {
    if (answer.action !== "remove" || Object.hasOwn(answer, "added_key") || answer.restored !== null) return false;
    if (preview.kind === "tokens") return !Object.hasOwn(answer, "removed_key") && Number.isSafeInteger(answer.removed_token_row_id)
      && answer.removed_token_row_id > 0 && answer.removed_token_row_id === preview.token_row_id;
    const key = answer.removed_key;
    return preview.kind === "collection" && key && typeof key === "object" && !Array.isArray(key)
      && Object.keys(key).sort().join(",") === "collector_number,finish,set"
      && ["set", "collector_number", "finish"].every(field => key[field] === preview.current[field]);
  }
  return !Object.hasOwn(answer, "action") && !Object.hasOwn(answer, "removed_key") && !Object.hasOwn(answer, "added_key") && activityUndoRow(answer.restored, preview.kind)
    && ACTIVITY_UNDO_FIELDS[preview.kind].every(field => answer.restored[field] === preview.restored[field]);
}

function activityUndoRemovalReason(value) {
  if (typeof value !== "string" || [...value].length > 200) return null;
  const reason = value.replace(/\p{Cf}/gu, "").replace(/[\p{White_Space}\u001c-\u001f]+/gu, " ").trim();
  return reason && !/[\u0000-\u001f\u007f]/.test(reason) ? reason : null;
}

function activityUndoOwner(ctx) {
  const view = ctx.view;
  return view.undoCtx === ctx && ctx.profile === state.profile?.id && ctx.space === ownSpace()
    && ctx.token === routeToken && view.token === ctx.token && view.profile === ctx.profile
    && ctx.hash === location.hash && view.hash === ctx.hash && JSON.stringify(view.filter) === ctx.filterSignature
    && view.days === ctx.root && ctx.root.isConnected && view.seq === ctx.seq;
}

function activityUndoButton(view, change) {
  if (change.undo?.review !== true || !Number.isSafeInteger(change.id) || change.id < 1) return null;
  const id = change.id, root = view.days, endpoint = change.undo.kind === "wishlist" ? "/api/activity/wishlist-undo"
    : change.undo.kind === "accessory" ? "/api/activity/accessory-undo" : "/api/activity/undo";
  const button = el("button", { type: "button", class: "btn btn-quiet activity-review-undo", text: "Review undo", onclick: () => {
    if (view.undoBusy || view.undoRefreshNeeded || view.undoCtx || view.older?.disabled || root !== view.days || !root.isConnected
        || !button.isConnected || !root.contains(button) || view.token !== routeToken || view.profile !== state.profile?.id
        || view.hash !== location.hash || document.querySelector("dialog[open]")) return;
    openActivityUndo(view, id, endpoint);
  } });
  return button;
}

/** Verify one current image, then display both recorded crops from its same local bytes. */
function activityUndoPhotoPreview(ctx, frames, changed) {
  const preview = ctx.preview, signature = JSON.stringify(preview), controller = new AbortController();
  const photo = { ready: false, failed: false, url: null, images: [] };
  let active = true;
  const current = () => active && ctx.current() && ctx.preview === preview && JSON.stringify(preview) === signature;
  const release = () => {
    if (!active) return;
    active = false; controller.abort(); photo.ready = false;
    for (const img of photo.images) { img.onload = null; img.onerror = null; img.removeAttribute("src"); }
    for (const frame of frames) frame.box.style.visibility = "hidden";
    if (photo.url !== null) { URL.revokeObjectURL(photo.url); photo.url = null; }
  };
  ctx.photoRelease = release;
  photo.valid = () => current() && photo.ready && !photo.failed && photo.url !== null && photo.images.length === 2
    && photo.images.every(img => img.isConnected && ctx.sheet.body.contains(img) && img.src === photo.url
      && (!img.currentSrc || img.currentSrc === photo.url) && img.complete && img.naturalWidth > 0 && img.naturalHeight > 0);
  const load = frame => new Promise((resolve, reject) => {
    const img = el("img", { alt: frame.label, decoding: "async" }), [x, y, w, h] = activityUndoAccessoryCrop(frame.crop);
    Object.assign(img.style, { width: `${100 / w}%`, height: `${100 / h}%`, left: `${-100 * x / w}%`, top: `${-100 * y / h}%` });
    const clipped = el("span", { class: "acc-crop" }, img); frame.box.append(clipped); photo.images.push(img);
    const loaded = () => {
      if (!current() || img.src !== photo.url || !img.complete || !img.naturalWidth || !img.naturalHeight) { reject(Error("The photo did not decode.")); return; }
      const ratio = w * img.naturalWidth / (h * img.naturalHeight);
      clipped.style.aspectRatio = String(ratio); clipped.classList.toggle("acc-crop-tall", ratio < 1); resolve();
    };
    const decoding = typeof img.decode === "function";
    img.onload = () => { if (!decoding) loaded(); }; img.onerror = () => reject(Error("The photo did not load.")); img.src = photo.url;
    if (decoding) Promise.resolve(img.decode()).then(loaded, reject);
    else if (img.complete) loaded();
  });
  Promise.resolve().then(async () => {
    if (!current()) { release(); return; }
    const meta = preview.photo, ext = meta.name.split(".").at(-1), mime = { jpg: "image/jpeg", png: "image/png", webp: "image/webp" }[ext];
    const url = accImgSrc("/accessory-img/" + encodeURIComponent(meta.name) + "?v=" + meta.version);
    const response = await fetch(url, { method: "GET", cache: "no-store", credentials: "same-origin", mode: "same-origin", redirect: "error",
      signal: controller.signal, headers: { Accept: mime, "X-Deck-Lab-Viewer": ctx.profile } });
    if (!current()) { release(); return; }
    if (!response.ok || response.status !== 200 || response.redirected || response.headers.get("ETag") !== '"' + meta.sha256 + '"'
        || response.headers.get("Content-Type")?.split(";")[0].trim().toLowerCase() !== mime
        || response.headers.get("Content-Length") !== String(meta.size) || !response.body?.getReader) throw Error("The current photo could not be verified.");
    const reader = response.body.getReader(), chunks = []; let size = 0;
    try {
      while (true) {
        const part = await reader.read();
        if (!current()) { release(); return; }
        if (part.done) break;
        if (!(part.value instanceof Uint8Array)) throw Error("The photo stream could not be checked.");
        size += part.value.byteLength;
        if (size > meta.size || size > 4 * 1024 * 1024) { controller.abort(); throw Error("The photo is too large."); }
        chunks.push(part.value);
      }
    } finally { reader.releaseLock?.(); }
    if (size !== meta.size) throw Error("The photo is incomplete.");
    const blob = new Blob(chunks, { type: mime });
    if (blob.size !== meta.size) throw Error("The photo blob could not be checked.");
    if (!current()) { release(); return; }
    const objectUrl = URL.createObjectURL(blob);
    if (typeof objectUrl !== "string" || !objectUrl.startsWith("blob:")) throw Error("The photo preview could not be created.");
    photo.url = objectUrl;
    await Promise.all(frames.map(load));
    if (!current()) { release(); return; }
    if (photo.images[0].naturalWidth !== photo.images[1].naturalWidth || photo.images[0].naturalHeight !== photo.images[1].naturalHeight) throw Error("The photo views disagree.");
    for (const frame of frames) frame.box.style.visibility = "";
    photo.ready = true; changed();
  }).catch(() => {
    if (!current()) { release(); return; }
    photo.failed = true; release(); changed();
  });
  return photo;
}

function openActivityUndo(view, id, endpoint = "/api/activity/undo") {
  if (!["/api/activity/undo", "/api/activity/wishlist-undo", "/api/activity/accessory-undo"].includes(endpoint)) return null;
  const ctx = { view, id, endpoint, root: view.days, seq: view.seq, profile: state.profile?.id, space: ownSpace(), token: routeToken,
    hash: location.hash, filter: { ...view.filter }, filterSignature: JSON.stringify(view.filter),
    pending: false, saved: false, needsRefresh: false, refreshing: false, refreshed: false, preview: null };
  view.undoCtx = ctx; view.undoBusy = true;
  const sheet = ctx.sheet = colOpenSheet("Review undo", { wide: true, onClose: () => {
    ctx.photoRelease?.();
    if (!activityUndoOwner(ctx) || ctx.pending) return;
    if (ctx.saved || ctx.needsRefresh) activityUndoAfterClose(ctx);
    else { view.undoCtx = null; view.undoBusy = false; }
  } });
  ctx.current = () => activityUndoOwner(ctx) && ctx.endpoint === endpoint && !sheet.closed;
  ctx.here = () => ctx.current() && [...document.querySelectorAll("dialog[open]")].at(-1) === sheet.dialog;
  clear(sheet.body).append(loadingBox("Checking whether this change can be undone."));
  sheetActions(sheet, [{ text: "Cancel", onclick: () => sheet.close() }]);
  api(endpoint + "?" + new URLSearchParams({ id })).then(data => {
    if (!ctx.current()) return;
    if (data?.available === false && data.id === id && typeof data.reason === "string") {
      clear(sheet.body).append(el("p", { text: "Undo is not available for this change." }), el("p", { class: "sub", text: data.reason }));
      sheetActions(sheet, [{ text: "Close", onclick: () => sheet.close() }]); return;
    }
    const preview = activityUndoEvidence(data, id, ctx.space, ctx.profile);
    const expectedEndpoint = preview?.kind === "wishlist" ? "/api/activity/wishlist-undo" : preview?.kind === "accessory" ? "/api/activity/accessory-undo" : "/api/activity/undo";
    if (!preview || endpoint !== expectedEndpoint) throw new Error("The Undo preview could not be checked.");
    ctx.preview = preview; activityUndoShow(ctx);
  }).catch(failure => {
    if (!ctx.current()) return;
    clear(sheet.body).append(errorBox("The Undo preview couldn't be loaded", failure, null));
    sheetActions(sheet, [{ text: "Close", onclick: () => sheet.close() }]);
  });
  return sheet;
}

function activityUndoShow(ctx) {
  const { sheet, preview, view, endpoint } = ctx, signature = JSON.stringify(preview);
  const accessoryRemoving = preview.kind === "accessory" && preview.action === "accessory_remove";
  const accessoryAdding = preview.kind === "accessory" && preview.action === "accessory_add";
  const accessoryCounting = preview.kind === "accessory" && preview.action === "accessory_stock_update";
  const accessoryOwning = preview.kind === "accessory" && preview.action === "accessory_owner_update";
  const accessoryRetyping = preview.kind === "accessory" && preview.action === "accessory_kind_update";
  const accessoryCorrecting = preview.kind === "accessory" && preview.action === "accessory_record_update";
  const accessoryCropping = preview.kind === "accessory" && preview.action === "accessory_crop_update";
  const batchRemoving = preview.action === "batch_remove", removing = batchRemoving || accessoryRemoving || preview.action === "remove";
  const batchAdding = preview.action === "batch_add", adding = batchAdding || accessoryAdding || preview.action === "add";
  const wishlistPresence = preview.kind === "wishlist" && ["wishlist_add", "wishlist_remove"].includes(preview.action);
  const stock = preview.action === "batch_update", batch = stock || preview.action === "batch_metadata";
  const words = { quantity: "Quantity", condition: "Condition", language: "Language", notes: "Notes", source: "Source", set: "Set", number: "Collector number", brand: "Brand", name: "Name", colour: "Colour", link: "Product link", image_source: "Recorded image source", capacity: "Box capacity (sleeved cards)", image: "Photo", crop: "Photo crop" };
  if (accessoryCounting) words.quantity = preview.current.kind === "sleeves" ? "Recorded quantity (individual sleeves)" : "Recorded quantity (items)";
  if (accessoryOwning || accessoryCorrecting) words.owner = "Whose";
  if (accessoryRetyping || accessoryCorrecting) words.kind = "Accessory kind";
  if (accessoryCorrecting) words.quantity = "Recorded quantity";
  const identity = accessoryCorrecting ? [] : preview.kind === "wishlist" ? ["name", ...["set", "number"].filter(field => !preview.fields?.some(item => item.field === field))]
    : ACTIVITY_UNDO_FIELDS[preview.kind].filter(field => !ACTIVITY_UNDO_EDITABLE[preview.kind].includes(field) && !(accessoryOwning && field === "owner") && !(accessoryRetyping && field === "kind"));
  const text = value => value === "" ? "Not recorded" : String(value);
  const ownerText = value => value === "shared" ? "Shared (both people at home)" : "Mine (" + (state.profile?.name || value) + ")";
  const kindText = value => ({ sleeves: "Sleeves", deck_box: "Deck box", playmat: "Playmat" })[value];
  const kindCount = row => row.quantity + " " + (row.kind === "sleeves" ? row.quantity === "1" ? "individual sleeve" : "individual sleeves" : row.quantity === "1" ? "item" : "items");
  let reasonInput = null, acceptedReason = "", reviewedReason = null;
  let ownershipInput = null, confirmedOwned = false;
  let photoPreview = null, startPhoto = null;
  clear(sheet.body).append(el("h3", { text: preview.label }));
  if (wishlistPresence) {
    const restoring = preview.action === "wishlist_add", row = restoring ? preview.restored : preview.current;
    sheet.body.append(el("p", { class: "box box-warn", text: restoring ? "Save Undo restores this entry to your wishlist." : "Save Undo removes this entry from your wishlist." }),
      el("p", { class: "sub", text: "Review its saved printing, notes and source below. Saving creates one new audited change; the original change stays in Activity." }),
      el("section", { class: "panel" }, el("h3", { text: restoring ? "Historical wishlist entry to restore" : "Current wishlist entry to remove" }),
        el("dl", {}, ACTIVITY_UNDO_FIELDS.wishlist.flatMap(field => [el("dt", { text: field === "number" ? "collector number" : field }),
          el("dd", { class: ["notes", "source"].includes(field) ? "activity-undo-note" : null, text: text(row[field]) })]))));
  } else if (accessoryCropping) {
    const frames = [["Current crop", preview.current], ["Restored crop", preview.restored]].map(([title, row]) => {
      const box = el("span", { class: "acc-thumb acc-thumb-fill", style: "visibility: hidden" });
      return { box, crop: row.crop, label: title + " on the current photo", panel: el("figure", { class: "panel" },
        el("h4", { text: title }), el("p", { class: "sub", text: row.crop ? "Recorded crop: " + row.crop : "Whole current photo" }), box) };
    });
    const status = el("p", { class: "sub", role: "status", "aria-live": "polite", text: "Checking the current photo before you review its crops." });
    sheet.body.append(el("p", { class: "box box-warn", text: "This restores only the recorded crop on the photo saved now. It cannot recover an earlier photo. Both views below use the same verified current photo; the photo itself, stock and kit stay as they are." }),
      el("p", { class: "sub", text: kindText(preview.current.kind) + " · " + kindCount(preview.current) + " · " + ownerText(preview.current.owner) }),
      status, el("div", { class: "panels activity-undo-photos" }, frames.map(frame => frame.panel)));
    const id = "activity-undo-photo-" + sheet.heading.id;
    ownershipInput = el("input", { id, type: "checkbox", disabled: true }); ownershipInput.checked = false;
    sheet.body.append(el("label", { class: "choice", for: id }, ownershipInput,
      el("span", { text: "I have checked both views and want this crop on the current photo." })));
    ownershipInput.addEventListener("change", () => {
      if (!ctx.here() || ctx.pending || ctx.saved || ctx.needsRefresh || !photoPreview?.valid() || !ownershipInput.isConnected
          || !sheet.body.contains(ownershipInput) || ctx.preview !== preview || JSON.stringify(preview) !== signature) { ownershipInput.checked = confirmedOwned; return; }
      confirmedOwned = ownershipInput.checked === true; ownershipInput.checked = confirmedOwned; error.textContent = ""; actions();
    });
    startPhoto = () => { photoPreview = activityUndoPhotoPreview(ctx, frames, () => {
      if (!ctx.current()) return;
      if (photoPreview.failed) {
        confirmedOwned = false; ctx.needsRefresh = true;
        status.textContent = "The current photo could not be verified. No crop review is available.";
        error.textContent = "Reload Activity before reviewing this crop again.";
      } else status.textContent = "Both views use the verified current photo. Review the crop you want to restore.";
      ownershipInput.checked = confirmedOwned; actions();
    }); };
  } else if (batch) {
    const rows = preview.rows.map(item => {
      const changes = item.fields.map(field => el("p", {}, el("b", { text: words[field.field] + ": " }),
        el("span", { class: field.field === "notes" ? "activity-undo-note" : null, text: text(field.before) }), " → ",
        el("span", { class: field.field === "notes" ? "activity-undo-note" : null, text: text(field.after) })));
      return el("section", { class: "panel activity-undo-batch-row" }, el("h4", { text: item.label }),
        el("p", { class: "sub", text: item.key.set.toUpperCase() + " " + item.key.collector_number + " · " + item.key.finish }), changes);
    });
    if (stock) sheet.body.append(el("p", { class: "box box-warn", text: "Review the current and restored copy counts. Recorded quantities are checked again against cards in use when you save." }));
    sheet.body.append(el("p", { class: "sub", text: "Review all " + plural(preview.row_count, "printing")
      + (stock ? " below. Their recorded quantities and metadata will be restored together in one new audited change; the original change stays in Activity."
        : " below. Their condition, language or notes will be restored together in one new audited change; the original change stays in Activity.") }),
      el("div", { class: "panels" }, rows));
  } else if (removing) {
    const tokenCards = preview.kind === "tokens";
    const copies = batchRemoving ? preview.rows.reduce((sum, item) => sum + item.current.quantity, 0) : preview.current.quantity;
    const warning = accessoryRemoving ? "Undo removes this entire accessory record, including its recorded quantity of " + preview.current.quantity
      + (preview.current.kind === "sleeves" ? " individual sleeves." : Number(preview.current.quantity) === 1 ? " item." : " items.")
      : batchRemoving ? "Undo removes all " + plural(copies, "recorded copy", "recorded copies") + " across all " + plural(preview.row_count, "printing") + ". Every added row will be removed together."
      : tokenCards ? "Undo removes all " + plural(preview.current.quantity, "physical token card") + " recorded in this row."
      + (preview.current.back.trim() ? " Each front/back pair is one physical card." : "")
      : "Undo removes all " + plural(preview.current.quantity, "recorded copy", "recorded copies")
        + " of this printing from the collection. The entire added row will be removed.";
    sheet.body.append(el("p", { class: "box box-warn", text: warning }),
    el("p", { class: "sub", text: "Saving creates one new audited change; the original change stays in Activity. "
      + (accessoryRemoving ? "Only an unused added record without a photo can be removed here. Deck and product references are checked again when you save; kit and photos stay as they are."
        : batchRemoving ? "The rows and their physical uses are checked again when you save." : "The row and its physical uses are checked again when you save.") }));
    const currentRow = row => el("dl", {}, (accessoryRemoving ? ACTIVITY_UNDO_ACCESSORY_STOCK_FIELDS : ACTIVITY_UNDO_FIELDS[preview.kind]).flatMap(field => [el("dt", { text: accessoryRemoving && words[field] ? words[field] : field.replaceAll("_", " ") }),
      el("dd", { class: ["notes", "link", "image_source"].includes(field) ? "activity-undo-note" : null,
        text: accessoryRemoving && field === "owner" ? row.owner === "shared" ? "Shared" : state.profile?.name || row.owner
          : accessoryRemoving && field === "kind" ? { sleeves: "Sleeves", deck_box: "Deck box", playmat: "Playmat" }[row.kind] : text(row[field]) })]));
    if (batchRemoving) sheet.body.append(el("p", { class: "sub", text: "Review every current row below. There is no partial selection." }),
      el("div", { class: "panels" }, preview.rows.map(item => el("section", { class: "panel activity-undo-batch-row" },
        el("h4", { text: item.label }), currentRow(item.current)))));
    else sheet.body.append(el("section", { class: "panel" }, el("h3", { text: accessoryRemoving ? "Current accessory record to remove" : tokenCards ? "Current token-card row to remove" : "Current row to remove" }), currentRow(preview.current)));
    const id = "activity-undo-reason-" + sheet.heading.id;
    reasonInput = el("input", { id, type: "text", maxlength: 400, autocomplete: "off", "aria-describedby": id + "-hint" });
    const normalized = el("p", { class: "sub", role: "status", "aria-live": "polite" });
    sheet.body.append(el("label", { class: "field", for: id }, el("span", { text: accessoryRemoving
      ? "Reason for removing this added accessory record (required)" : tokenCards
      ? "Reason for removing this added token-card row (required)" : batchRemoving ? "Reason for removing all these added rows (required)" : "Reason for removing this added row (required)" }), reasonInput),
      el("p", { class: "field-hint", id: id + "-hint", text: accessoryRemoving
        ? "Up to 200 characters. Enter why this entire record should be removed from Sleeves & boxes."
        : tokenCards
        ? "Up to 200 characters. Enter why these physical token cards should be removed from the recorded tokens."
        : "Up to 200 characters. Enter why these copies should be removed from the collection." }), normalized);
    const changed = () => {
      if (!ctx.here() || ctx.pending || ctx.saved || ctx.needsRefresh || !reasonInput.isConnected || !sheet.body.contains(reasonInput)
          || ctx.preview !== preview || JSON.stringify(preview) !== signature) { reasonInput.value = acceptedReason; return; }
      if (reasonInput.value === acceptedReason) return;
      acceptedReason = reasonInput.value; reviewedReason = activityUndoRemovalReason(acceptedReason);
      normalized.textContent = reviewedReason ? "Reason to be saved: " + reviewedReason : "Enter a nonblank reason of at most 200 characters.";
      error.textContent = ""; actions();
      if (document.activeElement === reasonInput) reasonInput.scrollIntoView?.({ block: "nearest" });
    };
    reasonInput.addEventListener("input", changed); reasonInput.addEventListener("change", changed);
  } else if (accessoryAdding) {
    const row = preview.restored, zero = row.quantity === "0", units = row.kind === "sleeves"
      ? row.quantity === "1" ? "individual sleeve" : "individual sleeves" : row.quantity === "1" ? "item" : "items";
    sheet.body.append(el("p", { class: "box box-warn", text: zero
      ? "Restore this zero-quantity reference record. No owned items are added."
      : "Undo restores all " + row.quantity + " " + units + " in this historical accessory record, in addition to the quantities already recorded in Sleeves & boxes." }),
      el("p", { class: "sub", text: "Saving creates one new audited change; the original audit stays in Activity. No photo or kit assignments are restored. Recorded image-source URLs restore as text; no photo is recovered." }),
      zero ? null : el("p", { class: "sub", text: "Confirm only if the entire quantity is still physically owned in addition to the existing records. If you own fewer, cancel and use Sleeves & boxes to add the actual quantity." }),
      el("section", { class: "panel" }, el("h3", { text: "Historical accessory record to restore" }),
        el("dl", {}, ACTIVITY_UNDO_ACCESSORY_STOCK_FIELDS.flatMap(field => [el("dt", { text: words[field] || field.replaceAll("_", " ") }),
          el("dd", { class: ["notes", "link", "image_source"].includes(field) ? "activity-undo-note" : null,
            text: field === "owner" ? row.owner === "shared" ? "Shared" : state.profile?.name || row.owner
              : field === "kind" ? { sleeves: "Sleeves", deck_box: "Deck box", playmat: "Playmat" }[row.kind] : text(row[field]) })]))));
    const id = "activity-undo-restore-" + sheet.heading.id;
    ownershipInput = el("input", { id, type: "checkbox" }); ownershipInput.checked = false;
    sheet.body.append(el("label", { class: "choice", for: id }, ownershipInput, el("span", { text: zero
      ? "I confirm this zero-quantity accessory record should be restored."
      : "I confirm all " + row.quantity + " " + units + " are still physically owned in addition to the quantities already recorded." })));
    ownershipInput.addEventListener("change", () => {
      if (!ctx.here() || ctx.pending || ctx.saved || ctx.needsRefresh || !ownershipInput.isConnected || !sheet.body.contains(ownershipInput)
          || ctx.preview !== preview || JSON.stringify(preview) !== signature) { ownershipInput.checked = confirmedOwned; return; }
      confirmedOwned = ownershipInput.checked === true; ownershipInput.checked = confirmedOwned; error.textContent = ""; actions();
    });
  } else if (adding) {
    const copies = batchAdding ? preview.rows.reduce((sum, item) => sum + item.restored.quantity, 0) : preview.restored.quantity;
    const scope = batchAdding ? " across all " + plural(preview.row_count, "printing") : " of this printing";
    const historical = row => el("dl", {}, ACTIVITY_UNDO_FIELDS.collection.flatMap(field => [el("dt", { text: field.replaceAll("_", " ") }),
      el("dd", { class: field === "notes" ? "activity-undo-note" : null, text: text(row[field]) })]));
    sheet.body.append(el("p", { class: "box box-warn", text: "Undo restores all " + plural(copies, "recorded copy", "recorded copies")
      + scope + ", with the historical condition, language and notes shown below." }),
      el("p", { class: "sub", text: "Confirm only if you still physically own the entire recorded quantity. If you own fewer copies, cancel and use Collection to record the copies you still own." }),
      el("p", { class: "sub", text: "Saving creates one new audited change; the original change stays in Activity." }));
    if (batchAdding) sheet.body.append(el("p", { class: "sub", text: "Review every historical row below. All printings restore together; there is no partial selection." }),
      el("div", { class: "panels" }, preview.rows.map(item => el("section", { class: "panel activity-undo-batch-row" },
        el("h4", { text: item.label }), historical(item.restored)))));
    else sheet.body.append(el("section", { class: "panel" }, el("h3", { text: "Historical row to restore" }), historical(preview.restored)));
    const id = "activity-undo-owned-" + sheet.heading.id;
    ownershipInput = el("input", { id, type: "checkbox" }); ownershipInput.checked = false;
    sheet.body.append(el("label", { class: "choice", for: id }, ownershipInput, el("span", {
      text: "I confirm all " + plural(copies, "recorded copy", "recorded copies") + scope + " are still physically owned." })));
    ownershipInput.addEventListener("change", () => {
      if (!ctx.here() || ctx.pending || ctx.saved || ctx.needsRefresh || !ownershipInput.isConnected || !sheet.body.contains(ownershipInput)
          || ctx.preview !== preview || JSON.stringify(preview) !== signature) { ownershipInput.checked = confirmedOwned; return; }
      confirmedOwned = ownershipInput.checked === true; ownershipInput.checked = confirmedOwned; error.textContent = ""; actions();
    });
  } else {
    const details = key => {
      const row = key === "before" ? preview.current : preview.restored;
      return accessoryCorrecting ? el("dl", {}, ACTIVITY_UNDO_ACCESSORY_QUANTITY_FIELDS.flatMap(field => [el("dt", { text: words[field] || field.replaceAll("_", " ") }),
        el("dd", { class: ["notes", "link", "image_source"].includes(field) ? "activity-undo-note" : null,
          text: field === "kind" ? kindText(row.kind) : field === "owner" ? ownerText(row.owner) : field === "quantity" ? kindCount(row) : text(row[field]) })]))
        : preview.fields.map(field => el("p", {}, el("b", { text: words[field.field] + ": " }),
          el("span", { class: ["notes", "source", "link", "image_source"].includes(field.field) ? "activity-undo-note" : null,
            text: accessoryOwning && field.field === "owner" ? ownerText(field[key]) : accessoryRetyping && field.field === "kind" ? kindText(field[key]) : text(field[key]) })));
    };
    const panels = [["Current", "before"], ["Restored by Undo", "after"]].map(([title, key]) => el("section", { class: "panel" },
      el("h3", { text: title }), details(key),
      accessoryRetyping ? el("p", { text: "Recorded quantity: " + kindCount(key === "before" ? preview.current : preview.restored) + "." }) : null));
    const identityText = field => preview.kind === "accessory" && field === "kind" ? { sleeves: "Sleeves", deck_box: "Deck box", playmat: "Playmat" }[preview.current.kind]
      : preview.kind === "accessory" && field === "owner" ? preview.current.owner === "shared" ? "Shared" : state.profile?.name || preview.current.owner : text(preview.current[field]);
    sheet.body.append(el("p", { class: "sub", text: preview.kind === "accessory"
      ? "Review the recorded accessory details this Undo will restore. Saving creates one new audited change and retains the current photo and kit; the original change stays in Activity. A restored image-source URL is not checked against the current photo."
      : "Review the current row and the values this Undo will restore. Saving creates one new audited change; the original change stays in Activity." }),
      preview.kind === "accessory" && preview.fields.some(field => field.field === "capacity")
        ? el("p", { class: "sub", text: "Recorded box capacity is in sleeved cards. Fit warnings may change; kit assignments stay as they are." }) : null,
      identity.length ? el("dl", {}, identity.flatMap(field => [el("dt", { text: field === "number" ? "collector number" : field.replaceAll("_", " ") }), el("dd", { text: identityText(field) })])) : null,
      el("div", { class: "panels" }, panels));
    if (accessoryCounting) {
      const row = preview.restored, zero = row.quantity === "0", units = row.kind === "sleeves"
        ? row.quantity === "1" ? "individual sleeve" : "individual sleeves" : row.quantity === "1" ? "item" : "items";
      sheet.body.append(el("p", { class: "box box-warn", text: "Undo replaces this record's current quantity with " + row.quantity + " " + units
        + ". This is the whole recorded count, not an additional quantity. Sleeve shortages and box availability warnings may change; photos and kit assignments stay as they are." }),
        el("p", { class: "sub", text: zero ? "The zero-quantity reference record is kept. No owned items are added."
          : "Confirm only if this record should show the entire quantity you still physically own. Sleeves count individual sleeves, loose ones included. If the count differs, cancel and use Sleeves & boxes to record the actual quantity." }));
      const id = "activity-undo-stock-" + sheet.heading.id;
      ownershipInput = el("input", { id, type: "checkbox" }); ownershipInput.checked = false;
      sheet.body.append(el("label", { class: "choice", for: id }, ownershipInput, el("span", { text: zero
        ? "I confirm this accessory record should show zero owned items."
        : "I confirm this record should show a total of " + row.quantity + " " + units + " still physically owned." })));
      ownershipInput.addEventListener("change", () => {
        if (!ctx.here() || ctx.pending || ctx.saved || ctx.needsRefresh || !ownershipInput.isConnected || !sheet.body.contains(ownershipInput)
            || ctx.preview !== preview || JSON.stringify(preview) !== signature) { ownershipInput.checked = confirmedOwned; return; }
        confirmedOwned = ownershipInput.checked === true; ownershipInput.checked = confirmedOwned; error.textContent = ""; actions();
      });
    }
    if (accessoryOwning) {
      const row = preview.restored, units = row.kind === "sleeves"
        ? row.quantity === "1" ? "individual sleeve" : "individual sleeves" : row.quantity === "1" ? "item" : "items";
      sheet.body.append(el("p", { class: "box box-warn", text: "Undo changes this record from " + ownerText(preview.current.owner) + " to " + ownerText(row.owner)
        + ". Both people at home can see and change Shared accessories; only you can change Mine. Read access also follows the destination owner's existing Public/Private kit setting. Undo does not change that setting." }),
        el("p", { class: "sub", text: "Recorded quantity stays at " + row.quantity + " " + units + ". Current photos and kit assignments stay as they are. Only an unused record can change owner here; references are checked again when you save." }));
      const id = "activity-undo-owner-" + sheet.heading.id;
      ownershipInput = el("input", { id, type: "checkbox" }); ownershipInput.checked = false;
      sheet.body.append(el("label", { class: "choice", for: id }, ownershipInput,
        el("span", { text: "I confirm this record should be " + ownerText(row.owner) + ", with the access described above." })));
      ownershipInput.addEventListener("change", () => {
        if (!ctx.here() || ctx.pending || ctx.saved || ctx.needsRefresh || !ownershipInput.isConnected || !sheet.body.contains(ownershipInput)
            || ctx.preview !== preview || JSON.stringify(preview) !== signature) { ownershipInput.checked = confirmedOwned; return; }
        confirmedOwned = ownershipInput.checked === true; ownershipInput.checked = confirmedOwned; error.textContent = ""; actions();
      });
    }
    if (accessoryRetyping) {
      const row = preview.restored, zero = row.quantity === "0";
      sheet.body.append(el("p", { class: "box box-warn", text: "Undo changes the recorded classification from " + kindText(preview.current.kind) + " to " + kindText(row.kind)
        + ". The number stays " + row.quantity + "; review its units on both sides. Current photos and kit assignments stay as they are. Only an unused record can change kind here; references are checked again when you save." }),
        el("p", { class: "sub", text: zero ? "This remains a zero-quantity reference record. No owned items are added."
          : "Confirm the kind and whole count still match the accessories you own. Sleeves count individual sleeves, loose ones included; boxes and playmats count items. If either differs, cancel and use Sleeves & boxes to record the actual kind and quantity." }));
      const id = "activity-undo-kind-" + sheet.heading.id;
      ownershipInput = el("input", { id, type: "checkbox" }); ownershipInput.checked = false;
      sheet.body.append(el("label", { class: "choice", for: id }, ownershipInput, el("span", { text: zero
        ? "I confirm this zero-quantity reference record should be classified as " + kindText(row.kind) + "."
        : "I confirm this record describes all " + kindCount(row) + " still physically owned as " + kindText(row.kind) + "." })));
      ownershipInput.addEventListener("change", () => {
        if (!ctx.here() || ctx.pending || ctx.saved || ctx.needsRefresh || !ownershipInput.isConnected || !sheet.body.contains(ownershipInput)
            || ctx.preview !== preview || JSON.stringify(preview) !== signature) { ownershipInput.checked = confirmedOwned; return; }
        confirmedOwned = ownershipInput.checked === true; ownershipInput.checked = confirmedOwned; error.textContent = ""; actions();
      });
    }
    if (accessoryCorrecting) {
      const row = preview.restored, zero = row.quantity === "0", ownerChanged = preview.current.owner !== row.owner;
      sheet.body.append(el("p", { class: "box box-warn", text: "Undo restores this whole recorded correction together. Review both complete records, including kind, count and whose accessories they are. The restored quantity replaces this record's current total. Current photos, crop and kit assignments stay as they are. Only an unused record can be recovered here; references are checked again when you save." }),
        el("p", { class: "sub", text: zero ? "The restored entry is a zero-quantity reference record. No owned items are added."
          : "Confirm the restored kind and entire count still match the accessories you own. Sleeves count individual sleeves, loose ones included; boxes and playmats count items. If any facts differ, cancel and use Sleeves & boxes to record the actual details." }),
        ownerChanged ? el("p", { class: "sub", text: "Both people at home can see and change Shared accessories; only you can change Mine. Read access also follows the destination owner's existing Public/Private kit setting. Undo does not change that setting." }) : null);
      const id = "activity-undo-record-" + sheet.heading.id;
      ownershipInput = el("input", { id, type: "checkbox" }); ownershipInput.checked = false;
      sheet.body.append(el("label", { class: "choice", for: id }, ownershipInput, el("span", { text: zero
        ? "I confirm this zero-quantity reference record should be " + kindText(row.kind) + " and " + ownerText(row.owner) + "."
        : "I confirm the full restored count of " + kindCount(row) + " is still physically owned as " + kindText(row.kind) + ", and this record should be " + ownerText(row.owner) + "." })));
      ownershipInput.addEventListener("change", () => {
        if (!ctx.here() || ctx.pending || ctx.saved || ctx.needsRefresh || !ownershipInput.isConnected || !sheet.body.contains(ownershipInput)
            || ctx.preview !== preview || JSON.stringify(preview) !== signature) { ownershipInput.checked = confirmedOwned; return; }
        confirmedOwned = ownershipInput.checked === true; ownershipInput.checked = confirmedOwned; error.textContent = ""; actions();
      });
    }
  }
  const error = el("p", { class: "form-error", role: "alert", tabindex: "-1" }); sheet.body.append(error);
  function actions() {
    if (reasonInput) reasonInput.disabled = ctx.pending || ctx.saved || ctx.needsRefresh;
    if (ownershipInput) ownershipInput.disabled = ctx.pending || ctx.saved || ctx.needsRefresh || accessoryCropping && !photoPreview?.valid();
    sheetActions(sheet, ctx.saved ? [{ text: "Done", kind: "primary", onclick: event => { if (ctx.here() && event.currentTarget.isConnected) sheet.close(); } }]
      : ctx.needsRefresh ? [{ text: "Reload Activity", kind: "primary", onclick: event => { if (ctx.here() && event.currentTarget.isConnected) sheet.close(); } },
        { text: "Close", onclick: () => sheet.close() }]
        : [{ text: "Cancel", disabled: ctx.pending, onclick: () => sheet.close() },
          { text: ctx.pending ? "Saving Undo." : "Save Undo", kind: "primary", disabled: ctx.pending || removing && !reviewedReason || (adding || accessoryCounting || accessoryOwning || accessoryRetyping || accessoryCorrecting || accessoryCropping) && !confirmedOwned || accessoryCropping && !photoPreview?.valid(), onclick: save }]);
  }
  async function save(event) {
    if (!ctx.here() || ctx.pending || ctx.saved || ctx.needsRefresh || !event?.currentTarget?.isConnected || !sheet.foot.contains(event.currentTarget)
        || ctx.endpoint !== endpoint || ctx.preview !== preview || JSON.stringify(preview) !== signature || !activityUndoEvidence(preview, ctx.id, ctx.space, ctx.profile)) return;
    if (removing && (!reasonInput?.isConnected || !sheet.body.contains(reasonInput) || reasonInput.value !== acceptedReason
        || !reviewedReason || activityUndoRemovalReason(reasonInput.value) !== reviewedReason)) {
      error.textContent = "Enter and review a nonblank reason of at most 200 characters before saving Undo."; return;
    }
    if ((adding || accessoryCounting || accessoryOwning || accessoryRetyping || accessoryCorrecting || accessoryCropping) && (!ownershipInput?.isConnected || !sheet.body.contains(ownershipInput) || !confirmedOwned || ownershipInput.checked !== true || accessoryCropping && !photoPreview?.valid())) {
      error.textContent = accessoryCropping ? "Wait for the verified current photo, then confirm both crop views before saving Undo."
        : accessoryCorrecting ? "Review and confirm the whole recorded correction before saving Undo."
        : accessoryRetyping ? "Review and confirm the accessory kind and whole recorded count before saving Undo."
        : accessoryOwning ? "Review and confirm who should own this accessory record before saving Undo."
        : accessoryCounting ? "Review and confirm the entire recorded accessory count before saving Undo."
        : accessoryAdding ? "Review and confirm this historical accessory record before saving Undo."
        : "Confirm that every recorded copy is still physically owned before saving Undo."; return;
    }
    const trigger = document.activeElement;
    const focusOwned = () => document.activeElement === trigger || document.activeElement === document.body || !document.activeElement?.isConnected;
    ctx.pending = true; error.textContent = ""; actions();
    try {
      const answer = await apiWrite(endpoint, { id: ctx.id, expect: preview.expect,
        ...(removing ? { reason: reviewedReason } : {}), ...(accessoryCropping ? { confirm_photo: true } : accessoryCorrecting ? { confirm_record: true } : accessoryRetyping ? { confirm_kind: true } : accessoryOwning ? { confirm_owner: true } : accessoryCounting ? { confirm_stock: true } : accessoryAdding ? { confirm_restore: true } : adding ? { confirm_owned: true } : {}) });
      if (preview.kind !== "wishlist") state.library = null;
      if (!activityUndoReceipt(answer, preview)) throw new Error("The Undo result could not be confirmed.");
      if (!activityUndoOwner(ctx)) return;
      ctx.saved = true;
      if (ctx.current()) {
        const confirmation = el("p", { role: "status", tabindex: "-1", text: "Undo saved as a new change. " + answer.summary });
        sheet.body.append(confirmation); actions(); if (ctx.here() && focusOwned()) confirmation.focus();
      }
    } catch (failure) {
      if (preview.kind !== "wishlist") state.library = null;
      if (!activityUndoOwner(ctx)) return;
      ctx.needsRefresh = true;
      error.textContent = (failure.status ? failure.message : "The Undo result could not be confirmed.") + " Reload Activity before reviewing another Undo.";
      if (ctx.current() && ctx.here() && focusOwned()) error.focus();
    } finally {
      ctx.pending = false;
      if (activityUndoOwner(ctx)) {
        if (ctx.current()) actions(); else activityUndoAfterClose(ctx);
      }
    }
  }
  actions();
  startPhoto?.();
}

/** A bounded refresh keeps the filter and loaded page depth; old rows stay until every read succeeds. */
async function activityUndoRefresh(ctx) {
  const view = ctx.view;
  if (!activityUndoOwner(ctx) || !ctx.sheet.closed || ctx.pending || ctx.refreshing || ctx.refreshed || document.querySelector("dialog[open]")) return;
  ctx.refreshing = true; view.undoRefreshNeeded = true;
  const depth = view.loadedPages || 1, pages = []; let cursor = null;
  try {
    for (let page = 0; page < depth; page++) {
      const data = await api(activityPath(ctx.filter, cursor));
      if (!activityUndoOwner(ctx) || document.querySelector("dialog[open]")) return;
      if (!data || !Array.isArray(data.changes) || !(data.next === null || Number.isSafeInteger(data.next) && data.next > 0)
          || typeof data.everything !== "boolean" || data.changes.some(change => !change || !Number.isSafeInteger(change.id) || change.id < 1
            || !Array.isArray(change.rows) || !Number.isFinite(new Date(change.at).getTime()))) throw new Error("The refreshed Activity could not be checked.");
      pages.push(data); cursor = data.next; if (cursor === null) break;
    }
    if (!activityUndoOwner(ctx) || document.querySelector("dialog[open]")) return;
    const oldRoot = view.days, oldPeople = view.peopleRow, oldEmpty = view.empty;
    const anchor = oldRoot.querySelector('[data-activity-id="' + ctx.id + '"]'), offset = anchor?.getBoundingClientRect().top;
    const active = document.activeElement, focusId = oldRoot.contains(active) ? active.closest(".activity-change")?.getAttribute("data-activity-id") : null;
    const kept = { days: view.days, peopleRow: view.peopleRow, people: view.people, cards: view.cards, lastDay: view.lastDay,
      lastList: view.lastList, shown: view.shown, empty: view.empty, next: view.next, everything: view.everything, loadedPages: view.loadedPages };
    try {
      Object.assign(view, { days: el("div", { class: "activity-days" }), peopleRow: el("nav", { class: "activity-filter", "aria-label": "Whose changes" }),
        people: new Map(), cards: Object.assign({}, ...pages.map(page => page.cards || {})), lastDay: null, lastList: null,
        shown: 0, empty: null, next: cursor, everything: pages[0].everything, loadedPages: pages.length });
      const changes = pages.flatMap(page => page.changes);
      if (new Set(changes.map(change => change.id)).size !== changes.length) throw new Error("Activity repeated a change.");
      activityAppend(view, changes); if (!view.shown) view.empty = activityEmpty(view);
    } catch (failure) { Object.assign(view, kept); throw failure; }
    ctx.refreshed = true; view.undoCtx = null; view.undoBusy = false; view.undoRefreshNeeded = false;
    oldRoot.replaceWith(view.days); oldPeople.replaceWith(view.peopleRow); oldEmpty?.remove();
    if (view.empty) view.days.parentNode.insertBefore(view.empty, view.older.parentNode);
    view.older.hidden = !view.next; clear(view.note).append("Activity is up to date.");
    const fresh = view.days.querySelector('[data-activity-id="' + ctx.id + '"]');
    if (fresh && offset !== undefined) window.scrollBy?.(0, fresh.getBoundingClientRect().top - offset);
    else if (!fresh) view.days.querySelector("h2")?.scrollIntoView?.({ block: "nearest" });
    const focus = focusId && view.days.querySelector('[data-activity-id="' + focusId + '"]');
    if (focus) focus.focus({ preventScroll: true });
    else if (focusId && !fresh) {
      const heading = view.days.querySelector("h2") || view.note;
      heading.setAttribute("tabindex", "-1"); heading.focus({ preventScroll: true });
    }
  } catch (failure) {
    if (activityUndoOwner(ctx)) activityUndoReloadNote(ctx, failure.message);
  } finally { ctx.refreshing = false; }
}

function activityUndoReloadNote(ctx, message = "Reload Activity before reviewing another Undo.") {
  if (!activityUndoOwner(ctx)) return;
  const view = ctx.view; view.undoRefreshNeeded = true;
  clear(view.note).append(message, " ", el("button", { type: "button", class: "btn", text: "Reload Activity", onclick: event => {
    if (activityUndoOwner(ctx) && event.currentTarget.isConnected && view.note.contains(event.currentTarget)) activityUndoRefresh(ctx);
  } }));
}

function activityUndoAfterClose(ctx) {
  if (!activityUndoOwner(ctx) || ctx.pending || ctx.refreshed || ctx.refreshing) return;
  const entry = ctx.sheet.entry;
  const stop = () => { window.removeEventListener("popstate", landed); window.removeEventListener("hashchange", stop); };
  const landed = () => {
    stop();
    if (!activityUndoOwner(ctx) || entry && (history.state?.sheet === entry.token || history.state?.pos !== entry.pos - 1)) return;
    activityUndoReloadNote(ctx); activityUndoRefresh(ctx);
  };
  if (!entry || entry.fromHistory || history.state?.sheet !== entry.token) landed();
  else { window.addEventListener("popstate", landed); window.addEventListener("hashchange", stop); }
}
