const $=id=>document.getElementById(id);
const API=localStorage.getItem('vc_api')||''; // Set this to your deployed HTTPS backend URL.
function validYT(s){try{let u=new URL(s);return ['youtube.com','www.youtube.com','m.youtube.com','youtu.be'].includes(u.hostname)}catch{return false}}
$('go').onclick=async()=>{
 const f=$('file').files[0],u=$('url').value.trim();
 $('results').innerHTML='';
 if(!f&&!u){$('status').textContent='કૃપા કરીને વીડિયો અપલોડ કરો અથવા YouTube લિંક નાખો.';return}
 if(u&&!validYT(u)){$('status').textContent='માન્ય YouTube લિંક નાખો.';return}
 if(u&&!f){$('status').textContent='YouTube લિંક નોંધાઈ છે, પરંતુ માત્ર જાહેર URLથી ડાઉનલોડ શક્ય નથી. પોતાના/અધિકૃત વીડિયોની મૂળ ફાઇલ અપલોડ કરો. YouTube OAuth આધારિત ઇમ્પોર્ટ અલગથી કનેક્ટ કરવો પડશે.';return}
 if(!API){$('status').textContent='Backend સરનામું સેટ કરેલું નથી. app.js માં API_BASE બદલીને તમારા HTTPS backend નું સરનામું મૂકો.';return}
 const fd=new FormData();fd.append('video',f);fd.append('count',$('count').value);fd.append('max_duration',$('duration').value);fd.append('language',$('lang').value);
 $('go').disabled=true;$('status').textContent='વીડિયો અપલોડ થઈ રહ્યો છે…';$('progress').classList.remove('hidden');$('bar').style.width='8%';
 try{
  const r=await fetch(API+'/api/jobs',{method:'POST',body:fd});if(!r.ok)throw new Error(await r.text());const j=await r.json();
  $('bar').style.width='35%';$('status').textContent='AI ટ્રાન્સક્રિપ્શન અને ક્લિપ પસંદગી ચાલી રહી છે…';
  let done=false;
  while(!done){await new Promise(x=>setTimeout(x,3000));const s=await fetch(API+'/api/jobs/'+j.job_id);if(!s.ok)throw new Error('Job status મળ્યો નથી');const d=await s.json();$('status').textContent=d.message||d.status;$('bar').style.width=(d.progress||40)+'%';if(d.status==='completed'){done=true;$('bar').style.width='100%';$('results').innerHTML='<h3>તમારી ક્લિપ્સ તૈયાર છે</h3>'+d.clips.map((c,i)=>`<div class="clip"><b>Clip ${i+1}</b> · ${c.duration}s<br><a href="${API}${c.download_url}" target="_blank" rel="noopener">Download MP4</a></div>`).join('')}else if(d.status==='failed')throw new Error(d.message||'Processing failed')}
 }catch(e){$('status').textContent='ભૂલ: '+e.message}finally{$('go').disabled=false}
};
