"""Bundle an offline, demo-only review copy. No API keys, DB or user files."""
import base64
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'dating' / 'web'


def data_uri(path, mime):
    return f'data:{mime};base64,' + base64.b64encode(path.read_bytes()).decode('ascii')


def source(name):
    value = (WEB / name).read_text()
    value = re.sub(r'^import .*?;\n', '', value, flags=re.M)
    return re.sub(r'\bexport (?=(?:async )?(?:function|const|let))', '', value)


def build(destination=None):
    destination = Path(destination) if destination else ROOT / 'docs' / 'metch-preview.html'
    logo = data_uri(WEB / 'logo.svg', 'image/svg+xml')
    api = source('api.js').replace('const telegram = window.Telegram?.WebApp;', 'const telegram = undefined;')
    api = api.replace('new URL(path,location.origin)', "new URL(path,'https://offline-demo.invalid')")
    for name in ('anya', 'mark', 'sonya', 'artem'):
        api = api.replace(f'/assets/images/{name}.png', data_uri(WEB / 'images' / f'{name}.png', 'image/png'))
    motion = source('motion.js').replace("matchMedia('(prefers-reduced-motion: reduce)').matches", "window.__metchPreviewReducedMotion || matchMedia('(prefers-reduced-motion: reduce)').matches")
    app = source('app.js').replace('/assets/logo.svg', logo)
    # Offline demo cannot accidentally call the authenticated production transport.
    api = api.replace("const demo = !initData;", 'const demo = true;')
    code = '\n'.join([
        '(()=>{\n"use strict";',
        'const ApiModule=(()=>{' + api + '\nreturn {api,post,demo,telegram,imageSource,clearPhotos,subscribe};})();',
        'const IconModule=(()=>{' + source('icons.js') + '\nreturn {icon};})();',
        'const VirtualModule=(()=>{const {api,post,telegram:tg}=ApiModule; const {icon}=IconModule;' + source('virtual.js') + '\nreturn {createVirtual};})();',
        'const TestingModule=(()=>{const {api,post}=ApiModule; const {icon}=IconModule;' + source('testing.js') + '\nreturn {createTesting};})();',
        'const AdminModule=(()=>{const {api,post}=ApiModule; const {icon}=IconModule;' + source('admin.js') + '\nreturn {createAdmin};})();',
        'const MotionModule=(()=>{' + motion + '\nreturn {spring,springStep};})();',
        '(()=>{const {api,post,demo,telegram:tg,imageSource,clearPhotos,subscribe}=ApiModule; const {icon}=IconModule; const {spring}=MotionModule; const {createAdmin}=AdminModule; const {createTesting}=TestingModule; const {createVirtual}=VirtualModule;',
        app,
        (ROOT / 'scripts' / 'preview_editor.js').read_text(),
        '})();\n})();'
    ])
    html = (WEB / 'index.html').read_text().replace('/assets/logo.svg', logo)
    html = html.replace('<link rel="stylesheet" href="/assets/style.css">', '<style>' + (WEB / 'style.css').read_text() + '\n' + (ROOT / 'scripts' / 'preview_editor.css').read_text() + '</style>')
    html = html.replace('<script async src="https://telegram.org/js/telegram-web-app.js" id="telegram-sdk"></script>', '')
    html = html.replace('<script type="module" src="/assets/boot.js"></script>', '')
    html = html.replace('</body>', '<script>' + code.replace('</script', '<\\/script') + '</script></body>')
    html = html.replace('<title>Мэтч — на одной волне</title>', '<title>Мэтч · интерактивное превью и редактор</title>')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html)
    archive = destination.with_suffix('.zip')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        z.write(destination, 'metch-preview.html')
        z.writestr('КАК ОТКРЫТЬ.txt', 'Откройте metch-preview.html обычным браузером (Chrome, Edge, Safari). Интернет и сервер не нужны.\nКнопка «Дизайн» открывает редактор цветов, скруглений и анимации. Кнопка «Сохранить дизайн» скачает metch-design.json — его можно прислать в чат для переноса правок.\nЭто демонстрация с вымышленными анкетами. Реальных пользователей и секретов здесь нет. Переписка демонстрационная, изменения не затрагивают рабочего бота.\n')
    print(f'Built {destination.name} and {archive.name}; offline demo only')
    return destination


if __name__ == '__main__':
    build()
