const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const stages = ['validate_campaign','resolve_sources','ingest_sources','analyse_successful_examples','social_research','synthesize_strategy','discover_candidates','rank_candidates','plan_enrichment','render','qa','review_ready'];
const state = {campaignId: new URLSearchParams(location.search).get('campaign'),pollTimer:null,listPollTimer:null,view:'campaigns'};
let pendingRequests=0;let loadingHideTimer=null;

function requestMessage(path,method='GET'){
  if(path.includes('/worker/'))return 'Processing campaign stages…';
  if(path.includes('/review'))return method==='POST'?'Saving review and rendering changes…':'Loading campaign review…';
  if(path.includes('/publish'))return 'Preparing approved export…';
  if(path.includes('/research-ledger'))return 'Loading research ledger…';
  if(path.includes('/feedback'))return 'Saving feedback…';
  if(path.includes('/performance'))return 'Saving performance data…';
  if(path.includes('/auth/login'))return 'Signing in…';
  if(path.includes('/auth/logout'))return 'Signing out…';
  if(path.includes('/submit'))return 'Starting background processing…';
  if(path.includes('/sources/import'))return 'Uploading authorised source…';
  if(path.includes('/assets'))return method==='POST'?'Uploading enrichment asset…':'Loading asset library…';
  if(path.includes('/campaigns/'))return method==='GET'?'Loading campaign data…':'Saving campaign data…';
  if(path==='/api/campaigns')return method==='GET'?'Loading campaigns…':'Creating campaign…';
  return 'Loading data…';
}
function beginLoading(message){pendingRequests+=1;clearTimeout(loadingHideTimer);$('#global-loading-message').textContent=message;$('#global-loading').classList.remove('hidden');$('main').setAttribute('aria-busy','true')}
function endLoading(){pendingRequests=Math.max(0,pendingRequests-1);if(pendingRequests)return;loadingHideTimer=setTimeout(()=>{if(pendingRequests===0){$('#global-loading').classList.add('hidden');$('main').removeAttribute('aria-busy')}},120)}
function apiError(data,fallback){const detail=data?.detail;if(typeof detail==='string')return detail;if(Array.isArray(detail))return detail.map(item=>`${item.loc?.slice(1).join(' → ')||'request'}: ${item.msg||'invalid value'}`).join('; ');if(detail&&typeof detail==='object')return detail.message||JSON.stringify(detail);return fallback}

async function api(path, options={}) {
  const {loading=true,...fetchOptions}=options;
  if(loading)beginLoading(requestMessage(path,fetchOptions.method||'GET'));
  try{
    const csrf=document.cookie.split('; ').find(value=>value.startsWith('alpha_csrf='))?.split('=').slice(1).join('=');
    const response = await fetch(path,{headers:{'content-type':'application/json',...(csrf?{'x-alpha-csrf':decodeURIComponent(csrf)}:{}),...(fetchOptions.headers||{})},...fetchOptions});
    const data = await response.json().catch(()=>({}));
    if(!response.ok) throw new Error(apiError(data,`Request failed (${response.status})`));
    return data;
  }finally{if(loading)endLoading()}
}
async function uploadApi(path, body) {
  beginLoading(requestMessage(path,'POST'));
  try{
    const csrf=document.cookie.split('; ').find(value=>value.startsWith('alpha_csrf='))?.split('=').slice(1).join('=');
    const response = await fetch(path,{method:'POST',headers:{...(csrf?{'x-alpha-csrf':decodeURIComponent(csrf)}:{})},body});
    const data = await response.json().catch(()=>({}));
    if(!response.ok) throw new Error(apiError(data,`Upload failed (${response.status})`));
    return data;
  }finally{endLoading()}
}
function notice(message,error=false){const el=$('#notice');el.textContent=message;el.classList.toggle('error',error);el.classList.remove('hidden');setTimeout(()=>el.classList.add('hidden'),6000)}
function lines(value){return value.split(/\r?\n/).map(v=>v.trim()).filter(Boolean)}
function transcriptSegments(value){return lines(value).map(line=>{const parts=line.split('|');if(parts.length<3)throw new Error('Each transcript line needs start_ms | end_ms | text');return {start_ms:+parts[0].trim(),end_ms:+parts[1].trim(),text:parts.slice(2).join('|').trim()}})}
function fileBase64(file){return new Promise((resolve,reject)=>{if(!file)return resolve(null);const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=reject;r.readAsDataURL(file)})}
function esc(value){const d=document.createElement('div');d.textContent=String(value??'');return d.innerHTML}
function createProgress(message){const button=$('#create-submit');const status=$('#create-status');button.disabled=true;button.textContent='Working…';$('#create-form').setAttribute('aria-busy','true');status.textContent=message}
function createReady(message='You can close this page after submitting.'){const button=$('#create-submit');const status=$('#create-status');button.disabled=false;button.textContent='Create and submit';$('#create-form').removeAttribute('aria-busy');status.textContent=message}

