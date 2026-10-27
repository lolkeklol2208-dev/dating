import {api,post} from './api.js';
import {icon} from './icons.js';

const statuses = [['new','Не проверена'],['reviewed','Проверена'],['needs_work','Доработать']];
export function createTesting(ui) {
 const {h} = ui;
 let query='',city='',low=20,high=30,status='all',offset=0,sequence=0;
 const portrait = p => `<div class="test-portrait" role="img" aria-label="Сгенерированный портрет: ${h(p.name)}" style="background-image:url('${h(p.photo.url)}');background-position:${p.photo.column*25}% ${p.photo.row*100}%"><span>Тестовая анкета</span></div>`;
 const pager = data => `<div class="admin-pagination"><button class="secondary" data-action="testing-prev" ${offset===0?'disabled':''}>Назад</button><span>${data.total?offset+1:0}–${Math.min(offset+20,data.total)} из ${data.total}</span><button class="secondary" data-action="testing-next" ${data.more?'':'disabled'}>Далее</button></div>`;
 async function open() {
  const current=++sequence;
  try {
   const params=new URLSearchParams({q:query,city,min_age:low,max_age:high,status,offset});
   const data=await api('/api/admin/test-profiles?'+params);
   if(current!==sequence||!ui.isActive())return;
   ui.render(`<main class="page testing-page"><div class="page-heading"><div><p class="eyebrow">Мэтч · Лаборатория</p><h1>Тестовые <em>анкеты.</em></h1><p class="subtitle">100 вымышленных персонажей · 20–30 лет.</p></div><button class="icon-button" data-action="admin" aria-label="Вернуться в админ-панель">${icon('back')}</button></div><div class="testing-notice">${icon('info')}<p>${h(data.notice)} Они не участвуют в реальных мэтчах и не отправляют сообщения.</p></div><div class="testing-stats"><span>Всего <b>${data.summary.total}</b></span><span>Проверено <b>${data.summary.reviewed}</b></span><span>Доработать <b>${data.summary.needs_work}</b></span></div><form id="testing-filters" class="testing-filters"><label class="field">Поиск<input name="q" maxlength="80" value="${h(query)}" placeholder="Имя, занятие или увлечение"></label><label class="field">Город<select name="city" aria-label="Город"><option value="">Все города</option>${data.cities.map(c=>`<option value="${h(c)}" ${city===c?'selected':''}>${h(c)}</option>`).join('')}</select></label><div class="form-grid"><label class="field">Возраст от<input type="number" name="min_age" min="20" max="30" value="${low}" required></label><label class="field">Возраст до<input type="number" name="max_age" min="20" max="30" value="${high}" required></label></div><label class="field">Проверка<select name="status" aria-label="Проверка"><option value="all">Все статусы</option>${statuses.map(([v,label])=>`<option value="${v}" ${status===v?'selected':''}>${label}</option>`).join('')}</select></label><button class="primary" type="submit">Применить</button><button class="secondary" type="button" data-action="testing-reset">Сбросить</button></form><div class="testing-toolbar"><p class="admin-total">Найдено: ${data.total}</p><button class="text-button" data-action="testing-export">${icon('arrow')} Скачать CSV · все 100</button></div><div class="testing-grid">${data.profiles.map(p=>`<article class="testing-card">${portrait(p)}<div class="testing-card-body"><h2>${h(p.name)}, ${p.age}</h2><p class="testing-city">${icon('pin')}${h(p.city)}</p><p class="testing-occupation">${h(p.occupation)}</p><p class="testing-bio">${h(p.bio)}</p><div class="tags">${p.tags.map(t=>`<span class="tag">${h(t)}</span>`).join('')}</div><div class="testing-rating"><span>${h(statuses.find(([v])=>v===p.review.status)?.[1]||'Не проверена')}</span><span>${p.review.rating?p.review.rating+'/5':'Без оценки'}</span></div><button class="secondary full" data-action="testing-detail" data-profile-id="${p.id}">Посмотреть и оценить</button></div></article>`).join('')}</div>${!data.total?'<div class="admin-empty"><p>Нет анкет с такими фильтрами. Попробуйте изменить поиск.</p></div>':''}${pager(data)}</main>`);
   const form=document.querySelector('#testing-filters');
   form.onsubmit=e=>{e.preventDefault();query=form.elements.q.value.trim();city=form.elements.city.value;low=Number(form.elements.min_age.value);high=Number(form.elements.max_age.value);status=form.elements.status.value;if(low>high){ui.toast('Возраст «от» должен быть меньше возраста «до»');return;}offset=0;open();};
  } catch(error) {if(current===sequence&&ui.isActive()){ui.render(`<main class="page"><h1>Не удалось загрузить каталог</h1><p class="subtitle">${h(error.message)}</p><button class="primary" data-action="testing-refresh">Повторить</button><button class="secondary" data-action="admin">Админ-панель</button></main>`);}}
 }
 async function detail(id) {
  const {profile:p}=await api('/api/admin/test-profiles/'+id);
  if(!ui.isActive())return;
  ui.showModal(ui.modalTop('Тестовая анкета')+`<div class="testing-detail">${portrait(p)}<h3>${h(p.name)}, ${p.age}</h3><p class="testing-city">${h(p.city)} · ${h(p.occupation)}</p><p class="testing-detail-bio">${h(p.bio)}</p><div class="tags">${p.tags.map(t=>`<span class="tag">${h(t)}</span>`).join('')}</div><p class="testing-disclaimer">Вымышленный персонаж и сгенерированное фото. Это не участница сервиса.</p><form id="testing-review"><div class="form-grid"><label class="field">Оценка<select name="rating" aria-label="Оценка"><option value="0">Без оценки</option>${[1,2,3,4,5].map(n=>`<option value="${n}" ${p.review.rating===n?'selected':''}>${n} из 5</option>`).join('')}</select></label><label class="field">Статус проверки<select name="status" aria-label="Статус проверки">${statuses.map(([v,label])=>`<option value="${v}" ${p.review.status===v?'selected':''}>${label}</option>`).join('')}</select></label></div><label class="field">Заметка<textarea name="notes" aria-label="Заметка" maxlength="2000" placeholder="Что проверить или изменить">${h(p.review.notes)}</textarea></label><p class="form-error" role="alert"></p><button class="primary full" type="submit">Сохранить оценку</button></form></div>`);
  const form=document.querySelector('#testing-review');
  form.onsubmit=async e=>{e.preventDefault();const button=form.querySelector('button');button.disabled=true;try{await post('/api/admin/test-profiles/'+id,{rating:Number(form.elements.rating.value),status:form.elements.status.value,notes:form.elements.notes.value,revision:p.review.revision});document.querySelector('#modal').close();ui.toast('Оценка и заметка сохранены');await open();}catch(error){form.querySelector('.form-error').textContent=error.message;button.disabled=false;}};
 }
 async function exportCsv(button) {
  button.disabled=true;
  try {
   const data=await api('/api/admin/test-profiles/export');
   const cell = value => {let s=String(value??'');if(/^[\s]*[=+\-@]/.test(s)||/^[\t\r\n]/.test(s))s="'"+s;return '"'+s.replaceAll('"','""')+'"';};
   const rows=[['ID','Тестовая анкета','Имя','Возраст','Город','Занятие','Описание','Интересы','Статус проверки','Оценка','Заметка','Изменено UTC']];
   for(const p of data.profiles)rows.push([p.id,'Да',p.name,p.age,p.city,p.occupation,p.bio,p.tags.join(', '),p.review.status,p.review.rating,p.review.notes,p.review.updated]);
   const csv='\ufeff'+rows.map(row=>row.map(cell).join(';')).join('\r\n');
   const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));
   const link=document.createElement('a');link.href=url;link.download='metch-test-profiles.csv';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);
   ui.toast('Отчёт подготовлен для скачивания');
  } finally {button.disabled=false;}
 }
 async function handle(button) {
  const action=button.dataset.action.slice(8);
  if(action==='detail')await detail(button.dataset.profileId);
  else if(action==='export')await exportCsv(button);
  else if(action==='next'){offset+=20;await open();}
  else if(action==='prev'){offset=Math.max(0,offset-20);await open();}
  else if(action==='reset'){query='';city='';low=20;high=30;status='all';offset=0;await open();}
  else if(action==='refresh')await open();
 }
 return {open,handle};
}
