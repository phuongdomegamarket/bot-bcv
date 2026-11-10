import asyncio
import os
import queue
import threading
import time
from datetime import datetime

import discord
import streamlit as st
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv

import bcv

load_dotenv()

# --- Cấu hình poll: chỉnh qua env, không cần sửa code ---
POLL_SECONDS = float(os.environ.get("poll_seconds", "1.0"))
SESSION_RENEW_SECONDS = float(os.environ.get("session_renew_seconds", "1500"))

USERNAME = os.environ.get("username")
PASSWORD = os.environ.get("password")
ACCOUNT_NO = os.environ.get("account_no")
MAIN_CHANNEL = os.environ.get("main_channel")

# Log queue có giới hạn, drop-oldest khi đầy -> không phình memory trên cloud
log_queue = queue.Queue(maxsize=200)

# Dedupe trong process: tên thread đã tạo. Không fetch Discord threads mỗi tick
processed_thread = set()
# Cache tag in/out sau lần đầu (bỏ quét available_tags mỗi GD)
cached_tags = {"in": None, "out": None}

# Trạng thái phiên VCB: True = session còn hạn, không phải login lại
session_ok = False
last_login_at = 0.0

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
basic_channel = None


def log(level, message):
    try:
        log_queue.put_nowait((level, message))
    except queue.Full:
        try:
            log_queue.get_nowait()  # drop bản ghi cũ nhất
        except queue.Empty:
            pass
        try:
            log_queue.put_nowait((level, message))
        except queue.Full:
            pass


async def do_login():
    """Login 1 lần; bcv.login tự cập nhật bcv.DEFAULT_PAYLOAD khi thành công."""
    try:
        result = await bcv.login(username=USERNAME, password=PASSWORD)
        return bool(result)
    except Exception as error:
        log("error", f"login error: {error}")
        return False


def find_basic(guild):
    for channel in guild.channels:
        if channel.name == MAIN_CHANNEL:
            return channel
    return None


def select_tags(basic, sign):
    """Chọn tag in/out, cache sau lần đầu."""
    key = "in" if sign == "+" else "out"
    if cached_tags[key] is None:
        tags = []
        keywords = ("in", "chuyển đến") if sign == "+" else ("out", "chuyển đi")
        for tag in basic.available_tags:
            name = tag.name.lower()
            if keywords[0] in name or keywords[1] in name:
                tags.append(tag)
        cached_tags[key] = tags
    return cached_tags[key]


def trans_key(trans):
    """Khóa dedupe + timestamp(ms) của 1 GD."""
    posting_date = trans["tranDate"]
    posting_time = trans["PostingTime"]  # HHMMSS
    dt = datetime.strptime(
        f"{posting_date} {posting_time[:2]}:{posting_time[2:4]}:{posting_time[4:]}",
        "%d/%m/%Y %H:%M:%S",
    )
    timestamp = int(dt.timestamp() * 1000)
    name = (
        f"{trans['CD']} {trans['Amount']} {trans['curCode']}/ {timestamp}/ "
        f"{trans['Reference']}/ {ACCOUNT_NO}"
    )
    return name, timestamp


async def create_thread_for_trans(basic, trans):
    name, _ = trans_key(trans)
    if name in processed_thread:
        return
    applied_tags = select_tags(basic, trans["CD"])
    pt = trans["PostingTime"]
    content = (
        f"\nSố tiền: **{trans['Amount']} {trans['curCode']}**"
        f"\nNội dung: **{trans['Description']}**"
        f"\nThời điểm: **{pt[:2]}:{pt[2:4]}:{pt[4:]}** ngày **{trans['tranDate']}**"
        "\n@everyone"
    )
    try:
        thread = await basic.create_thread(
            name=name,
            content=content,
            applied_tags=applied_tags,
            allowed_mentions=discord.AllowedMentions(everyone=True),
        )
    except Exception as error:
        log("error", f"create_thread error: {error}")
        return
    if thread:
        processed_thread.add(name)
        log("info", f"Đã tạo thread: {name}")


@tasks.loop(seconds=POLL_SECONDS)
async def getTransVCB(guild):
    global session_ok, last_login_at, basic_channel
    now = time.time()

    # 1) Session: gia hạn chủ động, không dùng while-loop block
    if not session_ok or now - last_login_at > SESSION_RENEW_SECONDS:
        session_ok = await do_login()
        last_login_at = now
        if not session_ok:
            await asyncio.sleep(4)  # fail -> thử lại sau ~5s, không dồn captcha
            return

    # 2) Forum channel: quét guild.channels đúng 1 lần rồi cache
    if basic_channel is None:
        basic_channel = find_basic(guild)
        if basic_channel is None:
            log("error", f"Không tìm thấy channel {MAIN_CHANNEL}")
            await asyncio.sleep(9)
            return

    # 3) Poll giao dịch — 3 API tuần tự trên 1 session keep-alive
    try:
        isLive = await bcv.getInsightToken(bcv.DEFAULT_PAYLOAD)
        if not isLive:
            session_ok = False
            return
        cards = await bcv.getAccountList(bcv.DEFAULT_PAYLOAD)
        if not cards:
            session_ok = False
            return
        for card in cards:
            if card["cardAccount"] == ACCOUNT_NO:
                transactions = await bcv.transactionHistory(card["cardAccount"])
                if transactions:
                    for trans in transactions:
                        await create_thread_for_trans(basic_channel, trans)
                break
    except Exception as error:
        print(error)
        log("error", str(error))


@client.event
async def on_ready():
    for guild_ in client.guilds:
        if guild_.name.lower() == "phượng đỏ mega":
            if not getTransVCB.is_running():
                getTransVCB.start(guild_)


def myStyle():
    log("info", "Starting process data...")
    max_retries = 3
    retry_delay = 30
    for attempt in range(max_retries):
        try:
            client.run(os.environ.get("botToken"))
            break
        except discord.errors.HTTPException as e:
            if e.status == 429:
                print(
                    f"Rate limited! Chờ {retry_delay}s... (lần {attempt + 1}/{max_retries})"
                )
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                raise
        except Exception as e:
            print(f"Lỗi khác: {e}")
            break


@st.cache_resource
def initialize_heavy_stuff():
    with st.spinner("running your scripts..."):
        thread = threading.Thread(target=myStyle, daemon=True)
        thread.start()
        return {
            "model": "loaded_successfully",
            "timestamp": time.time(),
            "db_status": "connected",
        }


st.title("my style")
result = initialize_heavy_stuff()
st.success("The system is ready!")
st.write("Result:")
st.json(result)