function stopPolling(){clearTimeout(state.pollTimer);clearTimeout(state.listPollTimer);state.pollTimer=null;state.listPollTimer=null}
function stageLabel(stage){return String(stage||'').replaceAll('_',' ')}
function completedCount(job){return Math.min(stages.length,(job?.checkpoint?.completed_stages||job?.job_checkpoint?.completed_stages||[]).length)}
function jobPresentation(c){
  const job=c.job||{status:c.job_status,current_stage:c.current_stage,checkpoint:c.job_checkpoint,error:c.job_error};
  if(c.status==='draft'||!job.status)return {kind:'draft',label:'Draft',title:'Ready when you are',detail:'This campaign has not been submitted. You can start durable background processing or permanently delete the draft.'};
  if(c.status==='awaiting_review'||job.status==='awaiting_review')return {kind:'ready',label:'Ready for review',title:'Processing complete',detail:'Rendered clips are ready for your approval.'};
  if(job.status==='leased')return {kind:'active',label:'Worker active',title:`Processing ${stageLabel(job.current_stage)}`,detail:'A remote worker currently holds the job lease. You can close this browser; progress is checkpointed.'};
  if(job.status==='retry')return {kind:'retry',label:'Retry scheduled',title:`Waiting to retry ${stageLabel(job.current_stage)}`,detail:`A temporary error occurred${job.error?.message?`: ${job.error.message}`:'.'} The durable worker will retry automatically${job.available_at?` after ${new Date(job.available_at).toLocaleString()}`:''}.`};
  if(job.status==='failed')return {kind:'failed',label:'Needs attention',title:`Stopped at ${stageLabel(job.current_stage)}`,detail:job.error?.message||'The stage exhausted its automatic retries. You can safely requeue it from its last checkpoint.'};
  return {kind:'queued',label:'Queued',title:`Waiting to process ${stageLabel(job.current_stage)}`,detail:'The campaign is safely queued. The scheduled remote worker will continue automatically; this browser does not need to stay open.'};
}
function campaignProgress(c){if(c.status==='awaiting_review'||c.job_status==='awaiting_review')return 100;if(c.status==='draft')return 0;return Math.round(completedCount(c.job||c)/stages.length*100)}
function campaignCards(campaigns){return campaigns.length?campaigns.map(c=>{const p=jobPresentation(c);return `<article class="campaign-card" tabindex="0" role="button" aria-label="Open ${esc(c.name)}" data-id="${c.id}"><div class="meta-row"><span class="status ${p.kind}">${esc(p.label)}</span><span class="muted">${new Date(c.updated_at||c.created_at).toLocaleDateString()}</span></div><h3>${esc(c.name)}</h3><p class="muted">${c.source_count} approved sources · ${c.variant_count} variants</p><p class="job-summary">${esc(p.title)}</p><div class="progress" aria-label="${campaignProgress(c)}% complete"><span style="width:${campaignProgress(c)}%"></span></div></article>`}).join(''):'<div class="empty-state panel"><h3>No campaigns yet</h3><p class="muted">Create your first campaign to begin research and clipping.</p><button class="primary" id="empty-new-campaign">New campaign</button></div>'}
function bindCampaignCards(){$$('.campaign-card').forEach(card=>{card.onclick=()=>openCampaign(card.dataset.id);card.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();openCampaign(card.dataset.id)}}});if($('#empty-new-campaign'))$('#empty-new-campaign').onclick=showCampaignForm}

