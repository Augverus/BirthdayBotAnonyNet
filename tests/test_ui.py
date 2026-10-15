"""Offline checks for keyboard migrations, premium-only rendering and Mini App links."""
import os
os.environ.setdefault('BOT_TOKEN', '123456789:offline_test_token_only')

import re
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update, User

import config
import main
import store
import ui

PICTOGRAPH = re.compile('[\U0001F000-\U0001FAFF\u2600-\u27BF\u2300-\u23FF\u2B00-\u2BFF\uFE0F]')


class Session(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.reject_custom = False

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        yield b''

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, AnswerCallbackQuery):
            return True
        if isinstance(method, (SendMessage, EditMessageText)):
            if self.reject_custom and '<tg-emoji' in method.text:
                raise TelegramBadRequest(method, 'CUSTOM_EMOJI_NOT_ALLOWED')
            return Message(message_id=900, date=datetime.now(timezone.utc),
                           chat=Chat(id=method.chat_id, type='private'), text=method.text)
        raise AssertionError(type(method).__name__)


class UITests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = patch.multiple(config, DB_PATH=str(Path(self.tmp.name)/'db.sqlite'),
                                    BASE_DIR=Path(self.tmp.name), ADMIN_IDS={1})
        self.patch.start()
        store.init()
        main.dp.storage.storage.clear()
        store.track_user(User(id=2,is_bot=False,first_name='Test'), 'test', 'message')
        self.session = Session()
        self.bot = Bot(token=os.environ['BOT_TOKEN'],session=self.session)
        self.bot.session.middleware(ui.EmojiFallback())
        self.seq = 10

    async def asyncTearDown(self):
        await self.bot.session.close()
        store.close_connection()
        self.patch.stop()
        self.tmp.cleanup()

    async def send(self,text,uid=2):
        self.seq += 1
        await main.dp.feed_update(self.bot,Update(update_id=self.seq,message=Message(
            message_id=self.seq,date=datetime.now(timezone.utc),chat=Chat(id=uid,type='private'),
            from_user=User(id=uid,is_bot=False,first_name='Test'),text=text)))

    async def callback(self,data):
        self.seq+=1
        await main.dp.feed_update(self.bot,Update(update_id=self.seq,callback_query=CallbackQuery(
            id=str(self.seq),chat_instance='test',data=data,
            from_user=User(id=1,is_bot=False,first_name='Owner'),
            message=Message(message_id=99,date=datetime.now(timezone.utc),chat=Chat(id=1,type='private'),text='Panel'))))

    def test_home_is_compact_with_premium_icons_only(self):
        store.update_user(2,month=1,day=5)
        keyboard=ui.home(2)
        self.assertEqual([len(row) for row in keyboard.keyboard],[2,2,2])
        self.assertEqual(keyboard.keyboard[0][0].style,'success')
        for row in keyboard.keyboard:
            for button in row:
                self.assertIsNone(PICTOGRAPH.search(button.text))
                self.assertTrue(button.icon_custom_emoji_id)
        store.set_setting('custom_emoji','0')
        self.assertTrue(all(b.icon_custom_emoji_id is None for row in ui.home(2).keyboard for b in row))
        self.assertEqual(ui.emoji('birthday','\U0001f382'),'')

    def test_calendar_buttons_are_plain_persian_numbers(self):
        keyboard=main.days_keyboard(1)
        self.assertEqual(keyboard.inline_keyboard[0][0].text,'۱')
        self.assertEqual(keyboard.inline_keyboard[0][0].callback_data,'day:1:1')
        self.assertEqual(keyboard.inline_keyboard[0][0].style,'primary')

    async def test_old_keyboard_labels_still_route(self):
        store.update_user(2,month=1,day=5)
        await self.send('\U0001f515 غیرفعال کردن اعلان')
        self.assertEqual(store.user(2)['notification'],0)
        await self.send('\U0001f514 فعال کردن اعلان')
        self.assertEqual(store.user(2)['notification'],1)
        await self.send('\U0001f6e0 پنل مدیریت',uid=1)
        self.assertIn('مرکز مدیریت',self.session.calls[-1].text)

    async def test_rejection_removes_custom_entity_and_all_icon_fields(self):
        store.set_setting('emoji_alts','{"5206607081334906820":"\\ud83c\\udf82"}')
        self.session.reject_custom=True
        await self.send('/start')
        self.assertEqual(store.setting('custom_emoji'),'0')
        last=self.session.calls[-1]
        self.assertNotIn('<tg-emoji',last.text)
        self.assertIsNone(PICTOGRAPH.search(last.text))
        self.assertTrue(all(b.icon_custom_emoji_id is None for row in last.reply_markup.keyboard for b in row))

    async def test_no_regular_icons_in_bot_owned_screens(self):
        store.set_setting('custom_emoji','0')
        await self.send('/start')
        await self.send('/help')
        await self.send('/friends')
        await self.send('/setbirthday 1 5')
        await self.send(ui.BTN_UNTIL)
        for action in ('adm:home','adm:stats','adm:settings','adm:channel','adm:errors'):
            await self.callback(action)
        for method in self.session.calls:
            if getattr(method,'text',None):
                self.assertIsNone(PICTOGRAPH.search(method.text),method.text)
            markup=getattr(method,'reply_markup',None)
            rows=getattr(markup,'keyboard',None) or getattr(markup,'inline_keyboard',[]) or []
            for row in rows:
                for button in row:
                    self.assertIsNone(PICTOGRAPH.search(button.text))

    async def test_unconfigured_miniapp_hides_setup_from_users(self):
        with patch.object(config,'WEBAPP_URL',''):
            await self.send(ui.BTN_DATE_CONVERTER)
            self.assertNotIn('WEBAPP_URL',self.session.calls[-1].text)
            self.assertIsNone(self.session.calls[-1].reply_markup)
            await self.send(ui.BTN_DATE_CONVERTER,uid=1)
            self.assertIn('WEBAPP_URL',self.session.calls[-1].text)

    def test_miniapp_url_is_opened_as_a_web_app(self):
        with patch.object(config,'WEBAPP_URL','https://example.com/calendar/'):
            button=ui.date_converter_keyboard().inline_keyboard[0][0]
            self.assertEqual(button.web_app.url,config.WEBAPP_URL)
            self.assertEqual(button.style,'success')
            self.assertIsNone(button.callback_data)


if __name__=='__main__':
    unittest.main()
