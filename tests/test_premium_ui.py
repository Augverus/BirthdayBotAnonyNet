from unittest.mock import patch

from aiogram.methods import AnswerCallbackQuery, SendDocument, SendMessage
from aiogram.types import MessageEntity

import store
import ui
from tests.support import BotTestCase


class PremiumUITests(BotTestCase):
    def setUp(self):
        super().setUp()
        store.set_setting('custom_emoji', '1')
        store.set_setting('emoji_alts', '{"5206607081334906820":"🎂","5836929837381456269":"✅"}')

    def test_friends_button_is_red_with_one_premium_birthday_icon(self):
        with patch.object(store, 'user', return_value=None):
            keyboard = ui.home(7)
        button = next(button for row in keyboard.keyboard for button in row
                      if button.text == ui.BTN_FRIENDS)
        self.assertEqual(button.style, 'danger')
        self.assertEqual(button.icon_custom_emoji_id, ui.EMOJIS['birthday'])
        self.assertIsNone(ui.ORDINARY_EMOJI.search(button.text))

    def test_plain_message_becomes_html_without_interpreting_user_markup(self):
        result = ui.prepare_method(SendMessage(chat_id=1, text='🎂 <User> & hello'))
        self.assertEqual(result.parse_mode, 'HTML')
        self.assertIn('&lt;User&gt; &amp; hello', result.text)
        self.assertIn('<tg-emoji', result.text)

    def test_existing_premium_entity_is_not_nested(self):
        text = ui.emoji('birthday', '🎂') + ' <b>تولد</b> ✅'
        result = ui.premium_text(text)
        self.assertEqual(result.count('<tg-emoji'), 2)
        self.assertIn('<b>تولد</b>', result)

    def test_no_regular_fallback_when_custom_emoji_disabled(self):
        store.set_setting('custom_emoji', '0')
        self.assertEqual(ui.premium_text('🎂 تولد 🔔'), ' تولد ')
        self.assertEqual(ui.emoji('birthday', '🎂'), '')
        self.assertEqual(ui.remove_custom({'text': '<tg-emoji emoji-id="1">🎂</tg-emoji> تولد'}), {'text': 'تولد'})

    def test_buttons_and_alerts_never_have_ordinary_icons(self):
        button = ui.button('✅ تأیید', 'confirm')
        self.assertEqual(button.text, 'تأیید')
        self.assertEqual(button.icon_custom_emoji_id, ui.EMOJIS['on'])
        alert = ui.prepare_method(AnswerCallbackQuery(callback_query_id='1', text='✅ ثبت شد'))
        self.assertEqual(alert.text, 'ثبت شد')
        self.assertEqual(ui.LEGACY_LABELS['🎂 ثبت تولد'], ui.BTN_REGISTER)

    def test_existing_text_entities_preserve_formatting(self):
        result = ui.prepare_method(SendMessage(chat_id=1, text='Hello 🎂',
            entities=[MessageEntity(type='bold', offset=0, length=5)]))
        self.assertIn('<b>Hello</b>', result.text)
        self.assertIsNone(result.entities)
        self.assertIn('<tg-emoji', result.text)

    def test_document_caption_uses_premium_markup(self):
        result = ui.prepare_method(SendDocument(chat_id=1, document='file-id', caption='📁 خروجی'))
        self.assertEqual(result.parse_mode, 'HTML')
        self.assertIn('<tg-emoji', result.caption)
