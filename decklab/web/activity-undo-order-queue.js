/* Whole recorded order +queue intent recovery. The server's immutable receipt is the only write authority. */
"use strict";

function activityUndoOrderFact(order, identity) {
  if (order === null) return true;
  if (!order || Object.keys(order).sort().join(",") !== "audit_notes,components,id,notes,ordered_on,seller,sources" || order.id !== identity
      || ["id","seller","ordered_on","notes","audit_notes"].some(key=>typeof order[key]!=="string")
      || !Array.isArray(order.sources) || order.sources.some(source=>typeof source!=="string")
      || !Array.isArray(order.components) || !order.components.length || order.components.length>2000) return false;
  const ids=new Set();
  return order.components.every(part=>{
    if(!part||typeof part!=="object")return false;
    const product=part.kind==="product",fields=["id","kind","status","received_on","checks","verified_checks","rows",
      ...(product?["product","name","format","product_status"]:[])].sort();
    if(Object.keys(part).sort().join(",")!==fields.join(",")||typeof part.id!=="string"||!part.id||ids.has(part.id)
        ||!["cards","tokens","product"].includes(part.kind)||!["pending","received","cancelled"].includes(part.status)
        ||typeof part.received_on!=="string"||[part.checks,part.verified_checks].some(items=>!Array.isArray(items)||items.some(item=>typeof item!=="string"))
        ||!Array.isArray(part.rows)||!part.rows.length||part.rows.length>2000)return false;
    ids.add(part.id);
    if(product&&(typeof part.product!=="string"||[part.name,part.format].some(value=>value!==null&&typeof value!=="string")
        ||!["ordered","preordered","owned","cancelled"].includes(part.product_status)))return false;
    return part.rows.every(row=>{
      if(!row||typeof row!=="object"||Array.isArray(row)||Object.values(row).some(value=>typeof value!=="string"))return false;
      const fields=ACTIVITY_UNDO_FIELDS[part.kind==="tokens"?"tokens":"collection"];
      const columns=Object.keys(row);
      if(product?!["name","set","collector_number","finish","quantity"].every(key=>columns.includes(key))
          ||columns.some(key=>![...fields,"section","deck","rarity","in_play_boosters"].includes(key)):columns.sort().join(",")!==[...fields].sort().join(","))return false;
      return /^\d+$/.test(row.quantity)&&/[1-9]/.test(row.quantity);
    });
  });
}

function activityUndoOrderTables(tables) {
  return tables&&Object.keys(tables).sort().join(",")==="needs_attention,written"&&typeof tables.needs_attention==="boolean"
    &&Array.isArray(tables.written)&&tables.written.length<=2000&&tables.written.every(row=>row&&Object.keys(row).sort().join(",")==="id,title"
      &&typeof row.id==="string"&&typeof row.title==="string");
}

function activityUndoOrderQueueEvidence(data,space,profile) {
  if(Object.keys(data).sort().join(",")!=="action,available,current,expect,id,kind,label,order_id,queue,queue_count,reason_required,restored,row_count,source_action,space,tables"
      ||data.kind!=="order_queue"||space!=="home"||data.space!=="home"||profile!==state.profile?.id||!profile||!isAdminProfile()||!mayDo("orders")||!seesHomeInventory(state.may)
      ||data.action!=="order_queue_restore"||data.reason_required!==true||typeof data.order_id!=="string"||!data.order_id
      ||!["added","removed","state"].includes(data.source_action)||!Number.isSafeInteger(data.row_count)||data.row_count<2||data.row_count>2000
      ||!Number.isSafeInteger(data.queue_count)||data.queue_count<1||data.queue_count>50
      ||!activityUndoOrderFact(data.current,data.order_id)||!activityUndoOrderFact(data.restored,data.order_id)
      ||(data.current===null)!==(data.source_action==="removed")||(data.restored===null)!==(data.source_action==="added")
      ||!activityUndoOrderTables(data.tables)||!data.queue||data.queue.kind!=="watchlist"||data.queue.row_count!==data.queue_count
      ||!activityUndoEvidence(data.queue,data.id,"home",profile))return false;
  return data.label==="recorded order and its purchase-queue intent";
}

