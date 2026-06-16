"""
==================================================
🌌 Ryhavean Premium Emoji Utility v3 - FIXED
==================================================
Bütün send_message / edit_message / respond / reply / send_file
metodlarına class-level monkey-patch tətbiq edir.
GitHub runtime ilə yüklənən pluginlər də avtomatik premium emoji göstərir.

✅ DÜZƏLİŞ: HTML teqlər (<b>, <code>) artıq düzgün render olunur!
==================================================
"""
import re
import random
from telethon import TelegramClient
from telethon.tl.custom import Message
from telethon.tl.types import (
    MessageEntityCustomEmoji,
    MessageEntityTextUrl,
)
from telethon.extensions import html as tl_html

# ============================================================
# Premium Emoji ID Map (150+ emoji)
# ============================================================
PREMIUM_EMOJI_MAP = {
    # Music / Audio
    "👥": 4942888689131848546,
    "🪜": 5427083257470542447,
    "🌅": 5472089304937278565,
    "🔍": 5258274739041883702,
    "🆔": 5422388085121885096,
    "🌦️": 5391055925035415864,
    "🌡️": 5839411778722729805,
    "🌬️": 6332347924063717264,
    "💬": 5296258510684712098,
    "♻️": 5377584064326804458,
    "🗑": 5372825386591732174,
    "🎮": 5319247469165433798,
    "🌐": 5456446900901262114,
    "🌌": 5364181936707216367,
    "💾": 5373342633798167891,
    "📌": 5213035264397562073,
    "🔇": 5462990730253319917,
    "🏓": 5335035652981410865,
    "🎵": 5316710964559624097,
    "🎶": 5456126169923461016,
    "🎧": 5278779535683252020,
    "🎤": 5388657954599746804,
    "🎼": 5312546813377538792,
    "👢": 5465287910691455473,
    "⏳": 5212985021870123409,
    "▪": 5445164438426507058,
    "👮": 5962906687076569235,
    "💤": 5409073806763367479,
    "⏱": 5015045170496799920,
    "📝": 5361812789797070028,
    "😎": 5332377304448382437,
    "🥳": 5460929352109661725,
    "🤩": 5271815649939712712,
    "😻": 5203909786038443975,
    "🦄": 5312093732982510667,
    "🎷": 5467793203769933478,
    "🎸": 5471947489412128060,
    "🥁": 5852466430603169101,
    "🎨": 5431456208487716895,
    "📚": 5222444124698853913,
    "🛡": 5406935230877542714,
    "👤": 5346136537123801643,
    "🧬": 5438527189240787734,
    # Status / Actions
    "✅": 5325538810275055890,
    "❌": 5436400368680450044,
    "⚠️": 5436308005408748533,
    "ℹ️": 6021618194228187816,
    "✔": 5350479625233395106,
    "❎": 4981202335737841455,
    "⛔": 5269770107340463723,
    "🚫": 5433834155785860591,
    "🆗": 5413737982333036649,
    "🆘": 5456626761246710338,
    "👏": 5843609817196794825,
    "🪨": 5253928829138785309,
    "🔢": 5287478403530767368,
    "🎱": 5136368178313561364,
    "🏳": 5467773141977670129,
    # Hearts
    "❤️": 5465514676374746733,
    "💖": 5418341487194679878,
    "💕": 5195322046174748092,
    "💗": 5206256461679724808,
    "💓": 5361857268478411449,
    "💝": 5290007284569627555,
    "💘": 5362051254971299115,
    "🧡": 5434147173002394272,
    "💛": 5345951651666615438,
    "💚": 5343881924106536026,
    "💙": 5206225752663548044,
    "💜": 5278747280478856642,
    "🖤": 5359359371333631914,
    "🤍": 5213148582814687024,
    "🤎": 5359732101480459887,
    # Faces
    "😀": 5821450070872035646,
    "🏹": 5206296361925878286,
    "💍": 5346076059689313891,
    "😍": 5465262274031659421,
    "😁": 6030394496041095796,
    "😂": 5456536919120813753,
    "🤣": 5850615733490290324,
    "😃": 5850343174865686224,
    "😄": 5204468157556733956,
    "😅": 5388650872198673917,
    "🙂": 5893406853437592859,
    "🛑": 5852974782932323756,
    "👻": 5359458146991481670,
    "💀": 5850424233783463073,
    "☠️": 5850176087752969770,
    "🤖": 5237689785425877860,
    "👽": 5188377706580342082,
    "👾": 5328150734506578613,
    "🇬🇪": 5350547232313599612,
    "⭐": 5341684837881235158,
    "🌟": 5343968167049839023,
    "✨": 5444957708765651221,
    "💫": 5469744063815102906,
    "🔥": 5212920133504212456,
    "💧": 5393512611968995988,
    "💦": 5850660345315594866,
    "☀️": 5458683354796806976,
    "🌙": 5474256979226541985,
    "⚡": 5877419533462933948,
    "❄️": 5364049247987578747,
    "🌈": 5350748331272334914,
    "☁️": 5983106326291554558,
    # Objects / Tools
    "💎": 5422555575961529062,
    "👑": 5271557007009128936,
    "🎁": 5420637379142625713,
    "🎉": 5391041468175495220,
    "🎊": 5204213715104184074,
    "🎈": 5388865049332823409,
    "💰": 5435999124245729290,
    "💵": 5291961954250794534,
    "💸": 5868527276122970322,
    "💳": 5240066289614987080,
    "🪙": 5467683093693354332,
    # Tech / Comm
    "📱": 5847950362685739628,
    "💻": 5852840084167987100,
    "⌨️": 5458569525278547985,
    "🖥️": 5334692506569288756,
    "🖱️": 5317059204802952215,
    "📷": 5197347179089392925,
    "📸": 5413628812854311979,
    "🎥": 6334554201519031929,
    "📹": 5375309569905938163,
    "📺": 5373330964372004748,
    "📡": 5413337163100083587,
    "🔋": 5248977066853943059,
    "🔌": 6332131440532129426,
    "📞": 5391192208642682468,
    "☎️": 5287324742485835162,
    "📧": 4970246557065544891,
    "📨": 5454113432284446338,
    "📩": 5472239203590888751,
    "📬": 5350421256627838238,
    "🏦": 5264895611517300926,
    "🎬": 6325351379388860506,
    "📰": 5434144690511290129,
    "🦠": 5296407803747903306,
    "💶": 5400320027758969855,
    "🌀": 5888999340818566791,
    "📐": 6334362276610443521,
    "🎴": 5341570699125355662,
    "🧠": 5319074132875295093,
    "💡": 5222253479690509955,
    "🏠": 5237952409791130101,
    "🔗": 5375129357373165375,
    "👁": 5156829295137522301,
    "🍴": 5866042019066942400,
    "📦": 5409380072291316349,
    "📛": 5215371279929976844,
    "🐙": 5267028539521114904,
    "🛰": 5467403607286502523,
    "📍": 5330088116944380969,
    "🏙": 5406686715479860449,
    "🌤": 5283075860188898177,
    "🐍": 5409076727341130651,
    "🔔": 5373136788900571050,
    "🔤": 5242615494439084286,
    "🧮": 5837157590907227857,
    "📮": 5235691513236706804,
}


