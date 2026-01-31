import asyncio
import json
import locale
import os
import queue
import random
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta

import aiohttp
import discord
import requests
import streamlit as st
from discord import app_commands
from discord.ext import commands, tasks
from discord.utils import get
from dotenv import load_dotenv

import bcv
import server
from guild import *

load_dotenv()
if "log_queue" not in st.session_state:
    st.session_state["log_queue"] = queue.Queue()

if "logs" not in st.session_state:
    st.session_state["logs"] = []

if "task_running" not in st.session_state:
    st.session_state["task_running"] = False
processed_thread = set()

DEFAULT_PAYLOAD = {
    "DT": "Windows",
    "E": None,
    "OV": "10",
    "PM": "Firefox 147.0",
    "appVersion": "",
    "lang": "en",
}


def myStyle(log_queue):
    log_queue.put(("info", "Starting process data..."))
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)
    HEADERS = []
    THREADS = []
    USERNAMES = []
    USERNAME = os.environ.get("username")
    PASSWORD = os.environ.get("password")
    ACCOUNT_NO = os.environ.get("account_no")
    MAIN_CHANNEL = os.environ.get("main_channel")
    RESULT = None

    def correctSingleQuoteJSON(s):
        rstr = ""
        escaped = False

        for c in s:
            if c == "'" and not escaped:
                c = '"'  # replace single with double quote

            elif c == "'" and escaped:
                rstr = rstr[:-1]  # remove escape character before single quotes

            elif c == '"':
                c = "\\" + c  # escape existing double quotes

            escaped = c == "\\"  # check for an escape character
            rstr += c  # append the correct json

        return rstr

    INFO = False

    @client.event
    async def on_ready():
        global INFO, DEFAULT_PAYLOAD
        # try:
        #     req = requests.get("http://localhost:8888")
        #     print(req.status_code)
        #     log_queue.put(("info", req.status_code))
        #     print("Client closed")
        #     log_queue.put(("info", "Client closed"))
        #     sys.exit("Exited")
        # except Exception as error:
        #     print(error)
        #     server.b()
        for guild in client.guilds:
            if guild.name.lower() == "phượng đỏ mega":
                RESULT = await getBasic(guild)
                stopped = False
                while not stopped:
                    result = await bcv.login(username=USERNAME, password=PASSWORD)
                    if result:
                        DEFAULT_PAYLOAD = {
                            **DEFAULT_PAYLOAD,
                            "sessionId": result["sessionId"],
                            "browserId": result["browserId"],
                            "mobileId": result["userInfo"]["mobileId"],
                            "accountType": result["userInfo"]["defaultAccountType"],
                            "user": USERNAME,
                            "clientId": result["userInfo"]["clientId"],
                            "cif": result["userInfo"]["cif"],
                        }
                        stopped = True
                    else:
                        print("trying re-login")
                    await asyncio.sleep(5)
                if not getTransVCB.is_running():
                    getTransVCB.start(guild)

    @tasks.loop(seconds=1)
    async def getTransVCB(guild):
        global processed_thread, DEFAULT_PAYLOAD, st
        print("getTransVCB is running")
        log_queue.put(("info", "getTransVCB is running"))
        if DEFAULT_PAYLOAD:
            try:
                channels = guild.channels
                basic = None
                for channel in channels:
                    if channel.name == MAIN_CHANNEL:
                        basic = channel
                if basic:
                    threads = basic.threads + [
                        thread async for thread in basic.archived_threads()
                    ]
                    applied_tags = []
                    cards = await bcv.getAccountList(DEFAULT_PAYLOAD)
                    if cards:
                        for card in cards:
                            if card["cardAccount"] == ACCOUNT_NO:
                                transactions = await bcv.transactionHistory(
                                    card["cardAccount"]
                                )
                                if transactions:
                                    for trans in transactions:
                                        posting_date = trans["tranDate"]
                                        posting_time = trans["PostingTime"]  # HHMMSS

                                        # Ghép và parse
                                        dt_str = f"{posting_date} {posting_time[:2]}:{posting_time[2:4]}:{posting_time[4:]}"
                                        dt = datetime.strptime(
                                            dt_str, "%d/%m/%Y %H:%M:%S"
                                        )
                                        timestamp = int(dt.timestamp() * 1000)
                                        sign = trans["CD"]
                                        currency = trans["curCode"]
                                        reference = trans["Reference"]
                                        description = trans["Description"]
                                        amount = trans["Amount"]
                                        threadName = f"{sign} {amount} {currency}/ {timestamp}/ {reference}/ {ACCOUNT_NO}"
                                        if threadName not in str(
                                            threads
                                        ) and threadName not in str(processed_thread):
                                            tags = basic.available_tags
                                            st = ""
                                            if sign == "+":
                                                for tag in tags:
                                                    if (
                                                        "in" in tag.name.lower()
                                                        or "chuyển đến"
                                                        in tag.name.lower()
                                                    ):
                                                        applied_tags.append(tag)
                                            else:
                                                for tag in tags:
                                                    if (
                                                        "out" in tag.name.lower()
                                                        or "chuyển đi"
                                                        in tag.name.lower()
                                                    ):
                                                        applied_tags.append(tag)
                                            allowed_mentions = discord.AllowedMentions(
                                                everyone=True
                                            )
                                            balance = "unknow"
                                            thread = await basic.create_thread(
                                                name=threadName,
                                                content="\nSố tiền: **"
                                                + amount
                                                + " "
                                                + currency
                                                + "**\nNội dung: **"
                                                + description
                                                + "**\nThời điểm: **"
                                                + f"{posting_time[:2]}:{posting_time[2:4]}:{posting_time[4:]}"
                                                + "** ngày **"
                                                + f"{posting_date}"
                                                + "**"
                                                + st
                                                + "\nSố dư hiện tại: **"
                                                + balance
                                                + " "
                                                + currency
                                                + "**\n@everyone",
                                                applied_tags=applied_tags,
                                            )
                                            if thread:
                                                processed_thread.add(threadName)

                    else:
                        stopped = False
                        while not stopped:
                            result = bcv.login(username=USERNAME, password=PASSWORD)
                            if result:
                                DEFAULT_PAYLOAD = {
                                    **DEFAULT_PAYLOAD,
                                    "sessionId": result["sessionId"],
                                    "browserId": result["browser_id"],
                                    "mobileId": result["userInfo"]["mobileId"],
                                    "accountType": result["userInfo"][
                                        "defaultAccountType"
                                    ],
                                    "user": USERNAME,
                                    "clientId": result["userInfo"]["clientId"],
                                    "cif": result["userInfo"]["cif"],
                                }
                                stopped = True
                            await asyncio.sleep(1)

            except Exception as error:
                print(error)
                log_queue.put(("error", str(error)))
                pass

    client.run(os.environ.get("botToken"))


