import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from dating.store import Store
from dating.features import register_features, relay_message
from dating.middleware import AccessMiddleware
from dating.notifications import app_keyboard

log = logging.getLogger(__name__)


def keyboard(*rows):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=value) for label, value in row]
        for row in rows
    ])


HOME = keyboard([('Смотреть анкеты →', 'browse')],
                [('Мои мэтчи · Диалоги 💬', 'matches:0')],
                [('Моя анкета', 'profile'), ('Настройки поиска', 'filters')],
                [('Правила и помощь', 'help')])
CANCEL = keyboard([('Отмена', 'cancel')])


class Form(StatesGroup):
    name = State()
    age = State()
    gender = State()
    seeking = State()
    city = State()
    bio = State()
    photo = State()
    preview = State()
    age_range = State()


def caption(p):
    return f"<b>{escape(p['name'])}, {p['age']}</b>\n{escape(p['city'])}\n\n{escape(p['bio'])}"


def contact(p):
    # Telegram usernames may have changed since the last interaction; tg:// uses the stable user ID.
    return f'<a href="tg://user?id={p["id"]}">Открыть профиль Telegram</a>'


def clean(value):
    return ' '.join((value or '').split())


def make_router(store: Store, admin_id: int | None = None, webapp_url: str | None = None):
    router = Router()
    router.message.filter(F.chat.type == "private")
    router.callback_query.filter(F.message.chat.type == "private")
    access = AccessMiddleware(store, keyboard)
    router.message.middleware(access)
    router.callback_query.middleware(access)
    register_features(router, store, admin_id, keyboard, HOME, webapp_url)

    async def show_home(message):
        if webapp_url:
            await message.answer('Ваши знакомства и диалоги — в Мэтч 💜\n\nНажмите кнопку ниже. Если кнопка меню пропала — отправьте /app.',
                                 reply_markup=app_keyboard(webapp_url))
            return
        await message.answer('<b>Мэтч</b>\nЗнакомства начинаются с одного «привет».\n\nВыберите, что хочется сделать.', reply_markup=HOME)

    async def show_card(message, p, own=False):
        if own:
            status = 'Анкета видна в поиске' if p['active'] else 'Анкета скрыта'
            markup = keyboard([('Редактировать', 'edit')],
                              [('Скрыть' if p['active'] else 'Показать', f'active:{0 if p["active"] else 1}')],
                              [('Удалить анкету', 'delete')], [('В меню', 'home')])
            await message.answer_photo(p['photo'], caption=caption(p) + f'\n\n<i>{status}</i>', reply_markup=markup)
        else:
            markup = keyboard([('Пропустить', f'skip:{p["id"]}'), ('Нравится ♡', f'like:{p["id"]}')],
                              [('Пожаловаться', f'report:{p["id"]}'), ('Заблокировать', f'block:{p["id"]}')],
                              [('В меню', 'home')])
            await message.answer_photo(p['photo'], caption=caption(p), reply_markup=markup)

    async def browse(message, uid):
        me = await store.profile(uid)
        if not me:
            await message.answer('Сначала создайте анкету.', reply_markup=keyboard([('Создать анкету', 'join')]))
        elif not me['active']:
            await message.answer('Ваша анкета скрыта. Включите её, чтобы знакомиться.', reply_markup=keyboard([('Показать анкету', 'active:1')], [('В меню', 'home')]))
        elif p := await store.candidate(uid):
            await show_card(message, p)
        else:
            await message.answer('Вы посмотрели все подходящие анкеты.\nЗагляните позже или измените настройки поиска.', reply_markup=keyboard([('Обновить', 'browse'), ('Настройки', 'filters')], [('Вернуть пропущенные', 'reset:ask')], [('В меню', 'home')]))

    async def begin(message, state):
        await state.clear()
        await state.set_state(Form.name)
        await message.answer('<b>Ваша анкета · 1/7</b>\nКак вас зовут? От 2 до 30 символов.\n\nОтменить можно на любом шаге: /cancel', reply_markup=CANCEL)

    @router.message(Command('app'))
    async def open_app(message: Message, state: FSMContext):
        await store.leave_chat(message.from_user.id)
        await state.clear()
        await show_home(message)

    @router.message(CommandStart())
    async def start(message: Message, state: FSMContext):
        await store.leave_chat(message.from_user.id)
        await state.clear()
        await store.update_username(message.from_user.id, message.from_user.username)
        if webapp_url:
            await message.answer('<b>Мэтч · На одной волне 💜</b>\n\nАнкеты, взаимные симпатии и ваши диалоги — в приложении. А здесь я сообщу о новом мэтче и сообщении.\n\nТолько 18+. /help — данные и безопасность.', reply_markup=app_keyboard(webapp_url))
        elif await store.profile(message.from_user.id):
            await show_home(message)
        else:
            await message.answer('<b>Мэтч</b>\nКто-то ваш — совсем близко.\n\nСоздайте анкету, смотрите людей в своём городе и ставьте лайки. Взаимная симпатия откроет диалог внутри бота. Можно также перейти в Telegram-профиль.\n\nТолько для совершеннолетних. Продолжая, вы подтверждаете, что вам 18+, и соглашаетесь на хранение анкеты. Фото и описание увидят другие участники.\n\n/help — данные и безопасность.', reply_markup=keyboard([('Мне есть 18 · Создать анкету', 'join')], [('Как это работает', 'help')]))

    @router.message(Command('cancel'))
    async def cancel_command(message: Message, state: FSMContext):
        await store.leave_chat(message.from_user.id)
        await state.clear()
        await show_home(message)

    @router.message(Command('help'))
    async def help_command(message: Message):
        await help_text(message)

    async def help_text(message):
        await message.answer('<b>Знакомьтесь в своём темпе</b>\n\n♡ Лайки анонимны до взаимной симпатии. После совпадения можно переписываться внутри бота и открыть Telegram-профиль. Доступность профиля зависит от настроек Telegram.\n\nПоиск учитывает город, пол и возрастные предпочтения обоих участников. Укажите город одинаково, например «Москва».\n\nНе переводите деньги незнакомым людям. Первую встречу назначайте в общественном месте. Жалоба блокирует человека для вас; при настроенном модераторе он получит уведомление. Автоматической проверки анкет нет.\n\n<b>Данные</b>\nХраним Telegram ID, имя пользователя, анкету, идентификатор фото, реакции, совпадения, блокировки, жалобы, черновики и текст переписки в базе сервера. Бан модератора хранится отдельно как Telegram ID, причина и время, чтобы удаление анкеты не позволяло обойти блокировку. Отдельно хранится журнал решений модератора с ID, причиной и временем; реальная личная переписка в админ-панели не показывается. Только в отдельно включённом режиме тестовых знакомств ваши сообщения читает и ведёт администратор от имени вымышленных персонажей; перед включением требуется ваше согласие. Номер телефона и точную геолокацию не запрашиваем. «Моя анкета → Удалить» удаляет анкету, черновики и связанные реакции, переписки и жалобы. В незавершённом заполнении данные можно удалить через /delete. Историю также можно удалить, завершив знакомство. Сообщения, уже отправленные в Telegram, остаются в чатах.\n\n/start — меню · /cancel — отмена', reply_markup=keyboard([('В меню', 'home')]))

    @router.callback_query(F.data.in_({'home', 'cancel', 'help', 'join', 'edit'}))
    async def navigation(call: CallbackQuery, state: FSMContext):
        await store.leave_chat(call.from_user.id)
        await call.answer()
        if call.data in {'join', 'edit'}:
            await begin(call.message, state)
        else:
            await state.clear()
            if call.data == 'help':
                await help_text(call.message)
            else:
                await show_home(call.message)

    @router.message(Form.name)
    async def name(message: Message, state: FSMContext):
        value = clean(message.text)
        if not 2 <= len(value) <= 30:
            await message.answer('Напишите имя текстом: от 2 до 30 символов.', reply_markup=CANCEL)
            return
        await state.update_data(name=value)
        await state.set_state(Form.age)
        await message.answer('<b>2/7 · Возраст</b>\nСколько вам лет? Введите число от 18 до 99.', reply_markup=CANCEL)

    @router.message(Form.age)
    async def age(message: Message, state: FSMContext):
        text = clean(message.text)
        if not text.isascii() or not text.isdigit() or not 18 <= int(text) <= 99:
            await message.answer('Знакомства доступны с 18 лет. Введите возраст от 18 до 99.', reply_markup=CANCEL)
            return
        await state.update_data(age=int(text))
        await state.set_state(Form.gender)
        await message.answer('<b>3/7 · О вас</b>\nВыберите вариант для поиска.', reply_markup=keyboard([('Я мужчина', 'gender:m'), ('Я женщина', 'gender:f')], [('Отмена', 'cancel')]))

    @router.callback_query(Form.gender, F.data.startswith('gender:'))
    async def gender(call: CallbackQuery, state: FSMContext):
        value = call.data.split(':')[1]
        if value not in {'m', 'f'}:
            await call.answer('Выберите вариант кнопкой.')
            return
        await call.answer()
        await state.update_data(gender=value)
        await state.set_state(Form.seeking)
        await call.message.answer('<b>4/7 · Кто вам интересен?</b>', reply_markup=keyboard([('Мужчины', 'seeking:m'), ('Женщины', 'seeking:f')], [('Все', 'seeking:any')], [('Отмена', 'cancel')]))

    @router.callback_query(Form.seeking, F.data.startswith('seeking:'))
    async def seeking(call: CallbackQuery, state: FSMContext):
        value = call.data.split(':')[1]
        if value not in {'m', 'f', 'any'}:
            await call.answer('Выберите вариант кнопкой.')
            return
        await call.answer()
        await state.update_data(seeking=value)
        await state.set_state(Form.city)
        await call.message.answer('<b>5/7 · Ваш город</b>\nНапишите название целиком, например: Санкт-Петербург.', reply_markup=CANCEL)

    @router.message(Form.city)
    async def city(message: Message, state: FSMContext):
        value = clean(message.text)
        if not 2 <= len(value) <= 60 or not any(c.isalpha() for c in value):
            await message.answer('Введите название города: от 2 до 60 символов.', reply_markup=CANCEL)
            return
        await state.update_data(city=value)
        await state.set_state(Form.bio)
        await message.answer('<b>6/7 · Пара слов о себе</b>\nЧто любите и кого хотите встретить? От 10 до 500 символов.\n\nНапример: «Люблю утренний кофе, кино и спонтанные прогулки. Ищу человека, с которым легко молчать и смеяться».', reply_markup=CANCEL)

    @router.message(Form.bio)
    async def bio(message: Message, state: FSMContext):
        value = clean(message.text)
        if not 10 <= len(value) <= 500:
            await message.answer('Расскажите о себе текстом: от 10 до 500 символов.', reply_markup=CANCEL)
            return
        await state.update_data(bio=value)
        await state.set_state(Form.photo)
        await message.answer('<b>7/7 · Ваше фото</b>\nПришлите одно фото, на котором хорошо видно вас. Отправьте его как фотографию, не как файл.', reply_markup=CANCEL)

    @router.message(Form.photo)
    async def photo(message: Message, state: FSMContext):
        if not message.photo:
            await message.answer('Нужна фотография. Пришлите её через скрепку → Галерея.', reply_markup=CANCEL)
            return
        await state.update_data(photo=message.photo[-1].file_id)
        await state.set_state(Form.preview)
        data = await state.get_data()
        await message.answer_photo(data['photo'], caption=caption(data) + '\n\n<i>Предпросмотр · ещё не опубликовано</i>',
            reply_markup=keyboard([('Всё верно · Сохранить', 'publish')], [('Заполнить заново', 'edit'), ('Отмена', 'cancel')]))

    @router.callback_query(Form.preview, F.data == 'publish')
    async def publish(call: CallbackQuery, state: FSMContext):
        await store.save(call.from_user.id, call.from_user.username, await state.get_data())
        await state.clear()
        await call.answer('Анкета сохранена ♡')
        await show_card(call.message, await store.profile(call.from_user.id), own=True)

    @router.callback_query(F.data.in_({'reset:ask', 'reset:yes'}))
    async def reset(call: CallbackQuery):
        await call.answer()
        if call.data == 'reset:ask':
            await call.message.answer('Снова показать пропущенные анкеты? Лайки и мэтчи сохранятся.',
                reply_markup=keyboard([('Да, показать снова', 'reset:yes')], [('В меню', 'home')]))
        else:
            await store.reset_skips(call.from_user.id)
            await browse(call.message, call.from_user.id)

    @router.callback_query(F.data == 'profile')
    async def profile(call: CallbackQuery, state: FSMContext):
        await store.leave_chat(call.from_user.id)
        await call.answer()
        await state.clear()
        await store.update_username(call.from_user.id, call.from_user.username)
        if p := await store.profile(call.from_user.id):
            await show_card(call.message, p, own=True)
        else:
            await call.message.answer('Пока здесь чистый лист.', reply_markup=keyboard([('Создать анкету', 'join')]))

    @router.callback_query(F.data == 'browse')
    async def browse_callback(call: CallbackQuery, state: FSMContext):
        await store.leave_chat(call.from_user.id)
        await call.answer()
        await state.clear()
        await store.update_username(call.from_user.id, call.from_user.username)
        await browse(call.message, call.from_user.id)

    @router.callback_query(F.data.startswith('active:'))
    async def active(call: CallbackQuery):
        await store.active(call.from_user.id, call.data == 'active:1')
        await call.answer('Сохранено')
        await show_home(call.message)

    @router.callback_query(F.data == 'filters')
    async def filters(call: CallbackQuery, state: FSMContext):
        await store.leave_chat(call.from_user.id)
        await call.answer()
        if not (p := await store.profile(call.from_user.id)):
            await call.message.answer('Сначала создайте анкету.', reply_markup=keyboard([('Создать', 'join')]))
            return
        await state.clear()
        await state.set_state(Form.age_range)
        await call.message.answer(f'<b>Настройки поиска</b>\nСейчас: {p["min_age"]}–{p["max_age"]} лет.\n\nВведите диапазон через пробел, например: 23 35.\nГород и предпочтения можно изменить через редактирование анкеты.', reply_markup=CANCEL)

    @router.message(Form.age_range)
    async def age_range(message: Message, state: FSMContext):
        values = (message.text or '').split()
        if len(values) != 2 or not all(v.isascii() and v.isdigit() and len(v) <= 2 for v in values):
            await message.answer('Нужны два числа через пробел. Например: 23 35.', reply_markup=CANCEL)
            return
        low, high = map(int, values)
        if not 18 <= low <= high <= 99:
            await message.answer('Диапазон должен быть от 18 до 99 лет, от меньшего к большему.', reply_markup=CANCEL)
            return
        await store.filters(message.from_user.id, low, high)
        await state.clear()
        await message.answer('Настройки сохранены.', reply_markup=HOME)

    async def notify_match(bot, uid, other):
        try:
            await bot.send_message(uid, f'<b>Это взаимно ♡</b>\nВы и {escape(other["name"])} понравились друг другу.\n\n{contact(other)}\nНачните с простого «привет».', reply_markup=keyboard([('Написать 💬', f'chat:{other["id"]}')], [('Все мэтчи', 'matches:0')]))
        except (TelegramForbiddenError, TelegramBadRequest, TelegramNetworkError):
            # A blocked bot or unavailable Telegram must not undo the durable match.
            log.warning('Match notification was not delivered; match remains in the database')

    @router.callback_query(F.data.regexp(r'^(like|skip):\d+$'))
    async def reaction(call: CallbackQuery, state: FSMContext, bot: Bot):
        if await state.get_state():
            await call.answer('Завершите анкету или нажмите /cancel.', show_alert=True)
            return
        kind, target = call.data.split(':')
        result = await store.react(call.from_user.id, int(target), kind, notify=bool(webapp_url))
        await call.answer('Анкета недоступна' if result is None else 'Лайк отправлен ♡' if kind == 'like' else 'Пропущено')
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass
        if result and not webapp_url:
            me, other = await store.profile(call.from_user.id), await store.profile(int(target))
            if me and other:
                await notify_match(bot, me['id'], other)
                await notify_match(bot, other['id'], me)
        await browse(call.message, call.from_user.id)

    @router.callback_query(F.data.regexp(r'^matches:\d+$'))
    async def matches(call: CallbackQuery, state: FSMContext):
        await store.leave_chat(call.from_user.id)
        await state.clear()
        await call.answer()
        offset = int(call.data.split(':')[1])
        if offset > 1000000:
            return
        rows = await store.matches(call.from_user.id, offset)
        if not rows:
            await call.message.answer('Здесь появятся ваши взаимные симпатии.', reply_markup=HOME)
            return
        for p in rows:
            await call.message.answer_photo(p['photo'], caption=caption(p) + '\n\n' + contact(p),
                reply_markup=keyboard([('Написать 💬', f'chat:{p["id"]}')], [('Заблокировать', f'block:{p["id"]}'), ('Пожаловаться', f'report:{p["id"]}')]))
        await call.message.answer('Ваши симпатии ♡', reply_markup=keyboard([('Далее', f'matches:{offset+5}')], [('В меню', 'home')]))

    @router.callback_query(F.data.regexp(r'^(block|report):\d+$'))
    async def safety(call: CallbackQuery):
        action, target = call.data.split(':')
        await call.answer()
        if action == 'report':
            await call.message.answer('Что случилось? Жалоба также заблокирует человека для вас.', reply_markup=keyboard([('Спам / мошенничество', f'flag:{target}:spam')], [('Неприемлемый контент', f'flag:{target}:content')], [('Младше 18 лет', f'flag:{target}:underage')], [('Отмена', 'home')]))
            return
        await store.block(call.from_user.id, int(target))
        await call.message.answer('Пользователь заблокирован. Вы больше не увидите друг друга в поиске и симпатиях.', reply_markup=HOME)
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass

    @router.callback_query(F.data.regexp(r'^flag:\d+:(spam|content|underage)$'))
    async def report(call: CallbackQuery, bot: Bot):
        _, target, reason = call.data.split(':')
        await store.block(call.from_user.id, int(target), reason)
        await call.answer('Жалоба сохранена')
        await call.message.answer('Спасибо. Жалоба сохранена, пользователь заблокирован для вас.', reply_markup=HOME)
        if admin_id:
            try:
                await bot.send_message(admin_id, f'Жалоба · {reason}\nОт: {call.from_user.id}\nНа: {target}\nАвтоматическое уведомление; проверьте запись в базе.')
            except (TelegramForbiddenError, TelegramBadRequest, TelegramNetworkError):
                log.warning('Report notification was not delivered; report remains in the database')

    @router.callback_query(F.data == 'delete')
    async def confirm_delete(call: CallbackQuery):
        await call.answer()
        await call.message.answer('Удалить анкету и все связанные данные? Это действие нельзя отменить.', reply_markup=keyboard([('Да, удалить', 'delete:yes')], [('Оставить анкету', 'home')]))

    @router.callback_query(F.data == 'delete:yes')
    async def delete(call: CallbackQuery, state: FSMContext):
        await store.delete(call.from_user.id)
        await state.clear()
        await call.answer('Удалено')
        await call.message.answer('Анкета и связанные записи удалены. Сообщения в Telegram остаются в чате.\n\nЕсли захотите вернуться — /start.')

    @router.callback_query()
    async def stale(call: CallbackQuery):
        await call.answer('Эта кнопка устарела. Используйте /start.', show_alert=True)

    @router.message()
    async def fallback(message: Message, state: FSMContext, bot: Bot):
        if await state.get_state():
            await message.answer('Выберите вариант кнопкой выше или отмените заполнение: /cancel.')
        elif webapp_url:
            await message.answer('Ваши знакомства и диалоги — в Мэтч 💜', reply_markup=app_keyboard(webapp_url))
        elif not await relay_message(message, store, bot, keyboard, HOME):
            await show_home(message)

    return router
