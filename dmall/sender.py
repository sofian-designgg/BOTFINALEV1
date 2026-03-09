"""
Envoi DM All avec protection anti-rate-limit Discord
- Délai aléatoire entre chaque DM (3-6s) pour éviter la détection
- Retry avec backoff en cas de rate limit (429)
"""
import asyncio
import random
import discord


DM_DELAY_MIN = 3.0
DM_DELAY_MAX = 6.0
RATE_LIMIT_WAIT = 60


async def send_dm_all(members: list, message: str, on_progress=None) -> tuple[int, int]:
    """
    Envoie un DM à chaque membre avec anti-rate-limit.
    Retourne (succès, échecs).
    on_progress(current, total, success, failed, extra_msg) pour les mises à jour.
    """
    success = 0
    failed = 0
    to_send = message[:2000]
    total = len(members)

    for i, member in enumerate(members):
        for attempt in range(3):
            try:
                dm_channel = member.dm_channel or await member.create_dm()
                await dm_channel.send(to_send)
                success += 1
                break
            except discord.Forbidden:
                failed += 1
                break
            except discord.HTTPException as e:
                if getattr(e, 'status', 0) == 429 and attempt < 2:
                    wait = RATE_LIMIT_WAIT + random.uniform(0, 30)
                    if on_progress:
                        await on_progress(i + 1, total, success, failed, f"Rate limit, attente {int(wait)}s")
                    await asyncio.sleep(wait)
                else:
                    failed += 1
                    break
            except Exception:
                if attempt < 2:
                    await asyncio.sleep(15)
                else:
                    failed += 1
                    break

        if on_progress:
            await on_progress(i + 1, total, success, failed, None)

        if i < total - 1:
            delay = random.uniform(DM_DELAY_MIN, DM_DELAY_MAX)
            await asyncio.sleep(delay)

    return success, failed
