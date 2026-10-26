import {api,post} from './api.js';
import {icon} from './icons.js';

const reasons = {spam:'Спам или мошенничество',content:'Неприемлемый контент',underage:'Возраст меньше 18 лет'};
const decisions = {ban:'Блокировка',unban:'Разблокировка',dismiss:'Жалоба отклонена'};
const reportDecisions = {banned:'Пользователь заблокирован',dismissed:'Жалоба отклонена'};
const date = raw => raw ? new Date(raw.replace(' ','T')+'Z').toLocaleString('ru-RU',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}) : '';

export function createAdmin(ui) {
 const {h} = ui;
 let view='overview',query='',filter='all',reportStatus='open',offset=0,sequence=0,stats={};
 const tabs = [['overview','Обзор'],['reports','Жалобы'],['users','Люди'],['audit','Журнал']];
 const cards = [['profiles','Всего анкет'],['visible','В поиске'],['matches','Мэтчи'],['messages','Сообщения'],['reports_open','Новые жалобы'],['bans','Блокировки']];
 const status = user => user.ban_reason != null ? 'Заблокирован' : user.active ? 'В поиске' : 'На паузе';
 const pager = data => data.total > 20 ? `<div class="admin-pagination"><button class="secondary" data-action="admin-prev" ${offset===0?'disabled':''}>Назад</button><span>${offset+1}–${Math.min(offset+20,data.total)} из ${data.total}</span><button class="secondary" data-action="admin-next" ${data.more?'':'disabled'}>Далее</button></div>` : '';
 const noRows = text => `<div class="admin-empty">${icon('shield')}<p>${text}</p></div>`;

 function overview() {
  return `<div class="admin-stats">${cards.map(([key,label])=>`<article class="admin-stat"><span>${label}</span><strong>${stats[key]??0}</strong></article>`).join('')}</div><section class="admin-note"><div class="note-icon">${icon('shield')}</div><h2>Спокойное пространство начинается с заботы</h2><p>Проверяйте жалобы по одной. Любое решение сохраняется в журнале. Личная блокировка заявителя останется и после отклонения жалобы.</p><button class="primary" data-action="admin-reports">Разобрать жалобы ${icon('arrow')}</button></section>`;
 }
 function users(data) {
  return `<form id="admin-search" class="admin-search"><label class="field">Поиск пользователей<input name="q" maxlength="80" placeholder="Имя, @username, город или Telegram ID" value="${h(query)}"></label><label class="field">Статус<select name="status">${[['all','Все'],['visible','В поиске'],['hidden','На паузе'],['banned','Заблокированные']].map(([v,label])=>`<option value="${v}" ${filter===v?'selected':''}>${label}</option>`).join('')}</select></label><button class="primary" type="submit">Найти</button></form><p class="admin-total">Найдено: ${data.total}</p><div class="admin-list">${data.users.map(user=>`<button class="admin-user" data-action="admin-user" data-id="${user.id}"><span class="admin-initial">${h((user.name||'?').slice(0,1))}</span><span class="grow"><strong>${h(user.name||'Анкета удалена')}${user.age?', '+user.age:''}</strong><small>${h(user.city||'Нет анкеты')} · ID ${user.id}</small></span><span class="admin-status ${user.ban_reason!=null?'is-banned':''}">${status(user)}</span>${icon('chevron')}</button>`).join('')||noRows('Пользователи не найдены')}</div>${pager(data)}`;
 }
 function reports(data) {
  return `<div class="admin-filters">${[['open','Ожидают решения'],['reviewed','Обработанные']].map(([v,label])=>`<button class="secondary ${reportStatus===v?'selected':''}" data-action="admin-report-filter" data-status="${v}" aria-pressed="${reportStatus===v}">${label}</button>`).join('')}<span class="admin-total">${data.total}</span></div><div class="admin-reports">${data.reports.map(r=>`<article class="admin-report"><div class="admin-report-top"><span class="admin-status ${r.reason==='underage'?'is-banned':''}">${h(reasons[r.reason]||r.reason)}</span><time>${h(date(r.created))}</time></div><h2>${h(r.target_name)}</h2><p>Жалоба от ${h(r.actor_name)} · ID ${r.actor}<br>На пользователя · ID ${r.target}</p>${r.action?`<p class="admin-decision">${h(reportDecisions[r.action]||r.action)}</p>`:''}<div class="admin-report-actions"><button class="secondary" data-action="admin-user" data-id="${r.target}">Посмотреть анкету</button>${!r.action?`<button class="danger" data-action="admin-ban" data-id="${r.target}" data-actor="${r.actor}" data-reason="${h(reasons[r.reason]||r.reason)}">${r.banned?'Подтвердить блокировку':'Заблокировать'}</button><button class="text-button" data-action="admin-dismiss" data-id="${r.target}" data-actor="${r.actor}">Отклонить</button>`:''}</div></article>`).join('')||noRows(reportStatus==='open'?'Новых жалоб нет. Здесь спокойно 💜':'Обработанных жалоб пока нет')}</div>${pager(data)}`;
 }
 function audit(data) {
  return `<p class="subtitle admin-description">Кто принял решение, когда и по какой причине. История переписки здесь не отображается.</p><div class="admin-list">${data.entries.map(row=>`<article class="admin-audit"><div><span class="admin-status">${decisions[row.action]||h(row.action)}</span><time>${h(date(row.created))}</time></div><p>${h(row.reason)}</p><small>Пользователь ${row.target} · Администратор ${row.moderator}${row.report_actor?' · Жалоба от '+row.report_actor:''}</small></article>`).join('')||noRows('Решения появятся здесь после первой проверки')}</div>${pager(data)}`;
 }
 async function open() {
  const current=++sequence;
  try {
   const params=new URLSearchParams({offset});
   if(view==='users'){params.set('q',query);params.set('status',filter);}
   if(view==='reports')params.set('status',reportStatus);
   const [summary,data]=await Promise.all([api('/api/admin/overview'),view==='overview'?Promise.resolve(null):api('/api/admin/'+view+'?'+params)]);
   if(current!==sequence||!ui.isActive())return;
   stats=summary;
   ui.render(`<main class="page admin-page"><div class="page-heading"><div><p class="eyebrow">Мэтч · Администратор</p><h1>Всё <em>под контролем.</em></h1><p class="subtitle">Люди, безопасность и ваше пространство.</p></div><button class="icon-button" data-action="admin-refresh" aria-label="Обновить админ-панель">${icon('refresh')}</button></div><nav class="admin-tabs" aria-label="Разделы администрирования">${tabs.map(([v,label])=>`<button class="${view===v?'active':''}" data-action="admin-${v}" ${view===v?'aria-current="page"':''}>${label}${v==='reports'&&stats.reports_open?`<b>${stats.reports_open}</b>`:''}</button>`).join('')}</nav>${view==='overview'?overview():view==='users'?users(data):view==='reports'?reports(data):audit(data)}</main>`);
   const form=document.querySelector('#admin-search');
   if(form)form.onsubmit=e=>{e.preventDefault();query=form.elements.q.value.trim();filter=form.elements.status.value;offset=0;open();};
  } catch(error) {if(current===sequence&&ui.isActive()){ui.render(`<main class="page admin-page"><h1>Не удалось загрузить</h1><p class="subtitle">${h(error.message)}</p><button class="primary" data-action="admin-refresh">Повторить</button></main>`);}}
 }
 async function detail(id) {
  const data=await api('/api/admin/users/'+id);
  if(!ui.isActive())return;
  const p=data.profile;
  ui.showModal(ui.modalTop('Карточка пользователя')+`<div class="admin-profile">${p?ui.photo(p):''}<h3>${h(p?.name||'Анкета удалена')}${p?', '+p.age:''}</h3><p>${h(p?.city||'')} ${p?.username?'· @'+h(p.username):''}</p><small>Telegram ID: ${data.id}</small>${p?`<p class="admin-bio">${h(p.bio)}</p>`:''}<div class="admin-detail-counts"><span>Мэтчей: ${data.matches}</span><span>Жалоб: ${data.reports_received}</span></div>${data.ban?`<div class="admin-ban-note"><b>Аккаунт заблокирован</b><p>${h(data.ban.reason)}</p><small>${h(date(data.ban.created))}</small></div>`:`<p>${p?.active?'Анкета в поиске':'Анкета на паузе'}</p>`}<div class="modal-actions">${id===ui.ownId()?'<p class="subtitle">Это ваш аккаунт администратора.</p>':data.ban?'<button class="secondary" id="admin-unban">Снять блокировку</button>':'<button class="danger" id="admin-user-ban">Заблокировать аккаунт</button>'}</div></div>`);
  document.querySelector('#admin-unban')?.addEventListener('click',()=>decision('unban',id));
  document.querySelector('#admin-user-ban')?.addEventListener('click',()=>decision('ban',id));
 }
 function decision(action,id,actor,reason='') {
  const label=action==='ban'?'Заблокировать':action==='unban'?'Снять блокировку':'Отклонить жалобу';
  const description=action==='ban'?'Человек потеряет доступ к знакомствам и диалогам. Анкета и данные не удаляются.':action==='unban'?'Доступ к сервису восстановится. Личные блокировки участников сохранятся.':'Жалоба будет закрыта. Личная блокировка заявителя сохранится.';
  ui.showModal(ui.modalTop(label+'?')+`<p class="modal-description">${description}<br>Пользователь: ${id}</p><form id="admin-decision"><label class="field">Причина решения<textarea aria-label="Причина решения" name="reason" minlength="3" maxlength="300" required placeholder="Кратко объясните решение">${h(reason)}</textarea><small>Причина сохранится в журнале администратора.</small></label><p class="form-error" role="alert"></p><div class="modal-actions"><button class="${action==='ban'?'danger':'primary'}" type="submit">${label}</button><button class="secondary" type="button" data-close>Отмена</button></div></form>`);
  const form=document.querySelector('#admin-decision');
  form.onsubmit=async e=>{
   e.preventDefault();const button=form.querySelector('button[type=submit]');button.disabled=true;
   try {
    const body={action,target:id,reason:form.elements.reason.value.trim()};
    if(actor)body.report_actor=actor;
    await post('/api/admin/moderate',body);document.querySelector('#modal').close();
    ui.toast('Решение сохранено');await open();
   } catch(error) {form.querySelector('.form-error').textContent=error.message;button.disabled=false;}
  };
 }
 async function handle(button) {
  const action=button.dataset.action.slice(6),id=Number(button.dataset.id),actor=Number(button.dataset.actor)||undefined;
  if(tabs.some(([v])=>v===action)){view=action;offset=0;await open();}
  else if(action==='user')await detail(id);
  else if(['ban','unban','dismiss'].includes(action))decision(action,id,actor,button.dataset.reason||'');
  else if(action==='report-filter'){reportStatus=button.dataset.status;offset=0;await open();}
  else if(action==='next'){offset+=20;await open();}
  else if(action==='prev'){offset=Math.max(0,offset-20);await open();}
  else if(action==='refresh')await open();
 }
 return {open,handle};
}
