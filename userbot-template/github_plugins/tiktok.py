import asyncio
from telethon import events
from config import Config

P = Config.CMD_PREFIX

def register(client):

    @client.on(events.NewMessage(outgoing=True, pattern=fr"^{P}tt\s+(https?://\S+)"))
    async def _tt_downloader(e):
        link = e.pattern_match.group(1).strip()
        target_bot = "downloader_tiktok_bot" # Botun istifadəçi adı
        
        await e.edit("⏳ Link emal edilir...")

        try:
            async with e.client.conversation(target_bot) as conv:
                # 1. Bota /start göndər
                await conv.send_message("/start")
                await asyncio.sleep(2)
                
                # 2. Linki göndər
                await conv.send_message(link)
                await asyncio.sleep(2)
                
                # 3. Botun cavabını gözlə və media (şəkil/video) tap
                # Bot bir neçə cavab göndərə bilər, ona görə sonuncunu alırıq
                media_msg = await conv.get_response()
                
                if not media_msg.media:
                    # Bəzən bot caption ilə cavab verir, media isə növbəti mesajda olur
                    media_msg = await conv.get_response()

                if media_msg.media:
                    # 4. Faylı öz chat-ımıza yönləndir və caption əlavə et
                    await e.client.send_file(
                        e.chat_id,
                        media_msg.media,
                        caption="Ryhavean Download 🪜"
                    )
                    await e.delete() # İş bitdikdən sonra .tt mesajını sil
                else:
                    await e.edit("❌ Təəssüf ki, videonu yükləmək mümkün olmadı.")

        except Exception as ex:
            await e.edit(f"❌ Xəta baş verdi: {ex}")