async function loadCampaigns({background=false}={}){
  stopPolling();
  try{const campaigns=await api('/api/campaigns',{loading:!background});$('#campaign-list').innerHTML=campaignCards(campaigns);bindCampaignCards();
    if(state.view==='campaigns'&&!state.campaignId)state.listPollTimer=setTimeout(()=>loadCampaigns({background:true}),10000);
  }catch(e){if(!background){$('#campaign-list').innerHTML=`<div class="error-state panel"><h3>Campaigns could not be loaded</h3><p>${esc(e.message)}</p><button class="secondary" id="retry-campaigns">Try again</button></div>`;$('#retry-campaigns').onclick=()=>loadCampaigns();notice(e.message,true)}else if(state.view==='campaigns'&&!state.campaignId){state.listPollTimer=setTimeout(()=>loadCampaigns({background:true}),15000)}}
}

function processingPanel(c){const job=c.job||{};const p=jobPresentation(c);const progress=campaignProgress({...c,job_status:job.status,job_checkpoint:job.checkpoint});const canSubmit=(c.sources||[]).length>0;return `<div id="processing-panel" class="panel processing-panel ${p.kind}" aria-live="polite"><div class="processing-head"><div><p class="eyebrow">${esc(p.label)}</p><h3>${esc(p.title)}</h3></div>${p.kind==='active'?'<span class="inline-spinner" aria-hidden="true"></span>':''}</div><p>${esc(p.detail)}</p>${p.kind==='draft'&&!canSubmit?'<p class="notice error">Add at least one approved source before processing. This partial draft can be deleted and recreated from the intake form.</p>':''}${p.kind!=='draft'?`<div class="progress large"><span style="width:${progress}%"></span></div><p class="muted">${progress}% complete · ${completedCount(job)} of ${stages.length} stages checkpointed${job.updated_at?` · updated ${new Date(job.updated_at).toLocaleString()}`:''}</p>`:''}<div class="actions">${p.kind==='draft'?`<button id="submit-draft" class="primary" ${canSubmit?'':'disabled'}>Start processing</button><button id="delete-draft" class="danger">Delete draft</button>`:p.kind==='failed'?'<button id="retry-job" class="primary">Retry failed stage</button>':'<button id="refresh-status" class="secondary">Refresh status</button>'}</div></div>`}
function bindProcessingActions(c){
  if($('#refresh-status'))$('#refresh-status').onclick=()=>refreshCampaign(c.id,true);
  if($('#submit-draft'))$('#submit-draft').onclick=async()=>{try{await api(`/api/campaigns/${c.id}/submit`,{method:'POST'});notice('Campaign submitted. Background processing will continue automatically.');await openCampaign(c.id)}catch(e){notice(e.message,true)}};
  if($('#retry-job'))$('#retry-job').onclick=async()=>{try{await api(`/api/campaigns/${c.id}/retry`,{method:'POST'});notice('Failed stage requeued from its last checkpoint.');await openCampaign(c.id)}catch(e){notice(e.message,true)}};
  if($('#delete-draft'))$('#delete-draft').onclick=async()=>{if(!confirm(`Permanently delete the draft “${c.name}” and its uploaded files? This cannot be undone.`))return;try{const result=await api(`/api/campaigns/${c.id}`,{method:'DELETE'});if(result.object_cleanup_failures?.length)notice('Draft deleted, but some unreferenced storage objects could not be removed.',true);else notice('Draft campaign permanently deleted.');showCampaignList()}catch(e){notice(e.message,true)}};
}
function shouldPoll(c){return c.status==='processing'&&['queued','leased','retry'].includes(c.job?.status)}
async function refreshCampaign(id,manual=false){
  if(state.campaignId!==id)return;
  try{const c=await api(`/api/campaigns/${id}`,{loading:manual});if(state.campaignId!==id)return;if(c.status==='awaiting_review'||c.job?.status==='awaiting_review'){await openCampaign(id);return}const panel=$('#processing-panel');if(panel){panel.outerHTML=processingPanel(c);bindProcessingActions(c)}const eyebrow=$('#campaign-status');if(eyebrow)eyebrow.textContent=jobPresentation(c).label;if(shouldPoll(c))state.pollTimer=setTimeout(()=>refreshCampaign(id),5000)}catch(e){if(manual)notice(e.message,true);if(state.campaignId===id)state.pollTimer=setTimeout(()=>refreshCampaign(id),10000)}
}

