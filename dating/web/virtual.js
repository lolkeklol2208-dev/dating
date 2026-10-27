import {api,post,telegram as tg} from './api.js';
import {icon} from './icons.js';

export function createVirtual(ui) {
 const {state,h,setPage,showModal,modalTop,toast,navigate,confirm}=ui;
 let thread=null,rows=[],peerRead=0,readThrough=0,sending=false,pending=null,inboxOffset=0,inboxCache='';
 const drafts=new Map();
 const isOperator=()=>state.route==='virtual-operator';
 const path=()=>`${isOperator()?'/api/admin/virtual':'/api/virtual'}/threads/${thread}`;
 const clock=raw=>new Date(raw.replace(' ','T')+'Z').toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'});
 function portrait(p,cls='') {
  return `<span class="virtual-portrait ${h(cls)}" role="img" aria-label="Сгенерированный портрет: ${h(p.name)}"><span style="background-image:url('${h(p.photo.url)}');background-position:${p.photo.column*25}% ${p.photo.row*100}%"></span></span>`;
 }
 function entry() {
  if(state.virtual?.enabled)return `<section class="virtual-banner active">${icon('info')}<div><strong>Тестовые знакомства включены</strong><p>Виртуальные анкеты отмечены в ленте. В диалогах с ними отвечает администратор.</p></div><button class="text-button" data-action="virtual-disable">Выключить и удалить</button></section>`;
  return `<section class="virtual-banner"><div><strong>Попробовать тестовые знакомства</strong><p>100 вымышленных персонажей в основной ленте. На сообщения отвечает администратор.</p></div><button class="secondary" data-action="virtual-enable">Включить тестовые знакомства</button></section>`;
 }
 async function enable() {
  const session=await api('/api/virtual/session');
  showModal(modalTop('Тестовые знакомства')+`<p class="modal-description">${h(session.notice)}</p><form id="virtual-consent"><label class="check-label"><input type="checkbox" required aria-label="Понимаю, что персонажи вымышлены, а переписку читает администратор"><span>Понимаю, что персонажи вымышлены, а переписку читает и ведёт администратор. Согласен(на) участвовать.</span></label><p class="form-error" role="alert"></p><button class="primary full" type="submit">Подтвердить и включить</button></form>`);
  const form=document.querySelector('#virtual-consent');
  form.onsubmit=async e=>{e.preventDefault();const button=form.querySelector('button');button.disabled=true;try{state.virtual=await post('/api/virtual/session',{enabled:true,accepted:true,version:session.version});document.querySelector('#modal').close();await navigate('discover');toast('Тестовые персонажи появились в ленте');}catch(error){form.querySelector('.form-error').textContent=error.message;button.disabled=false;}};
 }
 async function disable() {
  if(!await confirm('Выключить тестовые знакомства?','Все ваши тестовые мэтчи и сообщения удалятся из рабочей базы у вас и администратора. Реальные знакомства сохранятся.','Выключить и удалить',true))return;
  state.virtual=await post('/api/virtual/session',{enabled:false});
  state.unread=Math.max(0,(state.unread||0)-state.matches.filter(p=>p.is_virtual).reduce((n,p)=>n+(p.unread||0),0));state.matches=state.matches.filter(p=>!p.is_virtual);
  await navigate('discover');toast('Тестовый режим выключен, диалоги удалены');
 }
 function celebrate(p,id) {
  showModal(modalTop('Тестовый мэтч создан')+`<div class="virtual-match">${portrait(p)}<h3>${h(p.name)}, ${p.age}</h3><p>Это вымышленный персонаж. Вы можете проверить переписку: сообщения прочитает администратор и ответит от имени ${h(p.name)}.</p><button class="primary full" id="virtual-start">Начать тестовый диалог</button></div>`);
  document.querySelector('#virtual-start').onclick=()=>{document.querySelector('#modal').close();open(id);};
 }
 async function open(id,operator=false) {
  if(operator&&!state.user?.is_admin){toast('Нет доступа');return;}
  const version=++state.version;state.route=operator?'virtual-operator':'virtual-chat';state.chat=null;thread=id;readThrough=0;rows=[];
  try {
   const data=await api(path()+'/messages');if(version!==state.version)return;
   rows=data.messages;peerRead=data.summary.peer_read;
   const p=data.profile,key=(operator?'o:':'p:')+id;
   setPage(`<main class="thread virtual-thread"><header class="thread-head"><button class="icon-button" data-action="${operator?'virtual-inbox':'chats'}" aria-label="Назад">${icon('back')}</button>${portrait(p,'avatar')}<div><h2>${operator?h(data.participant_name)+' ↔ ':''}${h(p.name)}</h2><p>${operator?'Вы отвечаете от имени персонажа':'Вымышленный персонаж · отвечает администратор'}</p></div><span class="spacer"></span>${!operator?'<button class="icon-button" data-action="virtual-close" aria-label="Завершить тестовый диалог">'+icon('x')+'</button>':''}</header><div class="virtual-disclosure">${icon('info')}<span>${operator?'Участник согласился на тестовую переписку с администратором.':'Это тестовый диалог. Все сообщения здесь доступны администратору, который отвечает от имени персонажа.'}</span></div><div class="thread-body" id="virtual-messages" aria-label="Тестовая переписка"></div><form class="composer" id="virtual-composer"><textarea rows="1" maxlength="2000" aria-label="Сообщение" placeholder="${operator?'Ответ от имени персонажа…':'Сообщение персонажу…'}">${h(drafts.get(key)||'')}</textarea><button class="send" type="submit" aria-label="Отправить сообщение">${icon('send')}</button></form></main>`,true);
   render(true);
   const form=document.querySelector('#virtual-composer'),input=form.querySelector('textarea'),button=form.querySelector('button');button.disabled=!input.value.trim();
   input.oninput=()=>{drafts.set(key,input.value);button.disabled=!input.value.trim();input.style.height='auto';input.style.height=Math.min(120,input.scrollHeight)+'px';};
   form.onsubmit=e=>{e.preventDefault();send();};input.onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();send();}};
   document.querySelector('#virtual-messages').onscroll=()=>read().catch(()=>{});
   try{tg?.BackButton?.show();}catch{}await read();
  } catch(error){toast(error.message);if(operator)await inbox();else await navigate('chats');}
 }
 function render(bottom=false) {
  const el=document.querySelector('#virtual-messages');if(!el)return;
  const scroll=el.scrollTop,near=el.scrollHeight-scroll-el.clientHeight<100,mine=isOperator()?'operator':'participant';
  el.innerHTML=`<p class="thread-note">${icon('shield')}Персонаж вымышленный. Это общение с администратором.</p>${rows.length>=40?'<button class="text-button" data-action="virtual-older">Загрузить предыдущие</button>':''}${rows.map(m=>`<article class="bubble ${m.role===mine?'mine':''}"><small class="virtual-message-role">${m.role==='operator'?'Администратор · от имени персонажа':isOperator()?'Участник':'Вы'}</small><p>${h(m.body)}</p><div class="bubble-meta">${clock(m.created)}${m.role===mine?icon(m.id<=peerRead?'checks':'check'):''}</div></article>`).join('')}`;
  el.scrollTop=bottom||near?el.scrollHeight:scroll;
 }
 async function send() {
  const form=document.querySelector('#virtual-composer');if(!form||sending)return;
  const input=form.querySelector('textarea'),button=form.querySelector('button'),body=input.value.trim();if(!body)return;
  const version=state.version,target=path(),key=(isOperator()?'o:':'p:')+thread;
  const nonce=pending?.body===body&&pending?.target===target?pending.nonce:crypto.randomUUID();pending={body,target,nonce};sending=true;button.disabled=true;
  try{const data=await post(target+'/messages',{body,nonce});pending=null;drafts.delete(key);if(version===state.version){if(!rows.some(m=>m.id===data.message.id))rows.push(data.message);input.value='';input.style.height='auto';render(true);}}
  catch(error){toast(error.message+' Текст сохранён для повторной отправки.');}
  finally{sending=false;if(button.isConnected)button.disabled=!input.value.trim();}
 }
 async function read() {
  const el=document.querySelector('#virtual-messages');if(document.hidden||!el||!rows.length||el.scrollHeight-el.scrollTop-el.clientHeight>90)return;
  const last=rows.at(-1).id;if(last<=readThrough)return;const prior=readThrough;readThrough=last;
  try{await post(path()+'/read',{last_id:last});}catch(error){readThrough=prior;throw error;}
 }
 async function inbox() {
  if(!state.user?.is_admin){toast('Нет доступа');return;}
  state.version++;state.route='virtual-inbox';state.chat=null;inboxCache='';await refreshInbox();
 }
 async function refreshInbox() {
  const version=state.version,data=await api('/api/admin/virtual/threads?offset='+inboxOffset);
  if(version!==state.version||state.route!=='virtual-inbox')return;
  const serialized=JSON.stringify(data);if(serialized===inboxCache)return;inboxCache=serialized;
  setPage(`<main class="page"><div class="page-heading"><div><p class="eyebrow">Мэтч · Администратор</p><h1>Тестовые <em>диалоги.</em></h1><p class="subtitle">Вы отвечаете от имени вымышленных персонажей.</p></div><button class="icon-button" data-action="admin" aria-label="Вернуться в админ-панель">${icon('back')}</button></div><div class="testing-notice">${icon('info')}<p>Здесь только участники, которые явно включили тестовые знакомства и согласились на переписку с администратором. Реальные личные диалоги здесь не отображаются.</p></div><div class="chat-list">${data.threads.map(p=>`<button class="chat-row" data-action="virtual-operator" data-thread-id="${p.thread_id}">${portrait(p,'avatar')}<span class="chat-copy"><h3>${h(p.participant_name)} ↔ ${h(p.name)}</h3><p>${p.last?h(p.last.body):'Тестовый мэтч создан. Сообщений пока нет.'}</p><small>Участник ${p.participant_id} · Виртуальная анкета</small></span><span class="chat-meta">${p.unread?`<b class="unread">${p.unread}</b>`:icon('chevron')}</span></button>`).join('')||'<div class="admin-empty"><p>Тестовых диалогов пока нет. Участнику нужно включить тестовые знакомства и поставить лайк персонажу.</p></div>'}</div><div class="admin-pagination"><button class="secondary" data-action="virtual-prev" ${inboxOffset?'':'disabled'}>Назад</button><button class="secondary" data-action="virtual-next" ${data.more?'':'disabled'}>Далее</button></div></main>`);
 }
 async function refresh() {
  if(state.route==='virtual-inbox'){await refreshInbox();return;}
  if(!['virtual-chat','virtual-operator'].includes(state.route))return;
  const version=state.version;
  try{
   const data=await api(path()+'/messages?after='+(rows.at(-1)?.id||0));if(version!==state.version)return;
   const fresh=data.messages.filter(m=>!rows.some(r=>r.id===m.id)),changed=peerRead!==data.summary.peer_read;rows.push(...fresh);peerRead=data.summary.peer_read;
   if(fresh.length||changed)render();await read();
  }catch(error){if(version!==state.version)return;toast(error.message);if(isOperator())await inbox();else await navigate('chats');}
 }
 async function handle(button) {
  const action=button.dataset.action.slice(8);
  if(action==='enable')await enable();
  else if(action==='disable')await disable();
  else if(action==='inbox')await inbox();
  else if(action==='operator')await open(Number(button.dataset.threadId),true);
  else if(action==='next'){inboxOffset+=20;await inbox();}
  else if(action==='prev'){inboxOffset=Math.max(0,inboxOffset-20);await inbox();}
  else if(action==='card'){const p=state.candidate;if(p?.is_virtual)showModal(modalTop(p.name)+`<div class="virtual-match">${portrait(p)}<p>${h(p.bio)}</p><p>Персонаж вымышленный. Если поставить лайк, создастся тестовый мэтч; в диалоге ответит администратор.</p></div>`);}
  else if(action==='close'&&await confirm('Завершить тестовый диалог?','Мэтч и тестовая переписка удалятся из рабочей базы у вас и администратора.','Завершить',true)){await api('/api/virtual/threads/'+thread,{method:'DELETE'});await navigate('chats');}
  else if(action==='older'&&rows.length){const el=document.querySelector('#virtual-messages'),height=el.scrollHeight,version=state.version;const data=await api(path()+'/messages?before='+rows[0].id);if(version!==state.version)return;if(!data.messages.length){button.remove();toast('Это начало переписки');return;}rows=[...data.messages,...rows];render();el.scrollTop=el.scrollHeight-height;}
 }
 return {entry,portrait,celebrate,open,inbox,refresh,handle};
}
