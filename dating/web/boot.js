// A slow Telegram SDK must not block the whole page on a permanent splash screen.
const sdk = document.querySelector('#telegram-sdk');
if (!window.Telegram?.WebApp && sdk) {
 await new Promise(resolve => {
  const done = () => { clearTimeout(timer); resolve(); };
  const timer = setTimeout(done, 1500);
  sdk.addEventListener('load', done, {once:true});
  sdk.addEventListener('error', done, {once:true});
 });
}
try {
 await import('./app.js');
} catch {
 const root = document.querySelector('#app');
 root.replaceChildren();
 const panel = document.createElement('main');
 panel.className = 'page empty';
 const title = document.createElement('h1');
 title.textContent = 'Не удалось загрузить Мэтч';
 const text = document.createElement('p');
 text.textContent = 'Проверьте соединение и попробуйте снова.';
 const retry = document.createElement('button');
 retry.className = 'primary';
 retry.textContent = 'Попробовать снова';
 retry.onclick = () => location.reload();
 panel.append(title, text, retry);
 root.append(panel);
}