async function openCampaign(id){
  stopPolling();state.campaignId=id;history.replaceState({},'',`/?campaign=${id}`);$('#campaign-form').classList.add('hidden');$('#campaign-list').classList.add('hidden');$('.hero').classList.add('hidden');
  $('#campaign-detail').classList.remove('hidden');$('#campaign-detail').innerHTML='<div class="panel skeleton-panel" aria-label="Loading campaign"><span class="inline-spinner" aria-hidden="true"></span><h3>Loading campaign…</h3><p class="muted">Fetching processing status, rendered clips and outcomes.</p></div>';
  try{
    const [bundle,outcomes]=await Promise.all([api(`/api/campaigns/${id}/review`),api(`/api/campaigns/${id}/outcomes`)]);const c=bundle.campaign;
    const variants=bundle.variants||[];const selectedSources=new Set(variants.map(v=>v.source_item_id));const p=jobPresentation(c);
    $('#campaign-detail').innerHTML=`<div class="detail-head"><div><p id="campaign-status" class="eyebrow">${esc(p.label)}</p><h2>${esc(c.name)}</h2></div><button class="quiet" id="back">← All campaigns</button></div>
    <div class="stats"><div class="stat"><b>${c.sources.length}</b><span>approved sources</span></div><div class="stat"><b>${c.successful_examples.length}</b><span>successful examples</span></div><div class="stat"><b>${variants.length}</b><span>rendered variants</span></div><div class="stat"><b>${selectedSources.size}</b><span>winning sources</span></div></div>
    ${c.status!=='awaiting_review'?processingPanel(c):'<div class="panel ready-panel"><p class="eyebrow">Ready for review</p><h3>Processing complete</h3><p>Review each compliant clip below. Publishing still requires your explicit approval.</p></div>'}
    ${bundle.strategy?`<div class="panel"><p class="eyebrow">Strategy brief</p><h3>${esc(bundle.strategy.brief.recommendation)}</h3><p class="muted">${esc((bundle.strategy.brief.uncertainty||[]).join(' '))}</p></div>`:''}
    <div id="variants">${variants.map(variantCard).join('') || (c.status==='awaiting_review'?'<div class="empty-state panel"><h3>No review variants were produced</h3><p class="muted">The campaign completed without a compliant candidate. Check the research evidence and campaign requirements.</p></div>':'<div class="empty-state panel"><h3>Clips are not ready yet</h3><p class="muted">Candidates and rendered variants will appear automatically as the worker completes the pipeline.</p></div>')}</div>
    ${outcomes.preference_market_disagreements.length?`<div class="panel"><p class="eyebrow">Learning signal</p><h3>${outcomes.preference_market_disagreements.length} user/market outcome disagreement(s)</h3><p class="muted">Human preference and observed market performance are stored independently so policy evaluation can investigate the difference.</p></div>`:''}
    ${outcomes.summary.total_revenue?`<div class="panel"><p class="eyebrow">Observed return</p><h3>£${outcomes.summary.total_revenue.toFixed(2)} total · £${outcomes.summary.revenue_per_clip?.toFixed(2)||'—'} per clip · £${outcomes.summary.revenue_per_human_hour?.toFixed(2)||'—'} per human hour</h3></div>`:''}
    ${c.status==='awaiting_review'?`<div class="panel"><h3>How did ALPHA do?</h3><div class="review-box"><label class="sr-only" for="feedback-rating">Rating</label><select id="feedback-rating"><option value="">Rating</option><option>5</option><option>4</option><option>3</option><option>2</option><option>1</option></select><label class="sr-only" for="feedback-text">Feedback</label><input id="feedback-text" placeholder="What should ALPHA learn?"><button id="send-feedback" class="secondary">Save feedback</button></div></div>`:''}`;
    $('#back').onclick=showCampaignList;bindProcessingActions(c);
    $$('.review-action').forEach(button=>button.onclick=()=>review(button.dataset.id,button.dataset.decision));
    $$('.publish-action').forEach(button=>button.onclick=()=>publish(button.dataset.id));
    $$('.revise-rule').forEach(button=>button.onclick=()=>reviseRule(button.dataset.requirement,button.dataset.expected));
    $$('.video-frame video').forEach(video=>{const frame=video.closest('.video-frame');const ready=()=>frame.classList.remove('loading');video.addEventListener('loadeddata',ready);video.addEventListener('canplay',ready);video.addEventListener('waiting',()=>frame.classList.add('loading'));video.addEventListener('error',()=>{frame.classList.remove('loading');frame.classList.add('media-error');const status=frame.querySelector('.video-loading');status.textContent='Preview unavailable'})});
    if($('#send-feedback'))$('#send-feedback').onclick=async()=>{try{await api(`/api/campaigns/${id}/feedback`,{method:'POST',body:JSON.stringify({rating:+$('#feedback-rating').value||null,feedback_text:$('#feedback-text').value})});notice('Feedback stored in the learning record.')}catch(e){notice(e.message,true)}};
    if(shouldPoll(c))state.pollTimer=setTimeout(()=>refreshCampaign(id),5000);
  }catch(e){$('#campaign-detail').innerHTML=`<div class="error-state panel"><h3>Campaign could not be loaded</h3><p>${esc(e.message)}</p><div class="actions"><button class="secondary" id="retry-campaign">Try again</button><button class="quiet" id="back">← All campaigns</button></div></div>`;$('#retry-campaign').onclick=()=>openCampaign(id);$('#back').onclick=showCampaignList;notice(e.message,true)}
}

