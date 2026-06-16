import asyncio
from telethon import events
from config import Config

P = Config.CMD_PREFIX

def cmd_re(name):
    return rf"(?i)^\{P}{name}(?:\s|$)(.*)"

async def edit_safe(event, text):
    try:
        await event.edit(text)
    except:
        await event.respond(text)

def register(client):

    @client.on(events.NewMessage(outgoing=True, pattern=cmd_re("song")))
    async def _song(e):

        q = e.pattern_match.group(1).strip()
        target_bot = "KeepMediaBot"

        if not q and not e.is_reply:
            return await edit_safe(
                e,
                f"ℹ️ İstifadə: {P}song <mahnı adı> və ya audio faylına reply edin"
            )

        await edit_safe(e, "🔍 Axtarılır...")

        try:
            async with e.client.conversation(target_bot) as conv:

                # /start
                await conv.send_message("/start")
                await asyncio.sleep(3)

                if e.is_reply:

                    reply = await e.get_reply_message()

                    # Yalnız audio/musiqi reply qəbul et
                    ok = False

                    if reply.audio:
                        ok = True

                    elif reply.document:
                        mime = getattr(reply.document, "mime_type", "")
                        attrs = getattr(reply.document, "attributes", [])

                        is_audio = any(
                            attr.__class__.__name__ == "DocumentAttributeAudio"
                            for attr in attrs
                        )

                        if is_audio or mime.startswith("audio/"):
                            ok = True

                    if not ok:
                        return await edit_safe(
                            e,
                            "❌ Yalnız audio/musiqi faylına reply edin."
                        )

                    await conv.send_message(reply)
                    await asyncio.sleep(3)

                    msg = await conv.get_response()

                    if msg.buttons:
                        await msg.click(1)

                else:

                    await conv.send_message(q)
                    await asyncio.sleep(3)

                    msg = await conv.get_response()

                    if msg.buttons:
                        await msg.click(0)

                await asyncio.sleep(3)

                media_msg = None

                for _ in range(15):

                    resp = await conv.get_response()

                    if not resp.document:
                        continue

                    mime = getattr(resp.document, "mime_type", "")
                    attrs = getattr(resp.document, "attributes", [])

                    is_audio = any(
                        attr.__class__.__name__ == "DocumentAttributeAudio"
                        for attr in attrs
                    )

                    # Botdan yalnız musiqi qəbul et
                    if is_audio or mime.startswith("audio/"):
                        media_msg = resp
                        break

                if not media_msg:
                    return await edit_safe(e, "❌ Musiqi tapılmadı.")

                await e.client.send_file(
                    e.chat_id,
                    media_msg.media,
                    caption="🎵 @rveanx Download"
                )

                await e.delete()

        except Exception as ex:
            await edit_safe(e, f"❌ Xəta: {ex}")