function activityUndoOrderQueueReceipt(answer,preview) {
  return !!answer&&answer.saved===true&&answer.source_id===preview.id&&answer.expect===preview.expect
    &&Object.keys(answer).sort().join(",")==="action,expect,kind,order,order_id,queue,revision,saved,source_id,space,summary,tables"
    &&answer.kind==="order_queue"&&answer.space==="home"&&answer.action===preview.action&&answer.order_id===preview.order_id
    &&typeof answer.revision==="string"&&!!answer.revision&&typeof answer.summary==="string"&&!!answer.summary.trim()
    &&activityUndoOrderFact(answer.order,preview.order_id)&&JSON.stringify(answer.order)===JSON.stringify(preview.restored)
    &&activityUndoOrderTables(answer.tables)&&answer.queue?.revision===answer.revision&&activityUndoWatchlistReceipt(answer.queue,preview.queue);
}

function activityUndoOrderQueueShow(ctx) {
  const {sheet,preview,endpoint}=ctx,signature=JSON.stringify(preview);
  const current=()=>ctx.here()&&ctx.preview===preview&&JSON.stringify(preview)===signature&&activityUndoEvidence(preview,ctx.id,ctx.space,ctx.profile);
  const literal=value=>value===""||value==null?"Not recorded":String(value);
  const orderPanel=order=>{
    if(order===null)return el("p",{class:"sub",text:"No recorded order"});
    const panel=el("div",{},el("p",{text:`${order.id} · ${literal(order.seller)} · ${literal(order.ordered_on)}`}));
    for(const words of [order.notes,order.audit_notes,...order.sources])if(words)panel.append(el("p",{class:"activity-undo-note",text:words}));
    for(const part of order.components){
      const details=el("details",{},el("summary",{text:`${part.id} · ${part.kind} · ${part.status} · ${plural(part.rows.length,"recorded row")}`}),
        part.product?el("p",{text:`${part.name||part.product} · ${part.product_status}${part.format?` · ${part.format}`:""}`}):null);
      for(const row of part.rows){
        const name=part.kind==="tokens"?`${row.front}${row.back?` / ${row.back}`:""}`:row.name;
        const printing=part.kind==="tokens"?[row.set,row.front_collector_number,row.back_collector_number,row.finish].filter(Boolean).join(" ")
          :[row.set,row.collector_number,row.finish].filter(Boolean).join(" ");
        details.append(el("p",{text:`${row.quantity} × ${name} · ${printing||"Printing not confirmed"}${row.section?` · ${row.section}`:""}${row.deck?` · ${row.deck}`:""}`}));
        if(part.kind!=="tokens")details.append(el("p",{class:"sub",text:`Condition: ${literal(row.condition)} · Language: ${literal(row.language)}`}));
        if(part.kind==="product")for(const [field,label] of [["section","Section"],["deck","Product deck"],["rarity","Rarity"],["in_play_boosters","In play boosters"]])
          if(Object.hasOwn(row,field))details.append(el("p",{class:"sub",text:`${label}: ${literal(row[field])}`}));
        for(const note of [row.notes,row.front_details,row.back_details].filter(Boolean))details.append(el("p",{class:"activity-undo-note",text:note}));
      }
      for(const note of [...part.checks.map(text=>"Check on arrival: "+text),...part.verified_checks.map(text=>"Already checked: "+text)])details.append(el("p",{class:"activity-undo-note",text:note}));
      panel.append(details);
    }
    return panel;
  };
  clear(sheet.body).append(el("p",{class:"box box-warn",text:"Restore this recorded order and its purchase-queue intent together in one new audited change. Every row is checked again when you save; the original stays in Activity."}),
    el("p",{class:"sub",text:"Current deck lists, prose and kit are retained; their availability tables are refreshed from current inventory. Orders with the shop are handled separately."}),
    el("div",{class:"panels"},[["Current order",preview.current],["Restored by Undo",preview.restored]].map(([title,order])=>el("section",{class:"panel"},el("h4",{text:title}),orderPanel(order)))));
  for(const item of preview.queue.rows){
    const rowPanel=row=>row?el("dl",{},ACTIVITY_UNDO_FIELDS.watchlist.filter(field=>Object.hasOwn(row,field)).flatMap(field=>[
      el("dt",{text:ACTIVITY_UNDO_WATCHLIST_WORDS[field]||field}),el("dd",{class:"activity-undo-note",text:literal(row[field])})])):el("p",{class:"sub",text:"No queue row"});
    sheet.body.append(el("section",{class:"panel activity-undo-batch-row"},el("h4",{text:item.label}),el("h5",{text:"Current queue"}),rowPanel(item.current),
      el("h5",{text:"Queue restored by Undo"}),rowPanel(item.restored)));
  }
  if(preview.tables.written.length)sheet.body.append(el("p",{class:"sub",text:"Refresh availability: "+preview.tables.written.map(row=>row.title).join(", ")}));
  if(preview.tables.needs_attention)sheet.body.append(el("p",{class:"box box-warn",text:"Some deck tables need attention. The recorded order and queue inverse can still be saved together."}));
  const input=el("input",{type:"text",maxlength:200,"aria-label":"Reason for restoring the complete order and queue"}),error=el("p",{class:"form-error",role:"alert",tabindex:"-1"});
  sheet.body.append(el("label",{class:"field"},el("span",{text:"Reason for this complete recorded correction (required)"}),input),error);
  let accepted="",reason="";
  input.addEventListener("input",()=>{if(!current()||ctx.pending||ctx.saved||ctx.needsRefresh||!input.isConnected||!sheet.body.contains(input)){input.value=accepted;return;}
    accepted=input.value;reason=activityUndoRemovalReason(accepted);error.textContent="";actions();
    if(document.activeElement===input)input.scrollIntoView?.({block:"nearest"});});
  function actions(){
    input.disabled=ctx.pending||ctx.saved||ctx.needsRefresh;
    sheetActions(sheet,ctx.saved?[{text:"Done",kind:"primary",onclick:()=>{if(ctx.here())sheet.close();}}]:ctx.needsRefresh?
      [{text:"Reload Activity",kind:"primary",onclick:()=>{if(ctx.here())sheet.close();}},{text:"Close",onclick:()=>sheet.close()}]:
      [{text:"Cancel",disabled:ctx.pending,onclick:()=>sheet.close()},{text:ctx.pending?"Saving Undo…":"Save Undo",kind:"primary",disabled:ctx.pending||!reason,onclick:save}]);
  }
  async function save(event){
    if(!current()||ctx.pending||ctx.saved||ctx.needsRefresh||ctx.endpoint!==endpoint||!event.currentTarget.isConnected||!sheet.foot.contains(event.currentTarget)
        ||!input.isConnected||!sheet.body.contains(input)||input.value!==accepted||!reason||activityUndoRemovalReason(input.value)!==reason)return;
    ctx.pending=true;error.textContent="";actions();
    try{const answer=await apiWrite(endpoint,{id:ctx.id,expect:preview.expect,reason});invalidateLibrary();
      if(!activityUndoOrderQueueReceipt(answer,preview))throw Error("The complete Undo result could not be confirmed.");
      if(!activityUndoOwner(ctx))return;ctx.saved=true;
      if(ctx.current()){const message=el("p",{role:"status",tabindex:"-1",text:"Undo saved as a new change. "+answer.summary
        +(answer.tables.needs_attention?" Some deck tables need attention.":"")});sheet.body.append(message);actions();if(ctx.here())message.focus();}
    }catch(failure){invalidateLibrary();if(!activityUndoOwner(ctx))return;ctx.needsRefresh=true;
      error.textContent=(failure instanceof ApiError?failure.message:"The Undo result could not be confirmed.")+" Reload Activity before another review.";
    }finally{ctx.pending=false;if(activityUndoOwner(ctx)){if(ctx.current())actions();else activityUndoAfterClose(ctx);}}
  }
  actions();
}
