"""
==================================================
🌌 Ryhavean Quotly & Sekil Plugin v3
==================================================
.q   - reply edilmiş mesajı sticker (quote) edir (QuotLyBot inline)
.sekil ad - reply edilmiş şəkli local olaraq sticker'a çevirir (PIL)
==================================================
"""
import io
import logging
import asyncio
from telethon import events
from PIL import Image

log = logging.getLogger("quotly")

try:
    from emoji_utils import apply_premium_emojis  # noqa
except Exception:
    pass


def register_quotly(bot, CMD_PREFIX="."):

    @bot.on(events.NewMessage(pattern=rf"\{CMD_PREFIX}q(?:\s|$)", outgoing=True))
    async def quote_handler(event):
        try:
            if not event.is_reply:
                await event.edit("❌ Bir mesajı reply edin.")
                return
            await event.edit("⏳ Quote hazırlanır...")
            reply = await event.get_reply_message()

            # QuotLyBot'a forward et
            await event.client.send_message("QuotLyBot", "/qsend")
            await asyncio.sleep(1)
            await event.client.forward_messages("QuotLyBot", reply)

            # Cavabı poll et
            sticker = None
            for _ in range(20):
                await asyncio.sleep(0.5)
                async for m in event.client.iter_messages("QuotLyBot", limit=3):
                    if m.sticker and m.date and (not reply.date or m.date >= reply.date):
                        sticker = m
                        break
                if sticker:
                    break

            if not sticker:
                await event.edit("❌ Quote alına bilmədi.")
                return

            await event.client.send_file(event.chat_id, sticker.media, reply_to=reply.id)
            await event.delete()
        except Exception as e:
            log.exception(".q xətası")
            try:
                await event.edit(f"❌ Xəta: {e}")
            except Exception:
                pass

    @bot.on(events.NewMessage(pattern=rf"\{CMD_PREFIX}sekil(?:\s+(.+))?$", outgoing=True))
    async def sekil_handler(event):
        try:
            args = event.pattern_match.group(1)
            if not event.is_reply:
                await event.edit(
                    "ℹ️ <b>.sekil &lt;ad&gt;</b>\n"
                    "Bir şəkli reply edib sticker'a çevirir.\n"
                    "<b>Misal:</b> .sekil mypack",
                    parse_mode="html",
                )
                return
            reply = await event.get_reply_message()
            if not (reply and reply.photo):
                await event.edit("❌ Reply edilən mesaj şəkil deyil.")
                return

            await event.edit("⏳ Sticker hazırlanır...")
            buf = io.BytesIO()
            await reply.download_media(file=buf)
            buf.seek(0)
            img = Image.open(buf).convert("RGBA")

            # Sticker 512x512 PNG, ən böyük ölçü 512
            w, h = img.size
            if w >= h:
                new_w = 512
                new_h = int(h * 512 / w)
            else:
                new_h = 512
                new_w = int(w * 512 / h)
            img = img.resize((new_w, new_h), Image.LANCZOS)

            out = io.BytesIO()
            out.name = "sticker.png"
            img.save(out, "PNG")
            out.seek(0)

            await event.client.send_file(
                event.chat_id,
                out,
                force_document=False,
                attributes=None,
                reply_to=reply.id,
            )
            await event.delete()
        except Exception as e:
            log.exception(".sekil xətası")
            try:
                await event.edit(f"❌ Xəta: {e}")
            except Exception:
                pass