thread = None


@st.cache_resource
def initialize_heavy_stuff():
    global thread
    log_queue = st.session_state["log_queue"]
    st1 = st
    # Đây là phần chỉ chạy ĐÚNG 1 LẦN khi server khởi động (hoặc khi cache miss)
    with st.spinner("running your scripts..."):
        thread = threading.Thread(target=myStyle, args=(log_queue,))
        thread.start()
        print(
            "Heavy initialization running..."
        )  # bạn sẽ thấy log này chỉ 1 lần trong console/cloud log

        def test():
            with st1.status("Processing...", expanded=True) as status:
                placeholder = st1.empty()
                logs = []
                while thread.is_alive() or not log_queue.empty():
                    try:
                        level, message = log_queue.get_nowait()
                        logs.append((level, message))

                        with placeholder.container():
                            for lvl, msg in logs:
                                if lvl == "info":
                                    st1.write(msg)
                                elif lvl == "success":
                                    st1.success(msg)
                                elif lvl == "error":
                                    st1.error(msg)

                        time.sleep(0.2)
                    except queue.Empty:
                        time.sleep(0.3)

                status.update(label="Hoàn thành!", state="complete", expanded=False)

        t = threading.Thread(target=test, daemon=True)
        t.start()
        return {
            "model": "loaded_successfully",
            "timestamp": time.time(),
            "db_status": "connected",
        }


# Trong phần chính của app
st.title("my style")

# Dòng này đảm bảo: chạy 1 lần duy nhất, mọi user đều dùng chung kết quả
result = initialize_heavy_stuff()

st.success("The system is ready!")
st.write("Result:")
st.json(result)