function showCampaignList(){stopPolling();history.replaceState({},'','/');state.campaignId=null;$('#campaign-detail').classList.add('hidden');$('#campaign-form').classList.add('hidden');$('#campaign-list').classList.remove('hidden');$('.hero').classList.remove('hidden');loadCampaigns()}
function showCampaignForm(){stopPolling();createReady();$('#campaign-detail').classList.add('hidden');$('#campaign-form').classList.remove('hidden');$('#campaign-list').classList.add('hidden')}

function variantCard(v){
  const qa=v.qa_status==='passed';const approved=v.reviews.some(r=>r.decision==='approve');
  const bars=Object.entries(v.scores).sort((a,b)=>b[1]-a[1]).slice(0,8).map(([k,val])=>`<div><div class="score-row"><span>${esc(k.replaceAll('_',' '))}</span><b>${Math.round(val*100)}</b></div><div class="bar"><span style="width:${val*100}%"></span></div></div>`).join('');
  const compliance=(v.deterministic_qa.checks||[]).map(check=>`<div><span class="pill ${check.passed?'pass':'fail'}">${check.passed?'PASS':'BLOCK'} · ${esc(check.key)}</span>${!check.passed&&check.requirement_id?`<button class="quiet revise-rule" data-requirement="${check.requirement_id}" data-expected="${esc(JSON.stringify(check.expected))}">Revise rule</button>`:''}</div>`).join('');
  const events=v.render_spec?.enrichment?.events||[];const timeline=events.map(e=>`<li><span class="code">${Math.floor(e.start_ms/60000)}:${String(Math.floor(e.start_ms/1000)%60).padStart(2,'0')}</span> <b>${esc(e.type.replaceAll('_',' '))}</b> — ${esc(e.title||e.purpose||'native edit')}<small>${esc(e.reason||'')}</small></li>`).join('');
  return `<article class="variant"><div class="video-frame loading"><span class="video-loading"><span class="inline-spinner" aria-hidden="true"></span> Loading preview…</span><video controls preload="metadata" src="/api/variants/${v.id}/media"></video></div><div><div class="score-row"><div><span class="pill ${qa?'pass':'fail'}">QA ${esc(v.qa_status)}</span><span class="pill">${esc(v.discovery_pass)}</span><span class="pill">v${v.version}</span></div><span class="score">${Math.round(v.predicted_score*100)}</span></div><h3>${esc(v.source_title)}</h3><p class="muted">${Math.round(v.start_ms/1000)}s–${Math.round(v.end_ms/1000)}s · approved source</p><div class="evidence"><b>Why selected</b><br>${esc(v.selection_reason)}<br><span class="code">Evidence: ${v.evidence_ids.slice(0,4).map(esc).join(', ')}</span></div>${timeline?`<details open><summary>Enrichment timeline (${events.length})</summary><ol class="timeline">${timeline}</ol></details>`:'<p class="muted">No enrichment was warranted for this candidate.</p>'}<details><summary>Campaign compliance</summary>${compliance}</details><div class="score-bars">${bars}</div><div class="review-box"><button class="primary review-action" data-id="${v.id}" data-decision="approve" ${qa?'':'disabled'}>Approve</button><input id="change-${v.id}" placeholder="remove the meme, make the music quieter and add a zoom at the punchline"><button class="secondary review-action" data-id="${v.id}" data-decision="change">Request change</button><button class="danger review-action" data-id="${v.id}" data-decision="reject">Reject</button>${approved?`<button class="secondary publish-action" data-id="${v.id}">Prepare manual export</button>`:''}</div></div></article>`
}

