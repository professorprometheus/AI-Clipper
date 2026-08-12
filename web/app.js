const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const stages = ['validate_campaign','resolve_sources','ingest_sources','analyse_successful_examples','social_research','synthesize_strategy','discover_candidates','rank_candidates','render','qa','review_ready'];
const state = {campaignId: new URLSearchParams(location.search).get('campaign')};

async function api(path, options={}) {
  const csrf=document.cookie.split('; ').find(value=>value.startsWith('alpha_csrf='))?.split('=').slice(1).join('=');
  const response = await fetch(path,{headers:{'content-type':'application/json',...(csrf?{'x-alpha-csrf':decodeURIComponent(csrf)}:{}),...(options.headers||{})},...options});
  const data = await response.json().catch(()=>({}));
  if(!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
  return data;
}
async function uploadApi(path, body) {
  const csrf=document.cookie.split('; ').find(value=>value.startsWith('alpha_csrf='))?.split('=').slice(1).join('=');
  const response = await fetch(path,{method:'POST',headers:{...(csrf?{'x-alpha-csrf':decodeURIComponent(csrf)}:{})},body});
  const data = await response.json().catch(()=>({}));
  if(!response.ok) throw new Error(data.detail || `Upload failed (${response.status})`);
  return data;
}
function notice(message,error=false){const el=$('#notice');el.textContent=message;el.classList.toggle('error',error);el.classList.remove('hidden');setTimeout(()=>el.classList.add('hidden'),6000)}
function lines(value){return value.split(/\r?\n/).map(v=>v.trim()).filter(Boolean)}
function transcriptSegments(value){return lines(value).map(line=>{const parts=line.split('|');if(parts.length<3)throw new Error('Each transcript line needs start_ms | end_ms | text');return {start_ms:+parts[0].trim(),end_ms:+parts[1].trim(),text:parts.slice(2).join('|').trim()}})}
function fileBase64(file){return new Promise((resolve,reject)=>{if(!file)return resolve(null);const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=reject;r.readAsDataURL(file)})}
function esc(value){const d=document.createElement('div');d.textContent=String(value??'');return d.innerHTML}

async function loadCampaigns(){
  const campaigns=await api('/api/campaigns');
  $('#campaign-list').innerHTML=campaigns.length?campaigns.map(c=>{
    const idx=c.status==='awaiting_review'?stages.length:Math.max(0,stages.indexOf(c.current_stage));
    return `<article class="campaign-card" data-id="${c.id}"><div class="meta-row"><span class="status">${esc(c.status)}</span><span class="muted">${new Date(c.created_at).toLocaleDateString()}</span></div><h3>${esc(c.name)}</h3><p class="muted">${c.source_count} approved sources · ${c.variant_count} variants</p><div class="progress"><span style="width:${Math.round(idx/stages.length*100)}%"></span></div></article>`
  }).join(''):'<p class="muted">No campaigns yet. Create the first one.</p>';
  $$('.campaign-card').forEach(card=>card.onclick=()=>openCampaign(card.dataset.id));
}

async function openCampaign(id){
  state.campaignId=id;history.replaceState({},'',`/?campaign=${id}`);$('#campaign-form').classList.add('hidden');$('#campaign-list').classList.add('hidden');$('.hero').classList.add('hidden');
  const [bundle,outcomes]=await Promise.all([api(`/api/campaigns/${id}/review`),api(`/api/campaigns/${id}/outcomes`)]);const c=bundle.campaign;const job=c.job||{};
  const variants=bundle.variants||[];const selectedSources=new Set(variants.map(v=>v.source_item_id));
  $('#campaign-detail').innerHTML=`<div class="detail-head"><div><p class="eyebrow">${esc(c.status)}</p><h2>${esc(c.name)}</h2></div><button class="quiet" id="back">← All campaigns</button></div>
  <div class="stats"><div class="stat"><b>${c.sources.length}</b><span>approved sources</span></div><div class="stat"><b>${c.successful_examples.length}</b><span>successful examples</span></div><div class="stat"><b>${variants.length}</b><span>rendered variants</span></div><div class="stat"><b>${selectedSources.size}</b><span>winning sources</span></div></div>
  ${c.status!=='awaiting_review'?`<div class="panel"><h3>Durable processing</h3><p>Current stage: <span class="code">${esc(job.current_stage||'not submitted')}</span>. The database-backed worker continues without this browser.</p><button id="run-worker" class="secondary">Run remaining stages now</button></div>`:''}
  ${bundle.strategy?`<div class="panel"><p class="eyebrow">Strategy brief</p><h3>${esc(bundle.strategy.brief.recommendation)}</h3><p class="muted">${esc((bundle.strategy.brief.uncertainty||[]).join(' '))}</p></div>`:''}
  <div id="variants">${variants.map(variantCard).join('') || '<p class="muted">No review variants yet.</p>'}</div>
  ${outcomes.preference_market_disagreements.length?`<div class="panel"><p class="eyebrow">Learning signal</p><h3>${outcomes.preference_market_disagreements.length} user/market outcome disagreement(s)</h3><p class="muted">Human preference and observed market performance are stored independently so policy evaluation can investigate the difference.</p></div>`:''}
  ${outcomes.summary.total_revenue?`<div class="panel"><p class="eyebrow">Observed return</p><h3>£${outcomes.summary.total_revenue.toFixed(2)} total · £${outcomes.summary.revenue_per_clip?.toFixed(2)||'—'} per clip · £${outcomes.summary.revenue_per_human_hour?.toFixed(2)||'—'} per human hour</h3></div>`:''}
  ${c.status==='awaiting_review'?`<div class="panel"><h3>How did ALPHA do?</h3><div class="review-box"><select id="feedback-rating"><option value="">Rating</option><option>5</option><option>4</option><option>3</option><option>2</option><option>1</option></select><input id="feedback-text" placeholder="What should ALPHA learn?"><button id="send-feedback" class="secondary">Save feedback</button></div></div>`:''}`;
  $('#campaign-detail').classList.remove('hidden');$('#back').onclick=()=>{history.replaceState({},'','/');state.campaignId=null;$('#campaign-detail').classList.add('hidden');$('#campaign-list').classList.remove('hidden');$('.hero').classList.remove('hidden');loadCampaigns()};
  if($('#run-worker'))$('#run-worker').onclick=async()=>{notice('Worker is processing persisted stages…');await api('/api/dev/worker/run-until-idle',{method:'POST'});openCampaign(id)};
  $$('.review-action').forEach(button=>button.onclick=()=>review(button.dataset.id,button.dataset.decision));
  $$('.publish-action').forEach(button=>button.onclick=()=>publish(button.dataset.id));
  $$('.revise-rule').forEach(button=>button.onclick=()=>reviseRule(button.dataset.requirement,button.dataset.expected));
  if($('#send-feedback'))$('#send-feedback').onclick=async()=>{await api(`/api/campaigns/${id}/feedback`,{method:'POST',body:JSON.stringify({rating:+$('#feedback-rating').value||null,feedback_text:$('#feedback-text').value})});notice('Feedback stored in the learning record.')};
}

function variantCard(v){
  const qa=v.qa_status==='passed';const approved=v.reviews.some(r=>r.decision==='approve');
  const bars=Object.entries(v.scores).sort((a,b)=>b[1]-a[1]).slice(0,8).map(([k,val])=>`<div><div class="score-row"><span>${esc(k.replaceAll('_',' '))}</span><b>${Math.round(val*100)}</b></div><div class="bar"><span style="width:${val*100}%"></span></div></div>`).join('');
  const compliance=(v.deterministic_qa.checks||[]).map(check=>`<div><span class="pill ${check.passed?'pass':'fail'}">${check.passed?'PASS':'BLOCK'} · ${esc(check.key)}</span>${!check.passed&&check.requirement_id?`<button class="quiet revise-rule" data-requirement="${check.requirement_id}" data-expected="${esc(JSON.stringify(check.expected))}">Revise rule</button>`:''}</div>`).join('');
  return `<article class="variant"><div class="video-frame"><video controls preload="metadata" src="/api/variants/${v.id}/media"></video></div><div><div class="score-row"><div><span class="pill ${qa?'pass':'fail'}">QA ${esc(v.qa_status)}</span><span class="pill">${esc(v.discovery_pass)}</span><span class="pill">v${v.version}</span></div><span class="score">${Math.round(v.predicted_score*100)}</span></div><h3>${esc(v.source_title)}</h3><p class="muted">${Math.round(v.start_ms/1000)}s–${Math.round(v.end_ms/1000)}s · approved source</p><div class="evidence"><b>Why selected</b><br>${esc(v.selection_reason)}<br><span class="code">Evidence: ${v.evidence_ids.slice(0,4).map(esc).join(', ')}</span></div><details><summary>Campaign compliance</summary>${compliance}</details><div class="score-bars">${bars}</div><div class="review-box"><button class="primary review-action" data-id="${v.id}" data-decision="approve" ${qa?'':'disabled'}>Approve</button><input id="change-${v.id}" placeholder="e.g. start 3 seconds earlier and make the watermark smaller"><button class="secondary review-action" data-id="${v.id}" data-decision="change">Request change</button><button class="danger review-action" data-id="${v.id}" data-decision="reject">Reject</button>${approved?`<button class="secondary publish-action" data-id="${v.id}">Prepare manual export</button>`:''}</div></div></article>`
}

async function review(id,decision){let feedback_text=null,reason_code=null;if(decision==='change')feedback_text=$(`#change-${id}`).value;if(decision==='reject'){reason_code=prompt('Rejection reason (bad_moment, weak_hook, captions, crop, wrong_topic, other):','weak_hook');feedback_text=prompt('Optional detail:','')}
  try{const result=await api(`/api/variants/${id}/review`,{method:'POST',body:JSON.stringify({decision,reason_code,feedback_text})});notice(decision==='change'?`New immutable variant created (${Object.keys(result.parsed_changes).join(', ')}).`:`Review recorded: ${decision}.`);openCampaign(state.campaignId)}catch(e){notice(e.message,true)}}
async function publish(id){try{const pub=await api(`/api/variants/${id}/publish`,{method:'POST',body:JSON.stringify({platform:'manual_export',caption:'Prepared by ALPHA after explicit approval.'})});notice(`Approved export ready: ${pub.export_uri}`)}catch(e){notice(e.message,true)}}
async function reviseRule(requirementId,current){const raw=prompt('New deterministic rule value:',current);if(raw===null)return;const reason=prompt('Why is this campaign rule being changed?','Corrected campaign requirement during review');if(!reason)return;let value=raw;try{value=JSON.parse(raw)}catch{}try{await api(`/api/campaigns/${state.campaignId}/requirements/${requirementId}`,{method:'PATCH',body:JSON.stringify({value,reason})});notice('Requirement revised with an audit record; QA was recalculated.');openCampaign(state.campaignId)}catch(e){notice(e.message,true)}}

$('#new-campaign').onclick=()=>{$('#campaign-form').classList.remove('hidden');$('#campaign-list').classList.add('hidden')};
$('#close-form').onclick=()=>{$('#campaign-form').classList.add('hidden');$('#campaign-list').classList.remove('hidden')};
$('#create-form').onsubmit=async event=>{event.preventDefault();const form=new FormData(event.target);const watermarkRequired=form.get('watermark_required')==='on';const position=form.get('watermark_position');const file=form.get('watermark_file');
  const payload={name:form.get('name'),owner_email:form.get('owner_email'),payout_value:+form.get('payout_value'),currency:'GBP',target_platforms:[form.get('target_platform')],research_seeds:lines(form.get('seeds')),sources:lines(form.get('sources')).map(url=>({type:url.includes('playlist')||url.includes('list=')?'youtube_playlist':'youtube_video',url})),successful_examples:lines(form.get('examples')).map(url=>({url,platform:'fixture_social'})),requirements:[{key:'max_duration_seconds',type:'deterministic',operator:'max',value:45,severity:'mandatory'},{key:'watermark_present',type:'deterministic',operator:'eq',value:watermarkRequired,severity:'mandatory'},{key:'watermark_position',type:'deterministic',operator:'eq',value:position,severity:'mandatory'},{key:'strong_hook',type:'ai_evaluated',operator:'eq',value:true,severity:'warning'}],watermark:watermarkRequired?{data_base64:await fileBase64(file.size?file:null),filename:file.name||'generated.ppm',position,opacity:+form.get('watermark_opacity')/100,padding:+form.get('watermark_padding'),size_pct:+form.get('watermark_size')/100}:null};
  try{const sourceFiles=event.target.elements.source_media.files;if(!payload.sources.length&&!sourceFiles.length)throw new Error('Add at least one approved URL or authorised local video.');if(sourceFiles.length&&!event.target.elements.source_rights.checked)throw new Error('Confirm source-media usage rights before upload.');const campaign=await api('/api/campaigns',{method:'POST',body:JSON.stringify(payload)});const accountName=form.get('target_account_name')?.trim();if(accountName){const account=await api('/api/connected-accounts',{method:'POST',body:JSON.stringify({platform:form.get('target_platform'),display_name:accountName,adapter:'manual_export'})});await api(`/api/campaigns/${campaign.id}/accounts/${account.id}`,{method:'POST'})}if(sourceFiles.length){const transcript=transcriptSegments(form.get('source_transcript'));for(const sourceFile of sourceFiles){const upload=new FormData();upload.append('media',sourceFile);upload.append('title',sourceFile.name);upload.append('transcript_json',JSON.stringify(transcript));upload.append('rights_attestation','User confirmed permission to use this source media for the campaign.');await uploadApi(`/api/campaigns/${campaign.id}/sources/import`,upload)}}await api(`/api/campaigns/${campaign.id}/submit`,{method:'POST'});notice('Campaign submitted. Durable processing has started.');openCampaign(campaign.id)}catch(e){notice(e.message,true)}};

$$('.nav-button').forEach(button=>button.onclick=async()=>{$$('.nav-button').forEach(b=>b.classList.toggle('active',b===button));$('#campaigns-view').classList.toggle('hidden',button.dataset.view!=='campaigns');$('#ledger-view').classList.toggle('hidden',button.dataset.view!=='ledger');if(button.dataset.view==='ledger'){const rows=await api('/api/research-ledger');$('#ledger-list').innerHTML=rows.map(r=>`<article class="ledger-entry"><p class="eyebrow">${esc(r.entry_type)} · confidence ${Math.round(r.confidence*100)}%</p><h3>${esc(r.finding)}</h3><p>${esc(r.decision)}</p><span class="code">Policy ${esc(r.policy_id||'n/a')} · ${new Date(r.created_at).toLocaleString()}</span></article>`).join('')||'<p class="muted">The ledger fills as campaigns are processed and experiments are evaluated.</p>'}});

async function boot(){const session=await api('/api/auth/session');if(session.required&&!session.authenticated){$('#login-view').classList.remove('hidden');$('#campaigns-view').classList.add('hidden');$('#ledger-view').classList.add('hidden');return}$('#login-view').classList.add('hidden');$('#campaigns-view').classList.remove('hidden');$('#logout').classList.toggle('hidden',!session.required);if(state.campaignId)await openCampaign(state.campaignId);else await loadCampaigns()}
$('#login-form').onsubmit=async event=>{event.preventDefault();const form=new FormData(event.target);try{await api('/api/auth/login',{method:'POST',body:JSON.stringify({email:form.get('email'),password:form.get('password')})});await boot()}catch(e){notice(e.message,true)}};
$('#logout').onclick=async()=>{await api('/api/auth/logout',{method:'POST'});state.campaignId=null;history.replaceState({},'','/');await boot()};
boot().catch(e=>notice(e.message,true));
