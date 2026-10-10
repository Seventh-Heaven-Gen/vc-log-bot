"""ボイスチャンネルの入退室を、テキストチャンネルに書き出して、VCで読み上げるBot。"""

import asyncio
import io
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import discord
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
LOG_CHANNEL_NAME = os.getenv("LOG_CHANNEL_NAME", "vcログ").strip().lstrip("#")
SPEAK = os.getenv("SPEAK", "on").strip().lower() not in ("off", "0", "false", "no")
SPEAK_NAME_MAX = int(os.getenv("SPEAK_NAME_MAX", "10"))
JST = timezone(timedelta(hours=9))

intents = discord.Intents.none()
intents.guilds = True
intents.voice_states = True

client = discord.Client(intents=intents)

# サーバーごとに1本ずつ。接続・移動・読み上げが同時に走らないようにする
voice_locks: dict[int, asyncio.Lock] = {}


# ---------- テキストのログ ----------

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


# ---------- 読み上げ ----------

# Windows標準の日本語音声で、Discordにそのまま流せる形式(48kHz/16bit/ステレオ)のWAVを作る。
# 読む文字列は環境変数で渡す（コマンドに埋め込まないので、名前に記号があっても壊れない）
TTS_SCRIPT = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$ja = $s.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -eq 'ja-JP' } | Select-Object -First 1
if ($ja) { $s.SelectVoice($ja.VoiceInfo.Name) }
$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(48000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Stereo)
$s.SetOutputToWaveFile($env:TTS_OUT, $f)
$s.Speak($env:TTS_TEXT)
$s.Dispose()
"""


def wav_to_pcm(data: bytes) -> bytes:
    """WAVのヘッダーを外して、中の音声データだけ取り出す。"""
    pos = 12
    while pos + 8 <= len(data):
        chunk_id = data[pos:pos + 4]
        size = int.from_bytes(data[pos + 4:pos + 8], "little")
        if chunk_id == b"data":
            return data[pos + 8:pos + 8 + size]
        pos += 8 + size + (size & 1)
    raise ValueError("WAVに音声データが見つからない")


async def synthesize(text: str) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "tts.wav"
        env = {**os.environ, "TTS_TEXT": text, "TTS_OUT": str(out)}
        proc = await asyncio.create_subprocess_exec(
            "powershell", "-NoProfile", "-NonInteractive", "-Command", TTS_SCRIPT,
            env=env, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0 or not out.exists():
            raise RuntimeError(err.decode(errors="replace").strip() or "音声を作れなかった")
        return wav_to_pcm(out.read_bytes())


async def say(vc: discord.VoiceClient, text: str) -> None:
    try:
        pcm = await synthesize(text)
    except Exception as e:
        print(f"読み上げ失敗: {text} ({e})")
        return
    if not vc.is_connected():
        return
    done = asyncio.Event()
    loop = asyncio.get_running_loop()
    vc.play(discord.PCMAudio(io.BytesIO(pcm)), after=lambda _: loop.call_soon_threadsafe(done.set))
    await done.wait()


def spoken_name(member: discord.Member) -> str:
    return member.display_name[:SPEAK_NAME_MAX]


def humans_in(channel: discord.VoiceChannel | discord.StageChannel) -> int:
    count = 0
    for user_id in channel.voice_states:
        m = channel.guild.get_member(user_id)
        if m is None or not m.bot:
            count += 1
    return count


def busiest_channel(guild: discord.Guild):
    """人がいるVCのうち、一番人数が多いところ。誰もいなければ None。"""
    channels = [c for c in guild.voice_channels if humans_in(c) > 0]
    return max(channels, key=humans_in, default=None)


async def handle_voice(member: discord.Member, before, after) -> None:
    guild = member.guild
    async with voice_locks.setdefault(guild.id, asyncio.Lock()):
        vc = guild.voice_client
        name = spoken_name(member)

        # 退室（移動の「前」も含む）
        if before.channel is not None and vc and vc.channel == before.channel:
            if humans_in(before.channel) == 0:
                # 誰もいなくなったら抜ける。別のVCに人がいればそっちへ移る
                next_ch = busiest_channel(guild)
                if next_ch is None:
                    await vc.disconnect()
                    return
                await vc.move_to(next_ch)
            else:
                await say(vc, f"{name}さん退室")

        # 入室（移動の「後」も含む）
        if after.channel is not None:
            vc = guild.voice_client
            if vc is None or not vc.is_connected():
                try:
                    vc = await after.channel.connect(self_deaf=True)
                except Exception as e:
                    print(f"[{guild.name}] VCに入れなかった: {e}")
                    return
            elif vc.channel != after.channel and humans_in(vc.channel) == 0:
                await vc.move_to(after.channel)
            if vc.channel == after.channel:
                await say(vc, f"{name}さん入室")


# ---------- イベント ----------

@client.event
async def on_ready() -> None:
    print(f"ログイン完了: {client.user}（ログの出し先: #{LOG_CHANNEL_NAME}、読み上げ: {'オン' if SPEAK else 'オフ'}）")
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
    # このBot自身の出入りは記録しない
    if client.user and member.id == client.user.id:
        return

    now = datetime.now(JST).strftime("%m/%d %H:%M")
    name = discord.utils.escape_markdown(member.display_name)

    # チャンネル移動は「前のVCから退室」と「次のVCに入室」の2行で出す
    if before.channel is not None:
        await post(member.guild, f"`{now}` 🔴 **{name}** が {before.channel.mention} から退室")
    if after.channel is not None:
        await post(member.guild, f"`{now}` 🟢 **{name}** が {after.channel.mention} に入室")

    # 他のBot（音楽Botなど）の出入りは読み上げない
    if SPEAK and not member.bot:
        await handle_voice(member, before, after)


if __name__ == "__main__":
    if not TOKEN or TOKEN == "ここにトークンを貼る":
        raise SystemExit(".env の DISCORD_TOKEN が空です。README の手順でトークンを貼ってください。")
    client.run(TOKEN)