async function review(id,decision){let feedback_text=null,reason_code=null;if(decision==='change')feedback_text=$(`#change-${id}`).value;if(decision==='reject'){reason_code=prompt('Rejection reason (bad_moment, weak_hook, captions, crop, wrong_topic, other):','weak_hook');feedback_text=prompt('Optional detail:','')}
  try{const result=await api(`/api/variants/${id}/review`,{method:'POST',body:JSON.stringify({decision,reason_code,feedback_text})});notice(decision==='change'?`New immutable variant created (${Object.keys(result.parsed_changes).join(', ')}).`:`Review recorded: ${decision}.`);openCampaign(state.campaignId)}catch(e){notice(e.message,true)}}
async function publish(id){try{const pub=await api(`/api/variants/${id}/publish`,{method:'POST',body:JSON.stringify({platform:'manual_export',caption:'Prepared by ALPHA after explicit approval.'})});notice(`Approved export ready: ${pub.export_uri}`)}catch(e){notice(e.message,true)}}
async function reviseRule(requirementId,current){const raw=prompt('New deterministic rule value:',current);if(raw===null)return;const reason=prompt('Why is this campaign rule being changed?','Corrected campaign requirement during review');if(!reason)return;let value=raw;try{value=JSON.parse(raw)}catch{}try{await api(`/api/campaigns/${state.campaignId}/requirements/${requirementId}`,{method:'PATCH',body:JSON.stringify({value,reason})});notice('Requirement revised with an audit record; QA was recalculated.');openCampaign(state.campaignId)}catch(e){notice(e.message,true)}}

