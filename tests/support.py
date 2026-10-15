"""Shared fakes and database isolation helpers for the test suite."""
import contextlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import config
import store


class DatabaseIsolation:
    """Runs each test against a private temporary SQLite file.

    ``config.BASE_DIR`` is redirected too, so the repository's ``birthdays.json``
    is never consulted and no legacy rows leak into a test.
    """

    def _setup_db(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = (config.DB_PATH, config.BASE_DIR)
        config.BASE_DIR = self._tmp.name
        config.DB_PATH = str(Path(self._tmp.name) / 'test.db')
        store.close_connection()
        store.init()

    def _teardown_db(self):
        store.close_connection()
        config.DB_PATH, config.BASE_DIR = self._saved
        self._tmp.cleanup()


class BotTestCase(DatabaseIsolation, unittest.TestCase):
    def setUp(self):
        self._setup_db()

    def tearDown(self):
        self._teardown_db()


class AsyncBotTestCase(DatabaseIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._setup_db()

    async def asyncTearDown(self):
        self._teardown_db()


def user(uid, first_name='Test', last_name='User', username=None, is_bot=False):
    return FakeUser(uid, first_name, last_name, username, is_bot)


def private_chat(uid):
    return SimpleNamespace(id=uid, type='private', title=None, username=None)


def group_chat(gid, title='Group'):
    return SimpleNamespace(id=gid, type='supergroup', title=title, username='grp')


class FakeUser:
    def __init__(self, uid, first_name='Test', last_name='User', username=None, is_bot=False):
        self.id = uid
        self.first_name = first_name
        self.last_name = last_name
        self.username = username
        self.is_bot = is_bot

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'.strip()


class FakeMessage:
    """Minimal stand-in for ``aiogram.types.Message`` used by the handlers."""

    def __init__(self, text=None, from_user=None, chat=None, message_id=1,
                 content_type='text', caption=None, edit_date=None, sender_chat=None):
        self.text = text
        self.caption = caption
        self.from_user = from_user
        self.chat = chat
        self.message_id = message_id
        self.content_type = content_type
        self.edit_date = edit_date
        self.sender_chat = sender_chat
        self.answers = []
        self.edits = []
        self.documents = []

    async def answer(self, text=None, **kwargs):
        self.answers.append({'text': text, **kwargs})

    async def edit_text(self, text=None, **kwargs):
        self.edits.append({'text': text, **kwargs})

    async def answer_document(self, document, **kwargs):
        self.documents.append({'document': document, **kwargs})

    @property
    def last_answer(self):
        return self.answers[-1]['text'] if self.answers else None

    @property
    def last_edit(self):
        return self.edits[-1]['text'] if self.edits else None


class FakeCallback:
    """Minimal stand-in for ``aiogram.types.CallbackQuery``."""

    def __init__(self, data, from_user=None, message=None, cid='cb-1'):
        self.data = data
        self.from_user = from_user
        self.message = message
        self.id = cid
        self.answers = []

    async def answer(self, text=None, show_alert=False, **kwargs):
        self.answers.append({'text': text, 'show_alert': show_alert})

    @property
    def last_answer(self):
        return self.answers[-1]['text'] if self.answers else None


class FakeState:
    """In-memory stand-in for ``aiogram.fsm.context.FSMContext``."""

    def __init__(self):
        self.state = None
        self.data = {}

    async def clear(self):
        self.state = None
        self.data = {}

    async def set_state(self, state=None):
        self.state = state

    async def get_state(self):
        return self.state

    async def set_data(self, data):
        self.data = dict(data)

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def get_data(self):
        return dict(self.data)


class FakeBot:
    """Records outbound calls and lets tests simulate Telegram failures."""

    def __init__(self, username='testbot', uid=555, can_read_all_group_messages=False):
        self.id = uid
        self._username = username
        self.can_read_all_group_messages = can_read_all_group_messages
        self.sent = []
        self.copied = []
        self.member_status = 'member'
        self.member_error = None
        self.copy_error = None
        self.send_error = None
        self.chat = SimpleNamespace(id=-100123, type='channel', username='testchannel')
        self.custom_emoji_stickers = []
        self.webhook_url = ''

    async def me(self):
        return SimpleNamespace(username=self._username, id=self.id)

    async def send_message(self, chat_id, text, **kwargs):
        if self.send_error:
            raise self.send_error
        self.sent.append({'chat_id': chat_id, 'text': text, 'kwargs': kwargs})

    async def copy_message(self, chat_id, from_chat_id, message_id, **kwargs):
        if self.copy_error:
            raise self.copy_error
        self.copied.append((chat_id, from_chat_id, message_id))

    async def get_chat_member(self, chat_id, user_id):
        if self.member_error:
            raise self.member_error
        return SimpleNamespace(status=self.member_status, is_member=True)

    async def get_chat(self, chat_id):
        return self.chat

    async def get_webhook_info(self):
        return SimpleNamespace(url=self.webhook_url)

    async def get_me(self):
        return await self.me()

    async def get_custom_emoji_stickers(self, ids):
        return self.custom_emoji_stickers


def forbidden(message='Forbidden: bot was blocked by the user'):
    from aiogram.exceptions import TelegramForbiddenError
    return TelegramForbiddenError(SimpleNamespace(), message)


def bad_request(message='Bad Request: message to copy not found'):
    from aiogram.exceptions import TelegramBadRequest
    return TelegramBadRequest(SimpleNamespace(), message)


def retry_after(seconds=1, message='Flood control exceeded'):
    from aiogram.exceptions import TelegramRetryAfter
    return TelegramRetryAfter(SimpleNamespace(), message, seconds)


def api_error(message='boom'):
    from aiogram.exceptions import TelegramAPIError
    return TelegramAPIError(SimpleNamespace(), message)


async def run_until(predicate, factory, timeout=3.0, step=0.02):
    """Run an endless worker task until ``predicate()`` is true, then cancel it."""
    import asyncio

    task = asyncio.create_task(factory())
    try:
        waited = 0.0
        while waited < timeout:
            if predicate():
                return
            await asyncio.sleep(step)
            waited += step
        raise AssertionError('worker did not reach the expected state in time')
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
