export const telegram = window.Telegram?.WebApp;
// Telegram supplies the same signed payload in the launch hash. The server
// still verifies its HMAC; this is only a transport fallback when the SDK fails.
const launchParams = new URLSearchParams(location.hash.slice(1));
const initData = telegram?.initData || launchParams.get('tgWebAppData') || '';
export const demo = !initData;
const photos = [
 '/assets/images/anya.png',
 '/assets/images/mark.png',
 '/assets/images/sonya.png',
 '/assets/images/artem.png'
];
const people = [
 {id:101,name:'Аня',age:23,city:'Москва',bio:'Собираю красивые моменты, винил и поводы выбраться из дома. Пойдём за кофе, а там — как почувствуем ✨',tags:['Кофе и разговоры','Арт-пространства','Спонтанность'],photo_url:photos[0]},
 {id:102,name:'Марк',age:25,city:'Москва',bio:'Снимаю на плёнку, ищу новые места и слушаю один трек по кругу. Буду рад компании на длинную прогулку.',tags:['Фотография','Музыка','Прогулки'],photo_url:photos[1]},
 {id:103,name:'Соня',age:24,city:'Москва',bio:'Кино по четвергам, матча по утрам. Хочется встретить человека, с которым легко быть собой.',tags:['Кино','Матча','Путешествия'],photo_url:photos[2]},
 {id:104,name:'Артём',age:27,city:'Москва',bio:'Архитектор, немного музыкант. Верю, что хороший разговор лучше любого плана на вечер.',tags:['Архитектура','Гитара'],photo_url:photos[3]}
];
let own = {id:1,name:'Ваш профиль',age:24,city:'Москва',bio:'Это демонстрационная анкета. В Telegram здесь будет ваша история.',gender:'f',seeking:'any',active:1,min_age:18,max_age:35,photo_url:photos[2]};
let queue=[people[0],people[3]],matched=[people[1],people[2]],seq=3;
const transcripts=new Map([[102,[{id:1,sender:102,body:'Привет! Как насчёт прогулки без маршрута? ✨',created:'2026-10-25 12:30:00',status:'sent'}]],[103,[{id:2,sender:103,body:'Кажется, у нас совпали не только лайки 💜',created:'2026-10-25 12:35:00',status:'sent'}]]]);
const seen=new Map(),nonces=new Map();
function summaries(p){const rows=transcripts.get(p.id)||[];return {...p,last:rows.at(-1)||null,unread:rows.filter(m=>m.sender!==1&&m.id>(seen.get(p.id)||0)).length,peer_read:0};}
async function demoRequest(path,{method='GET',body}={}){
 const url=new URL(path,location.origin), route=url.pathname;
 let data=body instanceof FormData ? JSON.parse(body.get('profile')) : typeof body==='string'?JSON.parse(body):body||{};
 if(route==='/api/me') {if(method==='DELETE'){own=null;matched=[];queue=[];transcripts.clear();} return {user:{id:1,first_name:'Привет'},profile:own};}
 if(route==='/api/profile'){own={...own,...data,id:1,active:own?.active??1,min_age:own?.min_age??18,max_age:own?.max_age??35};const file=body instanceof FormData?body.get('photo'):null;if(file?.size)own.photo_url=URL.createObjectURL(file);return {profile:own};}
 if(route==='/api/candidate')return {profile:own?.active?queue[0]||null:null,active:!!own?.active};
 if(route==='/api/reactions'){const p=queue.find(p=>p.id===data.target);queue=queue.filter(p=>p.id!==data.target);const match=data.kind==='like'&&!!p;if(match&&!matched.some(m=>m.id===p.id))matched.unshift(p);return {match};}
 if(route==='/api/matches'){const offset=Number(url.searchParams.get('offset')||0);return {matches:matched.slice(offset,offset+5).map(summaries),more:matched.length>offset+5};}
 if(route.startsWith('/api/profiles/'))return {profile:people.find(p=>p.id===Number(route.split('/').at(-1)))};
 if(route==='/api/settings'){own={...own,...data};return {ok:true};}
 if(route.startsWith('/api/actions/')){const action=route.split('/').at(-1);if(action==='reset')queue=people.filter(p=>!matched.some(m=>m.id===p.id));else{queue=queue.filter(p=>p.id!==data.target);matched=matched.filter(p=>p.id!==data.target);transcripts.delete(data.target);}return {ok:true};}
 if(route.startsWith('/api/chats/')){
  const target=Number(route.split('/')[3]);let rows=transcripts.get(target)||[];
  if(route.endsWith('/read')){seen.set(target,data.last_id);return {ok:true};}
  if(method==='POST'){if(nonces.has(data.nonce))return {message:nonces.get(data.nonce)};const message={id:seq++,sender:1,body:data.body,created:new Date().toISOString(),status:'sent'};rows.push(message);transcripts.set(target,rows);nonces.set(data.nonce,message);return {message};}
  const after=Number(url.searchParams.get('after')||0),before=Number(url.searchParams.get('before')||Number.MAX_SAFE_INTEGER);
  return {messages:rows.filter(m=>m.id>after&&m.id<before),summary:summaries(people.find(p=>p.id===target))};
 }
 throw new Error('Действие недоступно в деморежиме');
}
export async function api(path, options={}){
 if(demo)return demoRequest(path,options);
 const headers={'X-Telegram-Init-Data':initData,...options.headers};
 if(options.body&&!(options.body instanceof FormData))headers['Content-Type']='application/json';
 const controller=new AbortController(), timeout=setTimeout(()=>controller.abort(),30000);
 try{
  const response=await fetch(path,{...options,headers,signal:controller.signal,credentials:'same-origin'});
  if(options.blob){if(!response.ok)throw new Error('Фото недоступно');return response.blob();}
  const data=await response.json();if(!response.ok)throw new Error(data.error||'Не удалось выполнить запрос');return data;
 }catch(error){if(error.name==='AbortError')throw new Error('Сервер долго отвечает. Проверьте соединение и попробуйте ещё раз.');throw error;}finally{clearTimeout(timeout);}
}
export const post=(path,data)=>api(path,{method:'POST',body:JSON.stringify(data)});
const photoCache=new Map();
export async function imageSource(p){
 if(!p?.photo_url)return '';
 if(!p.photo_url.startsWith('/api/'))return p.photo_url;
 const key=p.photo_url;
 if(!photoCache.has(key)){
  if(photoCache.size>=20){const old=photoCache.keys().next().value;photoCache.get(old).then(URL.revokeObjectURL).catch(()=>{});photoCache.delete(old);}
  photoCache.set(key,api(p.photo_url,{blob:true}).then(blob=>URL.createObjectURL(blob)).catch(error=>{photoCache.delete(key);throw error;}));
 }
 return photoCache.get(key);
}
export function clearPhotos(){for(const p of photoCache.values())p.then(URL.revokeObjectURL).catch(()=>{});photoCache.clear();}


// Authenticated fetch stream: no initData or token in a query string.
let subscribed=false;
export function subscribe(refresh){
 if(demo||subscribed)return;
 subscribed=true;
 let controller=null,timer=null;
 async function connect(){
  if(document.hidden||controller)return;
  controller=new AbortController();
  try{
   const response=await fetch('/api/events',{headers:{'X-Telegram-Init-Data':initData},signal:controller.signal});
   if(!response.ok)throw new Error('Stream unavailable');
   const reader=response.body.getReader(),decoder=new TextDecoder();let pending='';
   while(true){const {value,done}=await reader.read();if(done)break;pending+=decoder.decode(value,{stream:true});let split;
    while((split=pending.indexOf('\n\n'))>=0){const chunk=pending.slice(0,split);pending=pending.slice(split+2);if(chunk.includes('data: refresh'))refresh();}}
  }catch{}finally{controller=null;if(!document.hidden)timer=setTimeout(connect,5000);}
 }
 document.addEventListener('visibilitychange',()=>{clearTimeout(timer);if(document.hidden)controller?.abort();else connect();});
 window.addEventListener('pagehide',()=>{clearTimeout(timer);controller?.abort();});
 connect();
}
