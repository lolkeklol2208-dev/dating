"""Build a Windows review package: browser launcher, offline app, instructions."""
from pathlib import Path
import importlib.util
import zipfile

ROOT = Path(__file__).resolve().parents[1]

LAUNCHER = r'''@echo off
setlocal DisableDelayedExpansion
set "METCH_HTML=%~dp0metch-preview.html"
if not exist "%METCH_HTML%" (
  echo Please extract ALL files from the ZIP first.
  echo Keep START.cmd and metch-preview.html in the same folder.
  pause
  exit /b 1
)
set "METCH_BROWSER="
if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" set "METCH_BROWSER=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not defined METCH_BROWSER if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" set "METCH_BROWSER=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
if not defined METCH_BROWSER if exist "%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe" set "METCH_BROWSER=%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"
if not defined METCH_BROWSER if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "METCH_BROWSER=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined METCH_BROWSER if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "METCH_BROWSER=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
if defined METCH_BROWSER (
  start "" "%METCH_BROWSER%" --new-window "%METCH_HTML%"
  exit /b 0
)
start "" "%METCH_HTML%"
exit /b 0
'''

INSTRUCTIONS = '''МЭТЧ · ЛОКАЛЬНОЕ ПРЕВЬЮ ДЛЯ WINDOWS

КАК ОТКРЫТЬ
1. Нажмите правой кнопкой на Metch-Windows.zip → «Извлечь всё».
2. Откройте извлечённую папку Metch-Windows.
3. Дважды нажмите START.cmd.

Приложение откроется в Microsoft Edge или Google Chrome.
Устанавливать Python, сервер, расширения или дополнительные программы не нужно.
Интернет для просмотра не требуется. Файлы остаются на вашем компьютере.

ЕСЛИ START.cmd НЕ ОТКРЫЛСЯ
Нажмите правой кнопкой на metch-preview.html → «Открыть с помощью» → Microsoft Edge.
Можно просто перетащить metch-preview.html в окно Edge или Chrome.
Права администратора и отключение защиты Windows не нужны.

КАК РЕДАКТИРОВАТЬ
Кнопка «Дизайн» открывает редактор:
• переключайте тёмную сливовую и светлую лавандовую темы;
• меняйте фон, цвет карточек, акцент и текст отдельно для каждой темы;
• меняйте скругления карточки и настройку анимаций;
• «Сохранить дизайн в файл» скачивает metch-design.json.
Пришлите этот JSON в чат, чтобы перенести ваши правки в основное приложение.
Для других изменений можно написать пожелания обычным текстом или прислать скриншот.
В разделе «Профиль» можно попробовать редактирование демонстрационной анкеты.

ВАЖНО
Это демонстрация с вымышленными анкетами. Лайки, мэтчи и сообщения не отправляются
реальным людям. Рабочий бот и его база от этого файла не меняются.
Данные демо сбрасываются при перезагрузке. Оформление сохраняется в браузере,
если он разрешает локальное хранилище. В любом случае можно экспортировать JSON.
Для переноса настроек на другой компьютер используйте экспорт и импорт дизайна.

Не запускайте файл прямо из окна ZIP: сначала «Извлечь всё».
Если браузер запрещает открытие локальных файлов корпоративной политикой,
используйте разрешённый браузер или обратитесь к администратору компьютера.
'''


def build_windows(destination=None):
    destination = Path(destination) if destination else ROOT / 'docs' / 'Metch-Windows.zip'
    spec = importlib.util.spec_from_file_location('metch_preview_builder', ROOT / 'scripts' / 'build_preview.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    html = module.build()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.write(html, 'Metch-Windows/metch-preview.html')
        archive.writestr('Metch-Windows/START.cmd', LAUNCHER.replace('\n', '\r\n').encode('ascii'))
        archive.writestr('Metch-Windows/ПРОЧИТАЙТЕ.txt', INSTRUCTIONS.replace('\n', '\r\n').encode('utf-8-sig'))
    print(f'Built {destination.name}: no installer, no credentials, no server')
    return destination


if __name__ == '__main__':
    build_windows()
