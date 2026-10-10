"""ボイスチャンネルの入退室を、指定したテキストチャンネルに書き出すBot。"""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import discord
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
LOG_CHANNEL_NAME = os.getenv("LOG_CHANNEL_NAME", "vcログ").strip().lstrip("#")
JST = timezone(timedelta(hours=9))

intents = discord.Intents.none()
intents.guilds = True
intents.voice_states = True

client = discord.Client(intents=intents)


def find_log_channel(guild: discord.Guild) -> discord.TextChannel | None:
    return discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)


async def post(guild: discord.Guild, text: str) -> None:
    channel = find_log_channel(guild)
    if channel is None:
        print(f"[{guild.name}] #{LOG_CHANNEL_NAME} が見つからないのでスキップ: {text}")
        return
    try:
        await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
    except discord.Forbidden:
        print(f"[{guild.name}] #{LOG_CHANNEL_NAME} に書き込む権限がない: {text}")


@client.event
async def on_ready() -> None:
    print(f"ログイン完了: {client.user}（ログの出し先: #{LOG_CHANNEL_NAME}）")
    for guild in client.guilds:
        status = "OK" if find_log_channel(guild) else "チャンネルなし"
        print(f"  - {guild.name}: #{LOG_CHANNEL_NAME} {status}")


@client.event
async def on_voice_state_update(
    member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
) -> None:
    # ミュートや画面共有の切り替えでも呼ばれるので、チャンネルが変わった時だけ拾う
    if before.channel == after.channel:
        return

    now = datetime.now(JST).strftime("%m/%d %H:%M")
    name = discord.utils.escape_markdown(member.display_name)

    # チャンネル移動は「前のVCから退室」と「次のVCに入室」の2行で出す
    if before.channel is not None:
        await post(member.guild, f"`{now}` 🔴 **{name}** が {before.channel.mention} から退室")
    if after.channel is not None:
        await post(member.guild, f"`{now}` 🟢 **{name}** が {after.channel.mention} に入室")


if __name__ == "__main__":
    if not TOKEN or TOKEN == "ここにトークンを貼る":
        raise SystemExit(".env の DISCORD_TOKEN が空です。README の手順でトークンを貼ってください。")
    client.run(TOKEN)
