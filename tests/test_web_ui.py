"""Optional Chromium integration tests: install .[ui] and system chromium."""
import shutil
import pytest

playwright = pytest.importorskip('playwright.async_api')
from tests.test_web import webapp, signed
from tests.test_store import add

pytestmark = pytest.mark.skipif(not shutil.which('chromium'), reason='System Chromium is not installed')


async def telegram_page(browser, base, uid):
    page = await browser.new_page(viewport={'width':390,'height':844},reduced_motion='reduce')
    await page.route('https://telegram.org/**', lambda route: route.fulfill(body=''))
    await page.route('**/api/photos/*', lambda route: route.fulfill(status=200,body=b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10" fill="purple"/></svg>',content_type='image/svg+xml'))
    import json
    await page.add_init_script('''window.Telegram={WebApp:{initData:''' + json.dumps(signed(uid)) + ''',ready(){},expand(){},setHeaderColor(){},setBackgroundColor(){},BackButton:{show(){},hide(){},onClick(){}},HapticFeedback:{impactOccurred(){}}}};''')
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    await page.goto(base,wait_until='domcontentloaded')
    return page,errors


async def test_real_api_two_user_mobile_match_chat_and_profile_edit(webapp):
    client, db, _ = webapp
    await add(db,1,gender='m',name='Марк')
    await add(db,2,gender='f',name='Анна',bio='Люблю <кино> & музыку')
    base=str(client.make_url('/'))
    async with playwright.async_playwright() as p:
        browser=await p.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox'])
        try:
            first,errors1=await telegram_page(browser,base,1)
            await first.locator('#swipe-card').wait_for()
            assert await first.locator('.demo-banner').count()==0
            assert await first.locator('.card-detail p').inner_text()=='Люблю <кино> & музыку'
            assert await first.locator('.card-detail кино').count()==0
            await first.get_by_role('button',name='Светлая тема',exact=True).click()
            assert await first.locator('html').get_attribute('data-theme')=='light'
            await first.get_by_role('button',name='Нравится',exact=True).click()
            second,errors2=await telegram_page(browser,base,2)
            await second.locator('#swipe-card').wait_for()
            await second.get_by_role('button',name='Нравится',exact=True).click()
            await second.get_by_role('button',name='Начать общение',exact=True).click()
            await second.get_by_role('textbox',name='Сообщение',exact=True).fill('Привет из мини-приложения 💜')
            await second.get_by_role('button',name='Отправить сообщение',exact=True).click()
            await second.get_by_text('Привет из мини-приложения 💜',exact=True).wait_for()
            assert len(await db.web_messages(1,2))==1
            await first.get_by_role('button',name='Диалоги',exact=True).click()
            await first.get_by_role('button',name='Анна',exact=False).click()
            await first.get_by_text('Привет из мини-приложения 💜',exact=True).wait_for()
            await first.get_by_role('textbox',name='Сообщение',exact=True).fill('Привет! Это настоящий ответ через API.')
            await first.get_by_role('button',name='Отправить сообщение',exact=True).click()
            await second.get_by_text('Привет! Это настоящий ответ через API.',exact=True).wait_for(timeout=10000)
            assert (await db.chat_summary(2,1))['unread']==0
            assert not await first.evaluate('document.documentElement.scrollWidth>innerWidth')
            await first.get_by_role('button',name='Назад',exact=True).click()
            await first.get_by_role('button',name='Профиль',exact=True).click()
            await first.get_by_role('button',name='Редактировать анкету',exact=False).click()
            await first.get_by_label('Имя',exact=True).fill('Маркус')
            await first.get_by_role('checkbox').check()
            await first.get_by_role('button',name='Предпросмотр',exact=False).click()
            await first.get_by_role('button',name='Всё верно · Сохранить',exact=True).click()
            await first.get_by_role('heading',name='Маркус, 25').wait_for()
            assert (await db.profile(1))['name']=='Маркус'
            assert errors1==errors2==[]
        finally:
            await browser.close()


async def test_self_contained_preview_editor_and_export(tmp_path):
    import json
    from scripts.build_preview import build
    html=build(tmp_path/'preview.html').read_text()
    assert 'const demo = true;' in html
    assert '<script src="https://telegram.org' not in html
    assert '<script type="module"' not in html
    async with playwright.async_playwright() as p:
        browser=await p.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox'])
        try:
            page=await browser.new_page(viewport={'width':390,'height':844},accept_downloads=True)
            external=[]
            errors=[]
            page.on('request',lambda r: external.append(r.url) if r.url.startswith(('https:','http:')) and r.url!='https://preview.test/' else None)
            page.on('pageerror',lambda e:errors.append(str(e)))
            await page.route('https://preview.test/',lambda route:route.fulfill(body=html,content_type='text/html'))
            await page.goto('https://preview.test/',wait_until='load')
            await page.locator('#swipe-card').wait_for()
            await page.get_by_role('button',name='Открыть редактор дизайна',exact=True).click()
            await page.get_by_label('Фон приложения',exact=True).fill('#20102a')
            await page.get_by_label('Скругление карточек',exact=True).fill('32')
            async with page.expect_download() as download:
                await page.get_by_role('button',name='Сохранить дизайн в файл',exact=True).click()
            file=await download.value
            target=tmp_path/'design.json'
            await file.save_as(target)
            data=json.loads(target.read_text())
            assert data['dark']['bg']=='#20102a' and data['radius']==32
            await page.get_by_role('button',name='Посмотреть приложение',exact=True).click()
            await page.reload(wait_until='load')
            await page.get_by_role('button',name='Открыть редактор дизайна',exact=True).click()
            assert await page.get_by_label('Фон приложения',exact=True).input_value()=='#20102a'
            await page.get_by_role('button',name='Светлая лаванда',exact=True).click()
            assert await page.locator('html').get_attribute('data-theme')=='light'
            assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
            assert external==[] and errors==[]
        finally:
            await browser.close()


async def test_mobile_admin_reports_ban_unban_audit_and_owner_without_profile(webapp, tmp_path):
    from playwright.async_api import expect
    client, db, _ = webapp
    await add(db, 1, name='Марк')
    await add(db, 2, name='Анна', bio='Люблю <кино> & музыку')
    await db.block(1, 2, 'spam')
    async with playwright.async_playwright() as p:
        browser = await p.chromium.launch(executable_path=shutil.which('chromium'), args=['--no-sandbox'])
        try:
            page, errors = await telegram_page(browser, str(client.make_url('/')), 99)
            await page.get_by_role('button', name='Админ-панель', exact=True).click()
            await page.get_by_role('heading', name='Всё под контролем.').wait_for()
            await page.screenshot(path=str(tmp_path/'admin-dark.png'), full_page=True)
            await page.locator('.admin-tabs [data-action=admin-reports]').click()
            await page.get_by_role('button', name='Посмотреть анкету', exact=True).click()
            modal = page.locator('#modal')
            await expect(modal.locator('.admin-bio')).to_have_text('Люблю <кино> & музыку')
            assert await modal.locator('кино').count() == 0
            await modal.get_by_role('button', name='Закрыть', exact=True).click()
            await page.locator('[data-action=admin-ban]').click()
            await modal.get_by_label('Причина решения', exact=True).fill('Проверенный спам в анкете')
            await modal.get_by_role('button', name='Заблокировать', exact=True).click()
            await page.get_by_text('Новых жалоб нет. Здесь спокойно 💜', exact=True).wait_for()
            assert await db.is_banned(2)
            await page.locator('.admin-tabs [data-action=admin-users]').click()
            await page.get_by_label('Поиск пользователей', exact=True).fill('2')
            await page.get_by_role('button', name='Найти', exact=True).click()
            await expect(page.locator('.admin-user')).to_have_count(1)
            await page.locator('.admin-user').click()
            await modal.get_by_role('button', name='Снять блокировку', exact=True).click()
            await modal.get_by_label('Причина решения', exact=True).fill('Апелляция проверена')
            await modal.get_by_role('button', name='Снять блокировку', exact=True).click()
            await expect(modal).not_to_be_visible()
            await page.locator('.admin-tabs [data-action=admin-audit]').click()
            await expect(page.locator('.admin-audit')).to_have_count(2)
            assert not await db.is_banned(2)
            await page.get_by_role('button', name='Светлая тема', exact=True).click()
            await page.screenshot(path=str(tmp_path/'admin-light.png'), full_page=True)
            assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
            other, other_errors = await telegram_page(browser, str(client.make_url('/')), 1)
            await other.locator('#swipe-card, .empty').first.wait_for()
            assert await other.get_by_role('button', name='Админ-панель', exact=True).count() == 0
            assert errors == other_errors == []
        finally:
            await browser.close()


async def test_telegram_launch_hash_works_while_external_sdk_stalls_and_tampering_fails(webapp):
    import asyncio
    from urllib.parse import urlencode
    client, _, _ = webapp
    gate = asyncio.Event()
    async with playwright.async_playwright() as p:
        browser = await p.chromium.launch(executable_path=shutil.which('chromium'), args=['--no-sandbox'])
        try:
            page = await browser.new_page(viewport={'width':390,'height':844})
            errors=[]
            page.on('pageerror', lambda e: errors.append(str(e)))
            async def stalled_sdk(route):
                await gate.wait()
                await route.abort()
            await page.route('https://telegram.org/**', stalled_sdk)
            launch = str(client.make_url('/'))+'#'+urlencode({'tgWebAppData':signed(99)})
            await page.goto(launch, wait_until='domcontentloaded')
            await page.get_by_role('button', name='Админ-панель', exact=True).wait_for(timeout=6000)
            assert await page.locator('.demo-banner').count() == 0
            assert not await page.evaluate('Boolean(window.Telegram)')
            await page.get_by_role('button', name='Админ-панель', exact=True).click()
            await page.get_by_role('heading', name='Всё под контролем.').wait_for()
            gate.set()
            assert errors == []
            await page.goto(str(client.make_url('/'))+'#'+urlencode({'tgWebAppData':signed(99).replace('Test','Hacker')}), wait_until='domcontentloaded')
            await page.reload(wait_until='domcontentloaded')
            await page.get_by_role('heading', name='Не удалось войти', exact=True).wait_for()
            assert await page.get_by_role('button', name='Админ-панель', exact=True).count() == 0
        finally:
            gate.set()
            await browser.close()


async def test_consented_virtual_match_friend_message_operator_reply_and_withdrawal(webapp,tmp_path):
    from playwright.async_api import expect
    client,db,_=webapp
    async with playwright.async_playwright() as p:
        browser=await p.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox'])
        try:
            friend,errors=await telegram_page(browser,str(client.make_url('/')),1)
            await expect(friend.get_by_role('button',name='Включить тестовые знакомства',exact=True)).to_be_visible()
            await expect(friend.locator('[data-action=testing]')).to_have_count(0)
            await expect(friend.get_by_text('100 тестовых анкет',exact=True)).to_have_count(0)
            await friend.get_by_role('button',name='Включить тестовые знакомства',exact=True).click()
            modal=friend.locator('#modal')
            await expect(modal).to_contain_text('Ваши сообщения читает администратор')
            await modal.get_by_role('button',name='Подтвердить и включить',exact=True).click()
            assert not (await db.virtual_state(1))['enabled']
            await modal.get_by_role('checkbox').check()
            await modal.get_by_role('button',name='Подтвердить и включить',exact=True).click()
            await expect(friend.locator('#swipe-card .photo-chip')).to_contain_text('ВИРТУАЛЬНЫЙ ПРОФИЛЬ')
            await friend.locator('#swipe-card').scroll_into_view_if_needed()
            await friend.screenshot(path=str(tmp_path/'virtual-feed.png'))
            await friend.get_by_role('button',name='Нравится',exact=True).click()
            await modal.get_by_role('heading',name='Тестовый мэтч создан',exact=True).wait_for()
            await modal.get_by_role('button',name='Начать тестовый диалог',exact=True).click()
            await friend.get_by_role('textbox',name='Сообщение',exact=True).fill('Привет! Проверяю тестовое знакомство.')
            await friend.get_by_role('button',name='Отправить сообщение',exact=True).click()
            await friend.get_by_text('Привет! Проверяю тестовое знакомство.',exact=True).wait_for()
            owner,owner_errors=await telegram_page(browser,str(client.make_url('/')),99)
            await owner.get_by_role('button',name='Админ-панель',exact=True).click()
            await expect(owner.get_by_role('button',name='Открыть тестовые диалоги',exact=False)).to_be_visible()
            await expect(owner.locator('[data-action=testing]')).to_have_count(0)
            await expect(owner.get_by_text('100 тестовых анкет',exact=True)).to_have_count(0)
            await owner.get_by_role('button',name='Открыть тестовые диалоги',exact=False).click()
            await expect(owner.locator('.chat-row[data-action=virtual-operator]')).to_have_count(1)
            await owner.locator('.chat-row[data-action=virtual-operator]').click()
            await owner.get_by_text('Привет! Проверяю тестовое знакомство.',exact=True).wait_for()
            await owner.get_by_role('textbox',name='Сообщение',exact=True).fill('Привет! Это ответ администратора от имени Ани.')
            await owner.get_by_role('button',name='Отправить сообщение',exact=True).click()
            await friend.get_by_text('Привет! Это ответ администратора от имени Ани.',exact=True).wait_for(timeout=12000)
            assert 'администратору' in await friend.locator('.virtual-disclosure').inner_text()
            await friend.screenshot(path=str(tmp_path/'virtual-friend-chat.png'))
            await owner.screenshot(path=str(tmp_path/'virtual-operator-chat.png'))
            await friend.get_by_role('button',name='Назад',exact=True).click()
            await friend.locator('.chat-row[data-action=chat]').click()
            await friend.get_by_text('Привет! Это ответ администратора от имени Ани.',exact=True).wait_for()
            await friend.get_by_role('button',name='Назад',exact=True).click()
            await friend.get_by_role('button',name='Знакомства',exact=True).click()
            await friend.get_by_role('button',name='Выключить и удалить',exact=True).click()
            await modal.get_by_role('button',name='Выключить и удалить',exact=True).click()
            await expect(friend.get_by_role('button',name='Включить тестовые знакомства',exact=True)).to_be_visible()
            await expect(owner.locator('.admin-empty')).to_be_visible(timeout=12000)
            assert not (await db.virtual_state(1))['enabled']
            assert (await db.stats())['profiles']==(await db.stats())['messages']==0
            assert errors==owner_errors==[]
        finally:
            await browser.close()