def _maybe_replace_emoji(text: str):
    entities = []
    new_text = []
    i = 0
    while i < len(text):
        replaced = False
        for emoji_char, doc_id in PREMIUM_EMOJI_MAP.items():
            if text.startswith(emoji_char, i):
                offset = len("".join(new_text))
                new_text.append(emoji_char)
                entities.append(MessageEntityCustomEmoji(offset=offset, length=len(emoji_char), document_id=doc_id))
                i += len(emoji_char)
                replaced = True
                break
        if not replaced:
            new_text.append(text[i])
            i += 1
    return "".join(new_text), entities


def _inject_entities(text: str, entities=None, parse_mode=None):
    if parse_mode == "html":
        text, html_entities = tl_html.parse(text)
        base_entities = html_entities or []
    else:
        base_entities = entities or []
    new_text, emoji_entities = _maybe_replace_emoji(text)
    all_entities = list(base_entities) + emoji_entities
    all_entities.sort(key=lambda e: getattr(e, "offset", 0))
    return new_text, all_entities


async def _patched_send_message(self, entity, message='', *args, **kwargs):
    if isinstance(message, str):
        parse_mode = kwargs.get('parse_mode')
        text, entities = _inject_entities(message, kwargs.get('entities'), parse_mode)
        kwargs.pop('parse_mode', None)
        kwargs['formatting_entities'] = entities
        message = text
    return await _orig_send_message(self, entity, message, *args, **kwargs)


async def _patched_edit(self, *args, **kwargs):
    if args:
        message = args[0]
        rest = args[1:]
    else:
        message = kwargs.get('text') or kwargs.get('message') or ''
        rest = ()
    if isinstance(message, str):
        parse_mode = kwargs.get('parse_mode')
        text, entities = _inject_entities(message, kwargs.get('entities'), parse_mode)
        kwargs.pop('parse_mode', None)
        kwargs['formatting_entities'] = entities
        if args:
            args = (text, *rest)
        else:
            kwargs['text'] = text
            kwargs.pop('message', None)
    return await _orig_edit(self, *args, **kwargs)


async def _patched_respond(self, *args, **kwargs):
    if args:
        message = args[0]
        rest = args[1:]
    else:
        message = kwargs.get('message') or ''
        rest = ()
    if isinstance(message, str):
        parse_mode = kwargs.get('parse_mode')
        text, entities = _inject_entities(message, kwargs.get('entities'), parse_mode)
        kwargs.pop('parse_mode', None)
        kwargs['formatting_entities'] = entities
        if args:
            args = (text, *rest)
        else:
            kwargs['message'] = text
    return await _orig_respond(self, *args, **kwargs)


async def _patched_reply(self, *args, **kwargs):
    if args:
        message = args[0]
        rest = args[1:]
    else:
        message = kwargs.get('message') or ''
        rest = ()
    if isinstance(message, str):
        parse_mode = kwargs.get('parse_mode')
        text, entities = _inject_entities(message, kwargs.get('entities'), parse_mode)
        kwargs.pop('parse_mode', None)
        kwargs['formatting_entities'] = entities
        if args:
            args = (text, *rest)
        else:
            kwargs['message'] = text
    return await _orig_reply(self, *args, **kwargs)


_orig_send_message = TelegramClient.send_message
_orig_edit = Message.edit
_orig_respond = Message.respond
_orig_reply = Message.reply

TelegramClient.send_message = _patched_send_message
Message.edit = _patched_edit
Message.respond = _patched_respond
Message.reply = _patched_reply
