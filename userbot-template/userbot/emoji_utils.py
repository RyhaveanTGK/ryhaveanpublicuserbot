"""
==================================================
🌌 Ryhavean Premium Emoji Utility v3 - FIXED
==================================================
Bütün send_message / edit_message / respond / reply / send_file
metodlarına class-level monkey-patch tətbiq edir.
.pinstall ilə yüklənən pluginlər də avtomatik premium emoji göstərir.

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
    "🦅": 5413424754663122711,
    "🛑": 5945046460713145197,
    "⛔️": 5316653661105961462,
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
    "💞": 5292009027092378537,
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
    "💵": 5850605794935969315,
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
    "💵": 5291961954250794534,
    "🌀": 5888999340818566791,
    "📐": 6334362276610443521,
    "🎴": 5341570699125355662,
    "🧠": 5319074132875295093,
    "💡": 5222253479690509955,
    "📧": 4970246557065544891,
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
    # Navigation
    "➡️": 6037622221625626773,
    "⬅️": 6039539366177541657,
    "⬆️": 5963103826075456248,
    "⬇️": 6039802767931871481,
    "↗️": 5422706058730675684,
    "↘️": 6035353688619356485,
    "↙️": 5260260723329608328,
    "↖️": 5190779220611066696,
    "🔄": 6030657343744644592,
    "🔁": 5346269127059196142,
    "🔂": 5346269127059196142,
    # Tools / Settings
    "⚙️": 5393199882515277922,
    "🛠️": 5863945989127148135,
    "🔧": 5258023599419171861,
    "🔨": 5456312597273923475,
    "🔒": 5393302369024882368,
    "🔓": 5393302369024882368,
    "🔑": 5836690092306992715,
    "🗝️": 5836690092306992715,
    # Files / Docs
    "📁": 5298853345241358103,
    "📂": 5298853345241358103,
    "📄": 5411334681842966198,
    "📃": 5370604433233177619,
    "📑": 5251632825521696687,
    "📊": 5028325978175177540,
    "📈": 5244837092042750681,
    "📉": 5301037284571759350,
    "🗂️": 5298853345241358103,
    "📋": 5197269100878907942,
    "📝": 5215672443036772796,
    "✏️": 6273749645134925942,
    "🖊️": 5334673106202010226,
    "🖋️": 5389057773105328621,
    "📤": 5433614747381538714,
    "📖": 5319135825785529051,
    "🎭": 5276157818926300661,
    "🎌": 5431538972507522948,
    
    # Misc
    "🌍": 5465166522030764559,
    "🌎": 5465166522030764559,
    "🌏": 5465166522030764559,
    "🗺️": 5388916717789393938,
    "🧭": 5433825729060018456,
    "⏰": 5188377706580342082,
    "⏱️": 5195352914104694560,
    "⏲️": 5359535585251838264,
    "🕐": 5348236797606379943,
    "📅": 5265168676948035250,
    "📆": 5265168676948035250,
    "🗓️": 5265168676948035250,
    "🏳️‍🌈": 5850532823441607662,
    "🇦🇿": 5224542095963859210,
    "🇷🇺": 5398017006165305287,
}

# .song üçün random premium emoji ID'lər
SONG_PREMIUM_EMOJI_IDS = [
    5244489483159609086,  # 🎵
    5411371652921435502,  # 🎶
    5363988860747400777,  # 🎧
]
SONG_EMOJI_CHAR = ["🎵", "🎶", "🎧"]


# ============================================================
# Premium Emoji konvertasiya alqoritmi (DÜZƏLDILMIŞ)
# ============================================================
def _build_premium_emoji_entities(text: str, html_entities: list):
    """
    Parse olunmuş text üzərində premium emoji entity-lər yaradır.
    HTML entities ilə qarışdırmır.
    """
    if not text:
        return []
    
    sorted_emojis = sorted(PREMIUM_EMOJI_MAP.keys(), key=len, reverse=True)
    pattern = "|".join(re.escape(e) for e in sorted_emojis)
    
    def utf16_len(s):
        return len(s.encode("utf-16-le")) // 2

    emoji_entities = []
    
    for m in re.finditer(pattern, text):
        emoji_char = m.group(0)
        emoji_id = PREMIUM_EMOJI_MAP.get(emoji_char)
        if not emoji_id:
            continue
        
        offset = utf16_len(text[: m.start()])
        length = utf16_len(emoji_char)
        
        # Yoxla ki, bu offset artıq HTML entity tərəfindən tutulmayıb
        is_overlap = False
        for ent in html_entities:
            ent_start = ent.offset
            ent_end = ent.offset + ent.length
            if offset < ent_end and (offset + length) > ent_start:
                is_overlap = True
                break
        
        if not is_overlap:
            emoji_entities.append(
                MessageEntityCustomEmoji(
                    offset=offset,
                    length=length,
                    document_id=emoji_id,
                )
            )
    
    return emoji_entities


def apply_premium_emojis(text, existing_entities=None, parse_mode=None):
    """
    HTML teqlərini parse edib, premium emoji entity-ləri əlavə edir.
    
    Args:
        text: Mesaj mətni (HTML teqləri ola bilər)
        existing_entities: Artıq mövcud entity-lər
        parse_mode: 'html' və ya None
    
    Returns:
        (parsed_text, combined_entities)
    """
    if not text:
        return text, existing_entities or []
    
    # Əgər parse_mode='html' varsa, HTML-i parse edirik
    html_entities = []
    parsed_text = text
    
    if parse_mode == 'html' or (not existing_entities and '<' in text):
        try:
            # Telethon-un HTML parser-i istifadə et
            parsed_text, html_entities = tl_html.parse(text)
        except Exception:
            # Parse xətası olarsa, sadəcə text-i saxla
            parsed_text = text
            html_entities = []
    
    # Artıq entity-lər varsa, onları əlavə et
    if existing_entities:
        html_entities = list(existing_entities) + html_entities
    
    # İndi premium emoji entity-lər əlavə et
    emoji_entities = _build_premium_emoji_entities(parsed_text, html_entities)
    
    # Bütün entity-ləri birləşdir
    all_entities = html_entities + emoji_entities
    
    return parsed_text, all_entities


# ============================================================
# CLASS-LEVEL MONKEY PATCH (DÜZƏLDILMIŞ)
# ============================================================
_original_send_message = TelegramClient.send_message
_original_edit_message = TelegramClient.edit_message
_original_send_file = TelegramClient.send_file

async def _patched_send_message(self, entity, message=None, *args, **kwargs):
    if isinstance(message, str):
        parse_mode = kwargs.get("parse_mode")
        existing_ents = kwargs.get("formatting_entities")
        
        new_text, combined_ents = apply_premium_emojis(
            message, 
            existing_ents, 
            parse_mode
        )
        
        if combined_ents:
            kwargs["formatting_entities"] = combined_ents
            kwargs.pop("parse_mode", None)  # parse_mode-u silirik
            message = new_text
    
    return await _original_send_message(self, entity, message, *args, **kwargs)

async def _patched_edit_message(self, entity, message=None, text=None, *args, **kwargs):
    target_text = text if text else message
    
    if isinstance(target_text, str):
        parse_mode = kwargs.get("parse_mode")
        existing_ents = kwargs.get("formatting_entities")
        
        new_text, combined_ents = apply_premium_emojis(
            target_text,
            existing_ents,
            parse_mode
        )
        
        if combined_ents:
            kwargs["formatting_entities"] = combined_ents
            kwargs.pop("parse_mode", None)
            if text:
                text = new_text
            else:
                message = new_text
    
    return await _original_edit_message(self, entity, message, text, *args, **kwargs)

async def _patched_send_file(self, entity, file, *args, **kwargs):
    caption = kwargs.get("caption")
    
    if isinstance(caption, str):
        parse_mode = kwargs.get("parse_mode")
        existing_ents = kwargs.get("formatting_entities")
        
        new_text, combined_ents = apply_premium_emojis(
            caption,
            existing_ents,
            parse_mode
        )
        
        if combined_ents:
            kwargs["formatting_entities"] = combined_ents
            kwargs.pop("parse_mode", None)
            kwargs["caption"] = new_text
    
    return await _original_send_file(self, entity, file, *args, **kwargs)

_original_message_edit = Message.edit
_original_message_respond = Message.respond
_original_message_reply = Message.reply

async def _patched_message_edit(self, text=None, *args, **kwargs):
    if isinstance(text, str):
        parse_mode = kwargs.get("parse_mode")
        existing_ents = kwargs.get("formatting_entities")
        
        new_text, combined_ents = apply_premium_emojis(
            text,
            existing_ents,
            parse_mode
        )
        
        if combined_ents:
            kwargs["formatting_entities"] = combined_ents
            kwargs.pop("parse_mode", None)
            text = new_text
    
    return await _original_message_edit(self, text, *args, **kwargs)

async def _patched_message_respond(self, message=None, *args, **kwargs):
    if isinstance(message, str):
        parse_mode = kwargs.get("parse_mode")
        existing_ents = kwargs.get("formatting_entities")
        
        new_text, combined_ents = apply_premium_emojis(
            message,
            existing_ents,
            parse_mode
        )
        
        if combined_ents:
            kwargs["formatting_entities"] = combined_ents
            kwargs.pop("parse_mode", None)
            message = new_text
    
    return await _original_message_respond(self, message, *args, **kwargs)

async def _patched_message_reply(self, message=None, *args, **kwargs):
    if isinstance(message, str):
        parse_mode = kwargs.get("parse_mode")
        existing_ents = kwargs.get("formatting_entities")
        
        new_text, combined_ents = apply_premium_emojis(
            message,
            existing_ents,
            parse_mode
        )
        
        if combined_ents:
            kwargs["formatting_entities"] = combined_ents
            kwargs.pop("parse_mode", None)
            message = new_text
    
    return await _original_message_reply(self, message, *args, **kwargs)

def install_patches():
    TelegramClient.send_message = _patched_send_message
    TelegramClient.edit_message = _patched_edit_message
    TelegramClient.send_file = _patched_send_file
    Message.edit = _patched_message_edit
    Message.respond = _patched_message_respond
    Message.reply = _patched_message_reply

def vip_format(text: str, auto_bold: bool = True) -> str:
    parsed_text, _ = apply_premium_emojis(text, parse_mode='html')
    return parsed_text

install_patches()