$('#new-campaign').onclick=showCampaignForm;
$('#close-form').onclick=showCampaignList;
$('#create-form').onsubmit=async event=>{
  event.preventDefault();
  if($('#create-submit').disabled)return;
  createProgress('Validating campaign details…');
  let succeeded=false;let createdCampaign=null;
  try{
    const form=new FormData(event.target);const watermarkRequired=form.get('watermark_required')==='on';const position=form.get('watermark_position');const file=form.get('watermark_file');
    const sourceFiles=event.target.elements.source_media.files;const externalIds=lines(form.get('source_external_ids'));const assetInputs=[['music_asset','music'],['meme_asset','meme_image'],['broll_asset','broll']];const selectedAssets=assetInputs.filter(([name])=>event.target.elements[name].files.length);
    const enrichment={music_allowed:form.get('music_allowed')==='on',memes_allowed:form.get('memes_allowed')==='on',broll_allowed:form.get('broll_allowed')==='on',sound_effects_allowed:form.get('sound_effects_allowed')==='on',external_images_allowed:form.get('external_images_allowed')==='on',external_video_allowed:form.get('external_video_allowed')==='on',required_asset_source:form.get('required_asset_source')||null,prohibited_asset_types:form.get('prohibited_asset_types').split(',').map(v=>v.trim()).filter(Boolean),max_inserts:+form.get('max_inserts'),max_insert_duration_seconds:+form.get('max_insert_duration_seconds'),music_volume_min_db:+form.get('music_volume_min_db'),music_volume_max_db:+form.get('music_volume_max_db'),ducking_required:form.get('ducking_required')==='on',additional_instructions:form.get('enrichment_instructions')};
    const payload={name:form.get('name'),owner_email:form.get('owner_email'),payout_value:+form.get('payout_value'),currency:'GBP',target_platforms:[form.get('target_platform')],research_seeds:lines(form.get('seeds')),sources:lines(form.get('sources')).map(url=>({type:url.includes('playlist')||url.includes('list=')?'youtube_playlist':'youtube_video',url})),successful_examples:lines(form.get('examples')).map(url=>({url,platform:'fixture_social'})),requirements:[{key:'max_duration_seconds',type:'deterministic',operator:'max',value:45,severity:'mandatory'},{key:'watermark_present',type:'deterministic',operator:'eq',value:watermarkRequired,severity:'mandatory'},{key:'watermark_position',type:'deterministic',operator:'eq',value:position,severity:'mandatory'},{key:'strong_hook',type:'ai_evaluated',operator:'eq',value:true,severity:'warning'}],watermark:watermarkRequired?{data_base64:await fileBase64(file.size?file:null),filename:file.name||'generated.ppm',position,opacity:+form.get('watermark_opacity')/100,padding:+form.get('watermark_padding'),size_pct:+form.get('watermark_size')/100}:null,raw_brief:form.get('raw_brief'),enrichment};
    if(!payload.sources.length&&!sourceFiles.length)throw new Error('Add at least one approved URL or authorised local video.');
    if(sourceFiles.length&&!event.target.elements.source_rights.checked)throw new Error('Confirm source-media usage rights before upload.');
    if(selectedAssets.length&&(!event.target.elements.asset_rights.checked||!event.target.elements.asset_commercial.checked))throw new Error('Confirm rights and commercial-use permission for enrichment assets.');
    if(externalIds.length&&externalIds.length!==sourceFiles.length)throw new Error('Provide one YouTube video ID for each selected source file.');
    createProgress('Creating the campaign…');
    const campaign=await api('/api/campaigns',{method:'POST',body:JSON.stringify(payload)});createdCampaign=campaign;
    const accountName=form.get('target_account_name')?.trim();
    if(accountName){createProgress('Connecting the export account…');const account=await api('/api/connected-accounts',{method:'POST',body:JSON.stringify({platform:form.get('target_platform'),display_name:accountName,adapter:'manual_export'})});await api(`/api/campaigns/${campaign.id}/accounts/${account.id}`,{method:'POST'})}
    if(sourceFiles.length){const transcript=transcriptSegments(form.get('source_transcript'));for(const [index,sourceFile] of [...sourceFiles].entries()){createProgress(`Uploading source video ${index+1} of ${sourceFiles.length}…`);const upload=new FormData();upload.append('media',sourceFile);upload.append('title',sourceFile.name);upload.append('transcript_json',JSON.stringify(transcript));upload.append('rights_attestation','User confirmed permission to use this source media for the campaign.');if(externalIds[index])upload.append('external_id',externalIds[index]);await uploadApi(`/api/campaigns/${campaign.id}/sources/import`,upload)}}
    for(const [index,[name,assetType]] of selectedAssets.entries()){createProgress(`Uploading enrichment asset ${index+1} of ${selectedAssets.length}…`);const assetFile=event.target.elements[name].files[0];const upload=new FormData();upload.append('asset',assetFile);upload.append('asset_type',assetType);upload.append('title',assetFile.name);upload.append('tags_json',JSON.stringify(form.get('asset_tags').split(',').map(v=>v.trim()).filter(Boolean)));upload.append('semantic_description',`${assetType} supplied for this campaign`);upload.append('licence',form.get('asset_licence'));upload.append('permitted_commercial_use','true');upload.append('rights_attestation','User confirmed permission and commercial use rights for this campaign asset.');if(form.get('asset_source_url'))upload.append('source_url',form.get('asset_source_url'));await uploadApi(`/api/campaigns/${campaign.id}/assets`,upload)}
    createProgress('Starting durable background processing…');
    await api(`/api/campaigns/${campaign.id}/submit`,{method:'POST'});
    succeeded=true;createProgress('Campaign submitted. Background processing has started.');notice('Campaign submitted. Durable processing has started.');await openCampaign(campaign.id);
  }catch(e){if(succeeded){notice(`Campaign submitted, but the dashboard could not refresh: ${e.message}`,true)}else if(createdCampaign){notice(`A draft was saved, but setup did not finish: ${e.message}`,true);createReady('A partial draft was saved. Open it to start processing if it has a source, or delete it and try again.');await openCampaign(createdCampaign.id)}else{notice(e.message,true);createReady(`Submission failed: ${e.message} Correct the form and try again.`)}}
  finally{if(succeeded)createReady('Campaign submitted. Background processing is running.')}
};

