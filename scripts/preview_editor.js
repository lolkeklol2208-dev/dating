// This module is bundled only into the standalone offline preview.
const designStorageKey='metch-preview-design-v1';
const colorFields=[['bg','Фон приложения','--bg'],['surface','Карточки и окна','--surface'],['accent','Фиолетовый акцент','--accent'],['text','Основной текст','--text']];
let design={version:1,activeTheme:theme,dark:{},light:{},radius:26,reducedMotion:false};
function validDesign(value){
 if(!value||value.version!==1)throw Error('Неизвестный формат. Нужен файл metch-design.json.');
 const result={version:1,activeTheme:['dark','light'].includes(value.activeTheme)?value.activeTheme:'dark',dark:{},light:{},radius:26,reducedMotion:!!value.reducedMotion};
 for(const mode of ['dark','light'])for(const [key] of colorFields){const color=value[mode]?.[key];if(color!==undefined){if(typeof color!=='string'||!/^#[0-9a-f]{6}$/i.test(color))throw Error('В файле указан некорректный цвет');result[mode][key]=color;}}
 if(value.radius!==undefined){if(!Number.isFinite(value.radius)||value.radius<16||value.radius>36)throw Error('Скругление должно быть от 16 до 36');result.radius=value.radius;}
 return result;
}
try{const saved=localStorage.getItem(designStorageKey);if(saved)design=validDesign(JSON.parse(saved));}catch{}
const designer=document.createElement('dialog');designer.id='design-editor';designer.setAttribute('aria-label','Редактор дизайна');document.body.append(designer);
const launcher=document.createElement('button');launcher.className='preview-toggle';launcher.setAttribute('aria-label','Открыть редактор дизайна');launcher.innerHTML=icon('edit')+'Дизайн';document.body.append(launcher);
function luminance(hex){const channels=hex.slice(1).match(/../g).map(n=>parseInt(n,16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);return channels[0]*.2126+channels[1]*.7152+channels[2]*.0722;}
function contrast(a,b){const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);}
function saveDesign(){design.activeTheme=theme;try{localStorage.setItem(designStorageKey,JSON.stringify(design));}catch{}}
function applyDesign(){
 const style=document.documentElement.style;
 for(const [key,_,variable] of colorFields){style.removeProperty(variable);if(design[theme][key])style.setProperty(variable,design[theme][key]);}
 for(const variable of ['--primary','--primary-text','--soft'])style.removeProperty(variable);
 if(design[theme].accent){const accent=design[theme].accent;style.setProperty('--primary',accent);style.setProperty('--primary-text',contrast('#ffffff',accent)>=4.5?'#ffffff':'#190c34');style.setProperty('--soft',accent+'18');}
 style.setProperty('--radius',design.radius+'px');window.__metchPreviewReducedMotion=design.reducedMotion;
 document.documentElement.classList.toggle('preview-reduce-motion',design.reducedMotion);saveDesign();
}
function currentColor(key,variable){return design[theme][key]||getComputedStyle(document.documentElement).getPropertyValue(variable).trim();}
function updateContrast(){const box=designer.querySelector('#design-contrast');if(!box)return;const ratio=contrast(currentColor('bg','--bg'),currentColor('text','--text'));box.textContent=`Контраст текста и фона: ${ratio.toFixed(1)}:1. ${ratio>=4.5?'Текст хорошо читается.':'Лучше увеличить разницу между цветом текста и фона.'}`;box.className='design-contrast'+(ratio<4.5?' warn':'');}
function renderDesigner(){designer.innerHTML=`<div class="modal-heading"><h2>Сделайте по-своему</h2><button class="icon-button" id="design-close" aria-label="Закрыть редактор">${icon('x')}</button></div><p class="design-help">Настраивайте цвета и смотрите результат. Это только ваше превью — рабочий бот не меняется.</p><div class="design-tabs"><button data-design-theme="dark" class="${theme==='dark'?'active':''}">Тёмная слива</button><button data-design-theme="light" class="${theme==='light'?'active':''}">Светлая лаванда</button></div>${colorFields.map(([key,label,variable])=>`<label class="design-field"><span>${label}</span><span class="design-label-code" data-color-code="${key}">${h(currentColor(key,variable))}</span><input type="color" data-color="${key}" aria-label="${label}" value="${h(currentColor(key,variable))}"></label>`).join('')}<label class="design-field"><span>Скругление карточек</span><output id="radius-value">${design.radius}</output><input id="design-radius" type="range" min="16" max="36" step="1" value="${design.radius}" aria-label="Скругление карточек"></label><label class="design-field"><span>Уменьшить анимации</span><input type="checkbox" id="design-motion" ${design.reducedMotion?'checked':''}></label><p id="design-contrast" class="design-contrast"></p><div class="design-actions"><button class="primary" id="design-export">${icon('check')}Сохранить дизайн в файл</button><label class="secondary design-import">Импортировать настройки<input id="design-import" type="file" accept="application/json,.json"></label><button class="secondary" id="design-reset">Вернуть исходные цвета этой темы</button><button class="text-button" id="design-inspect">Посмотреть приложение</button></div><p class="design-caption">Настройки сохраняются в этом браузере. Кнопка «Сохранить» скачает metch-design.json: пришлите его в чат, и я перенесу правки в приложение. Тексты и фото анкеты можно менять в разделе «Профиль».</p><p class="design-error" id="design-error" role="alert"></p>`;
 designer.querySelector('#design-close').onclick=()=>designer.close();designer.querySelector('#design-inspect').onclick=()=>designer.close();
 designer.querySelectorAll('[data-design-theme]').forEach(b=>b.onclick=()=>{applyTheme(b.dataset.designTheme);applyDesign();renderDesigner();});
 designer.querySelectorAll('[data-color]').forEach(input=>input.oninput=()=>{design[theme][input.dataset.color]=input.value;applyDesign();designer.querySelector(`[data-color-code="${input.dataset.color}"]`).textContent=input.value;updateContrast();});
 designer.querySelector('#design-radius').oninput=e=>{design.radius=Number(e.target.value);designer.querySelector('#radius-value').textContent=design.radius;applyDesign();};
 designer.querySelector('#design-motion').onchange=e=>{design.reducedMotion=e.target.checked;applyDesign();};
 designer.querySelector('#design-reset').onclick=()=>{design[theme]={};applyDesign();renderDesigner();};
 designer.querySelector('#design-export').onclick=()=>{saveDesign();const blob=new Blob([JSON.stringify(design,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='metch-design.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
 designer.querySelector('#design-import').onchange=async e=>{try{const file=e.target.files[0];if(!file)return;if(file.size>20000)throw Error('Файл слишком большой');design=validDesign(JSON.parse(await file.text()));applyTheme(design.activeTheme);applyDesign();renderDesigner();}catch(error){designer.querySelector('#design-error').textContent=error.message;}};
 updateContrast();}
launcher.onclick=()=>{renderDesigner();designer.showModal();};
designer.addEventListener('click',e=>{if(e.target===designer){const b=designer.getBoundingClientRect();if(e.clientX<b.left||e.clientX>b.right||e.clientY<b.top||e.clientY>b.bottom)designer.close();}});
new MutationObserver(()=>{applyDesign();if(designer.open)renderDesigner();}).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
applyTheme(design.activeTheme);applyDesign();