async function loadLedger(){
  $('#ledger-list').innerHTML='<div class="panel skeleton-panel"><span class="inline-spinner" aria-hidden="true"></span><h3>Loading research ledger…</h3></div>';
  try{const rows=await api('/api/research-ledger');$('#ledger-list').innerHTML=rows.map(r=>`<article class="ledger-entry"><p class="eyebrow">${esc(r.entry_type)} · confidence ${Math.round(r.confidence*100)}%</p><h3>${esc(r.finding)}</h3><p>${esc(r.decision)}</p><span class="code">Policy ${esc(r.policy_id||'n/a')} · ${new Date(r.created_at).toLocaleString()}</span></article>`).join('')||'<div class="empty-state panel"><h3>No research decisions yet</h3><p class="muted">The ledger fills as campaigns are processed and experiments are evaluated.</p></div>'}catch(e){$('#ledger-list').innerHTML=`<div class="error-state panel"><h3>Research ledger could not be loaded</h3><p>${esc(e.message)}</p><button class="secondary" id="retry-ledger">Try again</button></div>`;$('#retry-ledger').onclick=loadLedger}
}
$$('.nav-button').forEach(button=>button.onclick=async()=>{stopPolling();state.view=button.dataset.view;$$('.nav-button').forEach(b=>b.classList.toggle('active',b===button));$('#campaigns-view').classList.toggle('hidden',state.view!=='campaigns');$('#ledger-view').classList.toggle('hidden',state.view!=='ledger');if(state.view==='ledger')await loadLedger();else if(state.campaignId)await openCampaign(state.campaignId);else await loadCampaigns()});

async function boot(){const session=await api('/api/auth/session');$('#provider-mode').textContent=`${String(session.provider_mode||'unknown').toUpperCase()} PROVIDERS`;if(session.required&&!session.authenticated){$('#login-view').classList.remove('hidden');$('#campaigns-view').classList.add('hidden');$('#ledger-view').classList.add('hidden');return}$('#login-view').classList.add('hidden');$('#campaigns-view').classList.remove('hidden');$('#logout').classList.toggle('hidden',!session.required);if(state.campaignId)await openCampaign(state.campaignId);else await loadCampaigns()}
$('#login-form').onsubmit=async event=>{event.preventDefault();const form=new FormData(event.target);try{await api('/api/auth/login',{method:'POST',body:JSON.stringify({email:form.get('email'),password:form.get('password')})});await boot()}catch(e){notice(e.message,true)}};
$('#logout').onclick=async()=>{try{await api('/api/auth/logout',{method:'POST'});stopPolling();state.campaignId=null;history.replaceState({},'','/');await boot()}catch(e){notice(e.message,true)}};
boot().catch(e=>{stopPolling();$('#campaign-list').innerHTML=`<div class="error-state panel"><h3>ALPHA could not start</h3><p>${esc(e.message)}</p><button class="secondary" id="retry-boot">Try again</button></div>`;$('#retry-boot').onclick=()=>boot();notice(e.message,true)});
