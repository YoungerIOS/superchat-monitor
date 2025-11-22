#!/usr/bin/env python3
"""
multi_room_monitor_playwright.py

使用 Playwright 自动获取 uniq + cookie，异步轮询多个房间 /chat 接口，
长期稳定监控高额打赏。

依赖:
  pip install playwright aiohttp requests
  python -m playwright install chromium
"""

import asyncio, re, os, time, json
from datetime import datetime, timedelta, timezone
from typing import Dict, Any
from aiohttp_socks import ProxyConnector
import aiohttp
import requests
from playwright.sync_api import sync_playwright
from nicegui import ui, app

PROXY = "socks5://127.0.0.1:10808"  # v2rayN 的本地 SOCKS5 代理端口

# ---------- 配置区 ----------
STREAMERS_FILE = "streamers.json"

# 数据持久化函数
def load_streamers():
    """从文件加载主播列表（字典格式）"""
    global STREAMERS
    try:
        if os.path.exists(STREAMERS_FILE):
            with open(STREAMERS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict) and "streamers" in data:
                    STREAMERS = data["streamers"]
                    # 确保所有元素都是字典格式，并确保有必要的键
                    for s in STREAMERS:
                        if not isinstance(s, dict):
                            s = {"username": str(s)}
                        if "running" not in s:
                            s["running"] = False
                        # 初始化配置字段
                        if "threshold" not in s:
                            s["threshold"] = 30.0  # 默认阈值
                        if "menu_items" not in s:
                            s["menu_items"] = []  # 完整菜单项列表
                        if "selected_menu_items" not in s:
                            s["selected_menu_items"] = []  # 选中的菜单项
                else:
                    STREAMERS = []
        else:
            STREAMERS = []
            save_streamers()
    except Exception as e:
        print(f"加载主播列表失败: {e}")
        STREAMERS = []

def save_streamers():
    """保存主播列表到文件（字典格式）"""
    try:
        with open(STREAMERS_FILE, 'w', encoding='utf-8') as f:
            json.dump({"streamers": STREAMERS}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存主播列表失败: {e}")

def get_streamer_username(streamer):
    """获取主播用户名"""
    if isinstance(streamer, dict):
        return streamer.get("username", "")
    return ""

def find_streamer_by_username(username):
    """根据用户名查找主播字典，返回索引和字典"""
    for idx, streamer in enumerate(STREAMERS):
        if get_streamer_username(streamer) == username:
            return idx, streamer
    return None, None

def get_streamer_running(username):
    """获取主播的 running 状态"""
    _, streamer = find_streamer_by_username(username)
    if streamer:
        return streamer.get("running", False)
    return False

def set_streamer_running(username, running):
    """设置主播的 running 状态并保存"""
    idx, streamer = find_streamer_by_username(username)
    if streamer is not None:
        streamer["running"] = running
        save_streamers()

def get_streamer_threshold(username):
    """获取主播的打赏金额提醒阈值"""
    _, streamer = find_streamer_by_username(username)
    if streamer:
        return streamer.get("threshold", 30.0)
    return 30.0

def set_streamer_threshold(username, threshold):
    """设置主播的打赏金额提醒阈值并保存"""
    idx, streamer = find_streamer_by_username(username)
    if streamer is not None:
        try:
            streamer["threshold"] = float(threshold)
            save_streamers()
        except (ValueError, TypeError):
            pass

def get_streamer_menu_items(username):
    """获取主播的完整菜单项列表"""
    _, streamer = find_streamer_by_username(username)
    if streamer:
        return streamer.get("menu_items", [])
    return []

def set_streamer_menu_items(username, menu_items):
    """设置主播的完整菜单项列表并保存"""
    idx, streamer = find_streamer_by_username(username)
    if streamer is not None:
        streamer["menu_items"] = menu_items
        save_streamers()

def get_streamer_selected_menu_items(username):
    """获取主播的选中菜单项列表"""
    _, streamer = find_streamer_by_username(username)
    if streamer:
        return streamer.get("selected_menu_items", [])
    return []

def set_streamer_selected_menu_items(username, selected_items):
    """设置主播的选中菜单项列表并保存"""
    idx, streamer = find_streamer_by_username(username)
    if streamer is not None:
        streamer["selected_menu_items"] = selected_items
        save_streamers()

def update_streamer_username(old_username: str, new_username: str):
    """更新主播的用户名并保存，同时更新UI绑定"""
    idx, streamer = find_streamer_by_username(old_username)
    if streamer is not None:
        streamer["username"] = new_username
        save_streamers()
        print(f"[系统] 已更新用户名: {old_username} -> {new_username}")
        
        # 更新 UI_BINDINGS 的键名（从旧用户名改为新用户名）
        if old_username in UI_BINDINGS:
            widgets = UI_BINDINGS.pop(old_username)
            UI_BINDINGS[new_username] = widgets
            # 更新名称显示
            if "name" in widgets:
                try:
                    widgets["name"].text = new_username
                except Exception as e:
                    print(f"[系统] 更新UI名称显示失败: {e}")
            print(f"[系统] 已更新UI绑定: {old_username} -> {new_username}")
        
        return True
    return False

# 初始化加载
load_streamers()
THRESHOLD = 30.0
POLL_INTERVAL = 5        # 轮询间隔（直播中）
OFFLINE_POLL_INTERVAL = 600  # 已下播后的低频轮询间隔（10分钟 = 600秒）
REFRESH_UNIQ_INTERVAL = 60 # 每多少秒强制刷新一次 uniq（避免长连接失效）
ONLINE_CHECK_INTERVAL = 180  # 直播中轮询suggestion API的检查间隔（3分钟），用于及时检测下播
VERBOSE = True

# Telegram 推送（环境变量或直接写在这里）
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN","")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID","")

# --------------------------------

# 用于存放每个主播的运行时信息 (uniq, cookies)
ROOM_STATE: Dict[str, Dict[str, Any]] = {}
RUNNING_TASKS: Dict[str, asyncio.Task] = {}
ASYNC_SESSION: aiohttp.ClientSession | None = None

# UI 状态
DELETE_MODE = False
SELECTED_STREAMERS: set = set()
STREAMERS_CONTAINER = None  # 用于动态更新列表
PENDING_BROWSER_NOTIFICATIONS: list[tuple[str, str]] = []  # (title, body)

# ---------- helpers ----------
def extract_uniq_from_html(username: str, html: str) -> str | None:
    """从主播主页 HTML 中提取 uniq"""
    # 尝试多种可能的 pattern（大小写/下划线/短横）
    patterns = [
        rf'/api/front/v2/models/username/{re.escape(username)}/chat\?source=regular&uniq=([a-z0-9]+)',
        rf'chat\?source=regular&uniq=([a-z0-9]+)'  # 更宽松的匹配
    ]
    for p in patterns:
        m = re.search(p, html, re.IGNORECASE)
        if m:
            return m.group(1)
    return None

def notify_print_and_telegram(text: str):
    print(text)
    # Correct Telegram send endpoint
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=10)
        except Exception as e:
            print("Telegram 发送失败:", e)

def browser_notify(title: str, body: str):
    """将通知加入队列，由前端上下文的 UI 定时器统一发送系统通知。"""
    try:
        PENDING_BROWSER_NOTIFICATIONS.append((str(title), str(body)))
    except Exception:
        pass

# ---------- Playwright helpers (同步 API used in dedicated thread) ----------
# 替换用的 fetch_page_uniq_and_cookies（同步，供 run_in_executor 使用）
def fetch_page_uniq_and_cookies(username: str, headless: bool = True, nav_timeout: int = 30000, watch_time: int = 8000):
    """
    用 Playwright 打开主播主页，监听网络请求以捕获 '/chat?source=regular&uniq=...' 的请求。
    返回 (uniq_or_None, cookies_dict, user_agent, html_or_error).
    - nav_timeout: 页面导航超时时间（毫秒）
    - watch_time: 在页面加载后继续监听网络请求的时间（毫秒）
    """
    from playwright.sync_api import sync_playwright
    home = f"https://zh.superchat.live/{username}"
    print(f"[Playwright] 打开页面获取 uniq: {home} (nav_timeout={nav_timeout}ms, watch_time={watch_time}ms)")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context()
            page = context.new_page()

            found = {"url": None}

            # 回调：记录所有请求 URL，查找匹配的 chat 请求
            def on_request(req):
                try:
                    url = req.url
                    if "/api/front/v2/models/username/" in url and "chat?source=regular" in url:
                        # 记录第一个命中的 URL
                        if not found["url"]:
                            found["url"] = url
                            print(f"[Playwright] 捕获到 chat 请求 URL: {url}")
                except Exception:
                    pass

            page.on("request", on_request)

            # 导航并等待基本加载
            page.goto(home, timeout=nav_timeout)
            # 等待 networkidle，之后再继续监听一段时间（以便捕获动态 XHR）
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                # networkidle 可能超时，但不用失败，继续监听
                pass

            # 继续监听短时间以捕获稍后发起的请求（例如异步 XHR）
            # watch_time 毫秒
            if watch_time > 0:
                page.wait_for_timeout(watch_time)

            # 如果在请求监听期间捕获到 URL，直接解析 uniq 和实际用户名
            uniq = None
            api_url = None
            actual_username = None
            if found["url"]:
                import urllib.parse as up
                parsed = up.urlparse(found["url"])
                # 从 URL 路径中提取实际用户名：/api/front/v2/models/username/{actual_username}/chat
                path_parts = parsed.path.split('/')
                try:
                    username_idx = path_parts.index('username')
                    if username_idx >= 0 and username_idx + 1 < len(path_parts):
                        actual_username = path_parts[username_idx + 1]
                except ValueError:
                    pass
                
                qs = up.parse_qs(parsed.query)
                uvals = qs.get("uniq") or qs.get("uniq[]") or []
                if uvals:
                    uniq = uvals[0]
                    api_url = found["url"]
                else:
                    # 如果没有 query parse 到 uniq，尝试用正则提取
                    m = re.search(r"uniq=([a-z0-9]+)", found["url"], re.IGNORECASE)
                    if m:
                        uniq = m.group(1)
                        api_url = found["url"]

            # 如果没在请求中找到，再回退到页面 HTML 中查找
            html = page.content()
            if not uniq:
                m2 = re.search(
                    rf'/api/front/v2/models/username/{re.escape(username)}/chat\?source=regular&uniq=([a-z0-9]+)',
                    html, flags=re.IGNORECASE)
                if m2:
                    uniq = m2.group(1)
                    api_url = f"https://zh.superchat.live/api/front/v2/models/username/{username}/chat?source=regular&uniq={uniq}"
                    print(f"[Playwright] 在 HTML 中提取到 uniq={uniq}")

            # 导出 cookie 与 UA
            cookies = context.cookies()
            cookie_dict = {c['name']: c['value'] for c in cookies}
            try:
                ua = page.evaluate("() => navigator.userAgent")
            except Exception:
                ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36"
            
            browser.close()

            if uniq:
                print(f"[Playwright] 成功获取 uniq={uniq}，cookies_keys={list(cookie_dict.keys())}")
                if actual_username and actual_username != username:
                    print(f"[Playwright] ⚠️ 检测到用户名变更: {username} -> {actual_username}")
            else:
                print(f"[Playwright] 未提取到 uniq（network requests 和 HTML 均无），已抓取 {len(cookie_dict)} 个 cookie")

            return uniq, cookie_dict, ua, html, actual_username

    except Exception as e:
        err = f"ERROR in playwright fetch: {e}"
        print(err)
        return None, {}, "", err, None


# ---------- 从DOM元素结构提取菜单信息（使用Playwright） ----------
def extract_menu_from_dom(username: str, headless: bool = True, nav_timeout: int = 30000) -> Dict[str, Any]:
    """
    使用 Playwright 提取主播的小费菜单。
    步骤：
      1. 打开页面并尝试触发“完整菜单/小费选单”入口；
      2. 首先尝试旧版 table 结构；
      3. 如无 table，再扫描包含“代币/token”关键词的卡片式 DOM 列表。
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    home = f"https://zh.superchat.live/{username}"
    result = {"menu_items": [], "detailed_items": [], "error": None}
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context()
            page = context.new_page()
            
            try:
                page.goto(home, timeout=nav_timeout)
            except PlaywrightTimeoutError:
                error_msg = f"页面加载超时（{nav_timeout/1000}秒），请检查网络连接或稍后重试"
                result["error"] = error_msg
                print(f"[{username}] {error_msg}")
                browser.close()
                return result
            except Exception as e:
                error_msg = f"页面加载失败: {str(e)}"
                result["error"] = error_msg
                print(f"[{username}] {error_msg}")
                browser.close()
                return result
            
            # 等待页面加载
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except:
                pass
            page.wait_for_timeout(2000)

            def _click_by_keywords(keywords, description: str) -> bool:
                for text in keywords:
                    try:
                        locator = page.get_by_text(text, exact=False)
                        if locator.count() > 0:
                            target = locator.first
                            target.scroll_into_view_if_needed()
                            target.click()
                            print(f"[{username}] 已点击 {description}: {text}")
                            return True
                    except Exception:
                        continue
                return False

            def _click_by_selector(selector: str, description: str) -> bool:
                try:
                    locator = page.locator(selector)
                    if locator.count() > 0:
                        locator.first.scroll_into_view_if_needed()
                        locator.first.click()
                        print(f"[{username}] 已通过选择器点击 {description}: {selector}")
                        return True
                except Exception as e:
                    print(f"[{username}] 选择器 {selector} 点击失败: {e}")
                return False

            # 尝试展开“完整小费菜单”按钮
            try:
                full_menu_clicked = _click_by_keywords(
                    ["完整小费菜单", "完整菜单", "完整", "Full menu", "Full tip menu", "Show full"],
                    "完整菜单按钮"
                )
                if full_menu_clicked:
                    page.wait_for_timeout(3000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=5000)
                    except:
                        pass
                    page.wait_for_timeout(1500)
            except Exception as e:
                print(f"[{username}] 点击完整菜单按钮时出错: {e}")

            # 点击“发送小费”按钮（可直接唤起菜单抽屉）
            try:
                # 若存在遮罩(如访客协议)，先尝试关闭
                def close_overlays():
                    selectors = [
                        "div.full-cover.modal-wrapper button",
                        "div#agreement-root button",
                        "button:has-text('接受')",
                        "button:has-text('同意')",
                        "button:has-text('Accept')"
                    ]
                    for sel in selectors:
                        try:
                            overlay_btn = page.locator(sel)
                            if overlay_btn.count() > 0:
                                overlay_btn.first.click()
                                page.wait_for_timeout(500)
                        except Exception:
                            continue

                close_overlays()

                send_tip_clicked = _click_by_keywords(
                    ["发送小费", "Send tip", "Send Tip"],
                    "发送小费按钮"
                )
                if not send_tip_clicked:
                    send_tip_clicked = _click_by_selector(
                        'button.send-tip-btn, button:has-text("发送小费"), button:has-text("Send tip")',
                        "发送小费按钮"
                    )
                if not send_tip_clicked:
                    close_overlays()
                    send_tip_clicked = _click_by_selector(
                        'button.send-tip-btn, button:has-text("发送小费"), button:has-text("Send tip")',
                        "发送小费按钮"
                    )
                if send_tip_clicked:
                    page.wait_for_timeout(2000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=5000)
                    except:
                        pass
                    page.wait_for_timeout(1000)
            except Exception as e:
                print(f"[{username}] 点击发送小费按钮失败: {e}")

            # 点击“小费选单”选项卡
            try:
                tip_tab_clicked = _click_by_keywords(
                    ["小费选单", "小费菜单", "Tip menu", "Tip Menu", "TIP MENU"],
                    "小费选单标签"
                )
                if tip_tab_clicked:
                    page.wait_for_timeout(2000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=5000)
                    except:
                        pass
                    page.wait_for_timeout(1000)
            except Exception as e:
                print(f"[{username}] 点击小费选单标签失败: {e}")
            
            # 从 DOM 中提取菜单项（优先 table，其次卡片式列表）
            try:
                menu_data = page.evaluate(r"""
                    () => {
                        const menuItems = [];
                        const seen = new Set();
                        const STOP_WORDS = ['目标', '总共支付', '已支付', '支付', '进度', 'goal', 'target', 'total', 'paid', 'progress'];

                        const pushItem = (activity, price, source = 'unknown', fullText = '') => {
                            if (!activity || !price) return;
                            activity = activity.replace(/\s+/g, ' ').trim();
                            const priceNum = (price.match(/(\d+)/) || [null, ''])[1];
                            if (!activity || !priceNum) return;
                            const activityLower = activity.toLowerCase();
                            if (STOP_WORDS.some(w => activityLower.includes(w))) return;
                            const key = `${activity}|${priceNum}`;
                            if (seen.has(key)) return;
                            seen.add(key);
                            menuItems.push({
                                activity,
                                price: priceNum,
                                text: activity,
                                raw: { activity, price: priceNum, fullText, source }
                            });
                        };

                        const tableSelectors = [
                            'div.ModelChatActionsSectionsWithScroll__section_tipMenu table',
                            'div.ModelChatActionsSectionsWithScroll__section table',
                            'table'
                        ];

                        const extractFromTables = () => {
                            for (const selector of tableSelectors) {
                                const tables = Array.from(document.querySelectorAll(selector));
                                for (const table of tables) {
                                    const rows = table.querySelectorAll('tr.tip-menu-item, tr');
                                    if (!rows.length) continue;
                                    for (const row of rows) {
                                        const activityCell = row.querySelector('.tip-menu-item-activity-cell, td:nth-child(1), td');
                                        const priceCell = row.querySelector('.tip-menu-item-price-cell, td:nth-child(2), td + td');
                                        if (!activityCell || !priceCell) continue;
                                        const activity = (activityCell.textContent || '').trim();
                                        const price = (priceCell.textContent || '').trim();
                                        pushItem(activity, price, 'table', row.textContent || '');
                                    }
                                }
                                if (menuItems.length) return;
                            }
                        };

                        const extractFromCards = () => {
                            const keywordRegex = /(小费|选单|tip|menu|token|代币)/i;
                            const valueRegex = /(.*?)(\d+)\s*(代币|token|tokens)/i;
                            const containers = new Set();
                            const selectors = [
                                'div.ModelChatActionsSectionsWithScroll__section_tipMenu',
                                '[class*="tip-menu"]',
                                '[class*="tipMenu"]',
                                '[data-test*="tip"]',
                                '[data-testid*="tip"]',
                                '[role="tabpanel"]',
                                'section'
                            ];
                            selectors.forEach(sel => {
                                document.querySelectorAll(sel).forEach(el => {
                                    const text = (el.textContent || '').trim();
                                    if (!text) return;
                                    if (!keywordRegex.test(text)) return;
                                    containers.add(el);
                                });
                            });

                            containers.forEach(container => {
                                const nodes = container.querySelectorAll('tr, li, div, p, span');
                                nodes.forEach(node => {
                                    const rawText = (node.innerText || node.textContent || '').trim();
                                    if (!rawText) return;
                                    const lowerRaw = rawText.toLowerCase();
                                    if (STOP_WORDS.some(w => lowerRaw.includes(w))) return;
                                    const match = rawText.match(valueRegex);
                                    if (match) {
                                        pushItem(match[1], match[2], 'card', rawText);
                                    }
                                });
                            });
                        };

                        extractFromTables();
                        if (!menuItems.length) {
                            extractFromCards();
                        }

                        return menuItems;
                    }
                """)
                
                if menu_data and len(menu_data) > 0:
                    result["menu_items"] = [item.get("activity") or item.get("text") for item in menu_data]
                    result["detailed_items"] = menu_data
                    print(f"\n[{username}] ========== 从DOM table中提取到 {len(menu_data)} 个菜单项 ==========")
                    # 打印详细的菜单项信息
                    for idx, item in enumerate(menu_data, 1):
                        activity = item.get("activity") or item.get("text") or ""
                        price = item.get("price") or ""
                        if price:
                            print(f"[{username}]   {idx:3d}. {activity:<50} - {price}代币")
                        else:
                            print(f"[{username}]   {idx:3d}. {activity}")
                    print(f"[{username}] ========== 菜单项列表结束（共 {len(menu_data)} 项）==========\n")
                else:
                    print(f"[{username}] 从DOM table中未提取到菜单项")
                    
            except Exception as e:
                error_msg = f"从DOM提取菜单失败: {str(e)}"
                result["error"] = error_msg
                print(f"[{username}] {error_msg}")
                if VERBOSE:
                    import traceback
                    traceback.print_exc()
            
            browser.close()
            
    except Exception as e:
        error_msg = f"Playwright提取菜单异常: {str(e)}"
        result["error"] = error_msg
        print(f"[{username}] {error_msg}")
        if VERBOSE:
            import traceback
            traceback.print_exc()
    
    return result


# ---------- 在线状态检测（基于搜索/suggestion API） ----------
async def check_online_status_via_search(session: aiohttp.ClientSession, username: str, cookies: Dict[str, str], ua: str, uniq: str) -> bool | None:
    """
    通过搜索 suggestion API 检查主播在线状态。
    返回 True(在线) / False(离线) / None(无法确定)
    """
    try:
        # 构建 suggestion API URL
        suggestion_url = (
            f"https://zh.superchat.live/api/front/v4/models/search/suggestion"
            f"?query={username}&limit=10&primaryTag=girls&rcmGrp=A&oRcmGrp=A&uniq={uniq}"
        )
        
        cookie_header = "; ".join([f"{k}={v}" for k, v in cookies.items()])
        headers = {
            "User-Agent": ua,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://zh.superchat.live/",
            "Cookie": cookie_header,
        }
        
        async with session.get(suggestion_url, headers=headers, timeout=10) as resp:
            if resp.status != 200:
                if VERBOSE:
                    print(f"[{username}] suggestion API 状态码: {resp.status}")
                return None
            
            try:
                data = await resp.json(content_type=None)
                if VERBOSE:
                    print(f"[{username}] suggestion API 响应类型: {type(data).__name__}")
            except Exception as e:
                if VERBOSE:
                    print(f"[{username}] suggestion API JSON 解析失败: {e}")
                    text = await resp.text()
                    print(f"[{username}] suggestion API 响应内容（前500字符）: {text[:500]}")
                return None
            
            # suggestion 响应可能是字典（包含 models 键）或直接是列表
            models_list = None
            if isinstance(data, dict):
                if VERBOSE:
                    print(f"[{username}] suggestion API 响应是字典，键: {list(data.keys())}")
                # 尝试从常见键中获取模型列表
                models_list = data.get("models") or data.get("results") or data.get("data")
                if models_list and isinstance(models_list, list):
                    if VERBOSE:
                        print(f"[{username}] 从字典中提取到 {len(models_list)} 个模型")
                else:
                    models_list = None
            elif isinstance(data, list):
                models_list = data
                if VERBOSE:
                    print(f"[{username}] suggestion API 响应是列表，包含 {len(models_list)} 个结果")
            
            # 在模型列表中查找匹配的主播
            if models_list and isinstance(models_list, list):
                for idx, model in enumerate(models_list):
                    # 尝试匹配用户名
                    model_username = model.get("username") or model.get("login") or model.get("name") or ""
                    
                    if VERBOSE and idx < 3:  # 只打印前3个结果用于调试
                        print(f"[{username}] suggestion[{idx}]: username={model_username}")
                    
                    if model_username.lower() == username.lower():
                        if VERBOSE:
                            print(f"[{username}] 找到匹配的主播: {model_username}")
                        
                        # 提取直播状态（优先使用 isLive，因为主要目的是检测是否在直播）
                        is_live = model.get("isLive")
                        is_online = model.get("isOnline")
                        
                        # 优先使用 isLive（是否在直播），如果不存在则使用 isOnline（是否在线）
                        if is_live is not None:
                            result = bool(is_live)
                            if VERBOSE:
                                print(f"[{username}] 从 isLive 字段提取到直播状态: {result} (isLive={is_live}, isOnline={is_online})")
                            return result
                        elif is_online is not None:
                            result = bool(is_online)
                            if VERBOSE:
                                print(f"[{username}] 从 isOnline 字段提取到在线状态: {result} (isOnline={is_online}, isLive未找到)")
                            return result
                        else:
                            # 如果都没找到，尝试其他字段
                            if VERBOSE:
                                status_fields = {k: v for k, v in model.items() if any(kw in k.lower() for kw in ["status", "live", "online", "broadcast"])}
                                print(f"[{username}] 未找到 isOnline/isLive，相关字段: {status_fields}")
                            return None
                
                # 如果没找到匹配的主播
                if VERBOSE:
                    print(f"[{username}] suggestion API 中未找到匹配的主播（用户名: {username}）")
                    usernames_found = [m.get("username") or m.get("login") or m.get("name") or "unknown" for m in models_list[:5]]
                    print(f"[{username}] 找到的用户名: {usernames_found}")
            else:
                if VERBOSE:
                    print(f"[{username}] suggestion API 响应格式无法识别，类型: {type(data).__name__}")
            
            return None
            
    except Exception as e:
        if VERBOSE:
            print(f"[{username}] 检查在线状态异常: {e}")
        return None

# ---------- Async polling worker ----------
async def poll_room(session: aiohttp.ClientSession, username: str):
    """异步轮询某房间的 /chat 接口，依赖 ROOM_STATE[username]['api_url'] & cookies"""
    seen = set()
    last_uniq_refresh = 0
    while True:
        try:
            state = ROOM_STATE.get(username)
            if not state or not state.get("api_url"):
                # 先用 Playwright 获取一次 uniq + cookies（在 executor 中运行）
                loop = asyncio.get_event_loop()
                uniq, cookies, ua, html, actual_username = await loop.run_in_executor(None, fetch_page_uniq_and_cookies, username, True, 20000)
                if not uniq:
                    print(f"[{username}] Playwright 未提取到 uniq，稍候重试")
                    await asyncio.sleep(5)
                    continue
                
                # 检测用户名变更
                username_changed = False
                if actual_username and actual_username != username:
                    print(f"[{username}] ⚠️ 检测到用户名已变更: {username} -> {actual_username}")
                    # 更新 streamers.json 中的用户名
                    if update_streamer_username(username, actual_username):
                        # 更新 ROOM_STATE 和 RUNNING_TASKS 的键名
                        old_state = ROOM_STATE.get(username, {})
                        if username in ROOM_STATE:
                            del ROOM_STATE[username]
                        if username in RUNNING_TASKS:
                            RUNNING_TASKS[actual_username] = RUNNING_TASKS.pop(username)
                        # 使用新用户名
                        username = actual_username
                        ROOM_STATE[username] = old_state
                        username_changed = True
                        print(f"[{username}] 已更新配置和状态，设置为低频模式等待下次刷新")
                
                api_url = f"https://zh.superchat.live/api/front/v2/models/username/{username}/chat?source=regular&uniq={uniq}"
                ROOM_STATE[username] = {
                    "api_url": api_url, 
                    "cookies": cookies, 
                    "ua": ua, 
                    "last_refresh": time.time(),
                    "online_status": None,
                    "last_status_check": 0,
                    "uniq": uniq,
                    "high_tip_count": 0,
                    "last_high_tip": None,
                    "status_loading": False,  # 初始化完成，清除加载状态
                    "model_id": None,  # 从消息中提取
                    "last_menu_tip": None,  # 最后匹配的菜单打赏信息
                    "offline_check_count": 0,  # 连续检测到已下播的次数
                    "low_freq_mode": False  # 用户名变更不再强制进入低频模式
                }
                state = ROOM_STATE[username]
                print(f"[{username}] 初始 uniq={uniq}，开始轮询 {api_url}")

            api_url = state["api_url"]
            cookies = state.get("cookies", {})
            ua = state.get("ua") or "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36"
            # 构造 cookie 字符串
            cookie_header = "; ".join([f"{k}={v}" for k, v in cookies.items()])

            headers = {
                "User-Agent": ua,
                "Accept": "application/json, text/plain, */*",
                "Referer": f"https://zh.superchat.live/{username}",
                "Cookie": cookie_header,
            }

            # 请求 API
            async with session.get(api_url, headers=headers, timeout=15) as resp:
                text_ct = resp.headers.get("Content-Type","")
                if resp.status != 200 or "text/html" in text_ct:
                    # 可能 uniq 失效或 CF 拦截：刷新 uniq & cookies
                    print(f"[{username}] 非 200 或返回 HTML({resp.status}), 刷新 uniq")
                    # 使用 Playwright 在后台刷新
                    loop = asyncio.get_event_loop()
                    uniq, cookies, ua, html, actual_username = await loop.run_in_executor(None, fetch_page_uniq_and_cookies, username, True, 20000)
                    if uniq:
                        # 检测用户名变更
                        username_changed = False
                        if actual_username and actual_username != username:
                            print(f"[{username}] ⚠️ 检测到用户名已变更: {username} -> {actual_username}")
                            if update_streamer_username(username, actual_username):
                                old_state = ROOM_STATE.get(username, {})
                                if username in ROOM_STATE:
                                    del ROOM_STATE[username]
                                if username in RUNNING_TASKS:
                                    RUNNING_TASKS[actual_username] = RUNNING_TASKS.pop(username)
                                username = actual_username
                                ROOM_STATE[username] = old_state
                                username_changed = True
                                print(f"[{username}] 已更新配置和状态，继续正常轮询")
                        
                        new_api = f"https://zh.superchat.live/api/front/v2/models/username/{username}/chat?source=regular&uniq={uniq}"
                        # 保留现有状态，只更新 uniq 相关字段
                        old_state = ROOM_STATE.get(username, {})
                        ROOM_STATE[username] = {
                            "api_url": new_api, 
                            "cookies": cookies, 
                            "ua": ua, 
                            "last_refresh": time.time(),
                            "online_status": old_state.get("online_status"),
                            "last_status_check": old_state.get("last_status_check", 0),
                            "uniq": uniq,
                            "high_tip_count": old_state.get("high_tip_count", 0),
                            "last_high_tip": old_state.get("last_high_tip"),
                            "status_loading": old_state.get("status_loading", True),  # 刷新时保持加载状态
                            "model_id": old_state.get("model_id"),
                            "last_menu_tip": old_state.get("last_menu_tip"),
                            "offline_check_count": old_state.get("offline_check_count", 0),
                            "low_freq_mode": old_state.get("low_freq_mode", False)
                        }
                        print(f"[{username}] 刷新到新 uniq={uniq}")
                    await asyncio.sleep(5)
                    continue

                doc = await resp.json(content_type=None)
                # doc 可能是 list 或 dict{'messages':[...] }
                msgs = doc if isinstance(doc, list) else doc.get("messages") or doc.get("data") or []
                if not msgs:
                    # 只有在非低频模式下且明确为直播中时才打印"本次无消息"
                    # 已下播或状态未知时不打印，减少日志噪音
                    # 状态未知时可能还在检测中，或者状态检查失败，不应该打印
                    online_status = state.get("online_status")
                    low_freq_mode = state.get("low_freq_mode", False)
                    # 只有明确为直播中时才打印
                    if VERBOSE and (not low_freq_mode and online_status is True):
                        print(f"[{username}] 本次无消息")
                    # 若长时间无消息，强制刷新 uniq 周期性检查（但低频模式下跳过，因为频率已经很低）
                    if not low_freq_mode and time.time() - state.get("last_refresh",0) > REFRESH_UNIQ_INTERVAL:
                        print(f"[{username}] 强制周期刷新 uniq")
                        loop = asyncio.get_event_loop()
                        uniq, cookies, ua, html, actual_username = await loop.run_in_executor(None, fetch_page_uniq_and_cookies, username, True, 20000)
                        if uniq:
                            # 检测用户名变更
                            username_changed = False
                            if actual_username and actual_username != username:
                                print(f"[{username}] ⚠️ 检测到用户名已变更: {username} -> {actual_username}")
                                if update_streamer_username(username, actual_username):
                                    old_state = ROOM_STATE.get(username, {})
                                    if username in ROOM_STATE:
                                        del ROOM_STATE[username]
                                    if username in RUNNING_TASKS:
                                        RUNNING_TASKS[actual_username] = RUNNING_TASKS.pop(username)
                                    username = actual_username
                                    ROOM_STATE[username] = old_state
                                    username_changed = True
                                    print(f"[{username}] 已更新配置和状态，继续正常轮询")
                            
                            old_state = ROOM_STATE.get(username, {})
                            ROOM_STATE[username] = {
                                "api_url": f"https://zh.superchat.live/api/front/v2/models/username/{username}/chat?source=regular&uniq={uniq}", 
                                "cookies": cookies, 
                                "ua": ua, 
                                "last_refresh": time.time(),
                                "online_status": old_state.get("online_status"),
                                "last_status_check": old_state.get("last_status_check", 0),
                                "uniq": uniq,
                                "high_tip_count": old_state.get("high_tip_count", 0),
                                "last_high_tip": old_state.get("last_high_tip"),
                                "status_loading": old_state.get("status_loading", False),  # 强制刷新时保持原有加载状态
                                "model_id": old_state.get("model_id"),
                                "last_menu_tip": old_state.get("last_menu_tip"),
                                "offline_check_count": old_state.get("offline_check_count", 0),
                                "low_freq_mode": old_state.get("low_freq_mode", False)
                            }
                            state = ROOM_STATE[username]  # 更新 state 引用

                # 处理消息
                else:
                    for m in msgs:
                        mid = str(m.get("id") or f"{m.get('createdAt')}_{m.get('cacheId')}")
                        if mid in seen:
                            continue
                        seen.add(mid)
                        
                        # 提取 modelId（如果还没有）
                        if not state.get("model_id") and m.get("modelId"):
                            state["model_id"] = m.get("modelId")
                            if VERBOSE:
                                print(f"[{username}] 提取到 modelId: {state['model_id']}")
                        
                        mtype = m.get("type")
                        details = m.get("details") or {}
                        
                        # 抽取金额：支持 amount, 金额, lovense detail.amount
                        amt = 0.0
                        if "amount" in details:
                            try: amt = float(details.get("amount",0))
                            except: amt = 0.0
                        else:
                            lov = details.get("lovenseDetails") or details.get("lovense_details")
                            if lov:
                                det = lov.get("detail") or lov.get("detail ")
                                if isinstance(det, dict) and "amount" in det:
                                    try: amt = float(det.get("amount",0))
                                    except: amt = 0.0

                        user = (m.get("userData") or {}).get("username") or (details.get("clientUserInfo") or {}).get("username")
                        ts = m.get("createdAt")
                        
                        # 目标达成监控：type="thresholdGoal" 且 details.goal == 0
                        if mtype == "thresholdGoal":
                            try:
                                goal_val = (details or {}).get("goal")
                                # goal==0 代表达成（从dabiao.json样例）
                                if goal_val == 0 and ts:
                                    # 只记录5分钟内的目标达成
                                    minutes_ago = get_minutes_ago(ts)
                                    if minutes_ago is not None and minutes_ago <= 5:
                                        try:
                                            state = ROOM_STATE.get(username) or {}
                                            current_last_goal = state.get("last_threshold_goal")
                                            # 只保留最新一条
                                            should_update = False
                                            if not current_last_goal:
                                                should_update = True
                                            else:
                                                cur_ts = current_last_goal.get("timestamp", "")
                                                if ts and cur_ts:
                                                    if ts > cur_ts:
                                                        should_update = True
                                                else:
                                                    should_update = True
                                            if should_update:
                                                state["last_threshold_goal"] = {
                                                    "goal": goal_val,
                                                    "timestamp": ts,
                                                    "id": mid
                                                }
                                                ROOM_STATE[username] = state
                                                if VERBOSE:
                                                    print(f"[{username}] ✅ 达标事件: goal={goal_val}, ts={ts}")
                                                try:
                                                    browser_notify(f"{username} 达成目标", f" · 时间：{ts}")
                                                except Exception:
                                                    pass
                                        except Exception:
                                            pass
                                    else:
                                        # 超过5分钟则忽略
                                        if VERBOSE:
                                            print(f"[{username}] ⏰ 达标事件已超过5分钟，忽略")
                            except Exception:
                                pass
                        
                        # 检查菜单打赏：type="tip" 且 source="tipMenu"
                        if mtype == "tip" and details.get("source") == "tipMenu":
                            menu_body = details.get("body", "").strip()
                            if menu_body and ts:
                                # 首先检查时间：只处理5分钟内的菜单打赏
                                try:
                                    # 解析时间戳（ISO 8601格式）
                                    ts_iso = ts.replace('Z', '+00:00')
                                    tip_time = datetime.fromisoformat(ts_iso)
                                    if tip_time.tzinfo is None:
                                        tip_time = tip_time.replace(tzinfo=timezone.utc)
                                    
                                    # 计算时间差
                                    now = datetime.now(timezone.utc)
                                    time_diff = now - tip_time
                                    
                                    # 如果超过5分钟，忽略
                                    if time_diff > timedelta(minutes=5):
                                        if VERBOSE:
                                            minutes_ago = int(time_diff.total_seconds() / 60)
                                            print(f"[{username}] ⏰ 菜单打赏时间超过5分钟，忽略: {menu_body} ({minutes_ago}分钟前)")
                                        continue  # 跳过这条消息
                                    
                                    # 5分钟内的消息，继续检查是否匹配选中的菜单项
                                except Exception as e:
                                    # 时间解析失败，跳过
                                    if VERBOSE:
                                        print(f"[{username}] ⚠️ 菜单打赏时间解析失败: {ts}, 错误: {e}")
                                    continue
                                
                                # 获取已选中的菜单项
                                selected_items = get_streamer_selected_menu_items(username)
                                matched = False  # 标记是否匹配成功
                                
                                # 过滤掉空字符串和空白字符串，只保留有效的菜单项
                                valid_selected_items = [item for item in selected_items if item and item.strip()]
                                
                                if valid_selected_items:
                                    # 清理menu_body：去除emoji和特殊字符，转换为小写进行匹配
                                    def clean_text(text):
                                        """清理文本：去除emoji和特殊字符，只保留中文、英文、数字
                                        同时处理Unicode转义序列（\\uXXXX格式）"""
                                        if not text:
                                            return ""
                                        # 首先处理Unicode转义序列（\\uXXXX格式），转换为实际字符
                                        try:
                                            # 如果文本包含 \u 转义序列（字面量形式，如 "\\u4e2d"），尝试解码
                                            if '\\u' in text:
                                                # 使用 unicode_escape 解码
                                                text = text.encode().decode('unicode_escape')
                                        except Exception:
                                            # 如果解码失败，保持原文本
                                            pass
                                        
                                        # 去除emoji（使用正则表达式匹配emoji范围）
                                        # 注意：避免使用大范围（如 \U000024C2-\U0001F251），因为它包含了中文字符范围（0x4E00-0x9FFF）
                                        # 使用精确的emoji范围，分成多个不重叠的小范围
                                        emoji_patterns = [
                                            re.compile("[\U0001F600-\U0001F64F]+", flags=re.UNICODE),  # emoticons
                                            re.compile("[\U0001F300-\U0001F5FF]+", flags=re.UNICODE),  # symbols & pictographs
                                            re.compile("[\U0001F680-\U0001F6FF]+", flags=re.UNICODE),  # transport & map symbols
                                            re.compile("[\U0001F1E0-\U0001F1FF]+", flags=re.UNICODE),  # flags (iOS)
                                            re.compile("[\U00002702-\U000027B0]+", flags=re.UNICODE),  # 装饰符号
                                            re.compile("[\U000024C2-\U000024FF]+", flags=re.UNICODE),  # 带圈字母和数字
                                            re.compile("[\U00002600-\U000026FF]+", flags=re.UNICODE),  # 符号和象形文字
                                            re.compile("[\U0001F900-\U0001F9FF]+", flags=re.UNICODE),  # 补充符号和象形文字
                                            re.compile("[\U0001FA00-\U0001FAFF]+", flags=re.UNICODE),  # 扩展A
                                        ]
                                        # 使用更安全的方法：分别匹配不重叠的范围，避免包含中文字符范围（0x4E00-0x9FFF）
                                        for pattern in emoji_patterns:
                                            text = pattern.sub('', text)
                                        # 去除其他特殊字符，只保留中文、英文、数字和常见标点
                                        text = re.sub(r'[^\w\s\u4e00-\u9fff~-]', '', text)
                                        # 去除多余空白
                                        text = re.sub(r'\s+', ' ', text)
                                        return text.strip().lower()
                                    
                                    cleaned_menu_body = clean_text(menu_body)

                                    
                                    # 如果清理后的菜单文本为空，不进行匹配
                                    if not cleaned_menu_body:
                                        matched = False
                                    else:
                                        # 检查是否匹配
                                        for selected_item in valid_selected_items:
                                            cleaned_selected = clean_text(selected_item)
                                            
                                            # 如果清理后的选中项为空，跳过
                                            if not cleaned_selected:
                                                continue
                                            
                                            # 更严格的匹配逻辑：
                                            # 1. 完全匹配（最高优先级）
                                            # 2. 包含匹配：要求匹配的子串（较短的字符串）长度至少是较长字符串的30%，且至少3个字符
                                            #    这样可以避免短字符串（如"测试"）误匹配长文本（如"这是一个测试菜单项"）
                                            is_match = False
                                            if cleaned_selected == cleaned_menu_body:
                                                is_match = True
                                            else:
                                                # 检查选中项是否包含在菜单文本中
                                                if cleaned_selected in cleaned_menu_body:
                                                    # 匹配的子串是 cleaned_selected，要求它至少是菜单文本长度的30%，且至少3个字符
                                                    min_match_len = max(3, int(len(cleaned_menu_body) * 0.3))
                                                    if len(cleaned_selected) >= min_match_len:
                                                        is_match = True
                                                # 检查菜单文本是否包含在选中项中
                                                elif cleaned_menu_body in cleaned_selected:
                                                    # 匹配的子串是 cleaned_menu_body，要求它至少是选中项长度的30%，且至少3个字符
                                                    min_match_len = max(3, int(len(cleaned_selected) * 0.3))
                                                    if len(cleaned_menu_body) >= min_match_len:
                                                        is_match = True
                                            
                                            if is_match:
                                                # 匹配成功，检查时间戳，只保留最新的菜单打赏
                                                if VERBOSE:
                                                    print(f"[{username}] 🔍 菜单匹配: 选中项='{selected_item}' (清理后='{cleaned_selected}') <-> 菜单文本='{menu_body}' (清理后='{cleaned_menu_body}')")
                                                matched = True
                                                try:
                                                    state = ROOM_STATE.get(username) or {}
                                                    current_last_tip = state.get("last_menu_tip")
                                                    
                                                    # 如果当前没有记录，或者新消息的时间更晚，则更新
                                                    should_update = False
                                                    if not current_last_tip:
                                                        should_update = True
                                                    else:
                                                        # 比较时间戳（ISO 8601格式）
                                                        current_ts = current_last_tip.get("timestamp", "")
                                                        if ts and current_ts:
                                                            # 直接比较字符串（ISO 8601格式可以按字典序比较）
                                                            if ts > current_ts:
                                                                should_update = True
                                                        else:
                                                            # 如果时间戳格式异常，默认更新
                                                            should_update = True
                                                    
                                                    if should_update:
                                                        state["last_menu_tip"] = {
                                                            "menu_text": menu_body,
                                                            "amount": amt,
                                                            "user": user,
                                                            "timestamp": ts,
                                                            "id": mid
                                                        }
                                                        ROOM_STATE[username] = state
                                                        if VERBOSE:
                                                            print(f"[{username}] 🎯 菜单打赏: {menu_body} (用户: {user}, 金额: {amt}, 时间: {ts})")
                                                        try:
                                                            browser_notify(f"{username} 选单命中", f"{menu_body} · 金额：{amt}")
                                                        except Exception:
                                                            pass
                                                except Exception:
                                                    pass
                                                break  # 找到匹配后退出循环
                                
                                # 如果没有匹配成功，清除之前的记录（如果有的话）
                                if not matched:
                                    try:
                                        state = ROOM_STATE.get(username) or {}
                                        if state.get("last_menu_tip"):
                                            state["last_menu_tip"] = None
                                            ROOM_STATE[username] = state
                                            if VERBOSE:
                                                print(f"[{username}] ⚠️ 菜单打赏未匹配选中项，清除记录: {menu_body}")
                                    except Exception:
                                        pass
                        
                        # 高额打赏检查：只处理 type=="tip" 且 source=="interactiveToy" 或 source=="" 的打赏
                        # 排除菜单打赏（source="tipMenu"）和其他类型的打赏
                        source = details.get("source", "")
                        threshold = get_streamer_threshold(username)
                        out = f"[{username}] [{ts}] type={mtype} user={user} amount={amt} id={mid}"
                        
                        # 检查是否符合高额打赏条件：type=="tip" 且 (source=="interactiveToy" 或 source=="") 且 amount>=threshold
                        if mtype == "tip" and (source == "interactiveToy" or source == "") and amt >= threshold:
                            # 首先检查时间：只处理5分钟内的打赏
                            if ts:
                                try:
                                    # 解析时间戳（ISO 8601格式）
                                    ts_iso = ts.replace('Z', '+00:00')
                                    tip_time = datetime.fromisoformat(ts_iso)
                                    if tip_time.tzinfo is None:
                                        tip_time = tip_time.replace(tzinfo=timezone.utc)
                                    
                                    # 计算时间差
                                    now = datetime.now(timezone.utc)
                                    time_diff = now - tip_time
                                    
                                    # 如果超过5分钟，只发送通知但不记录
                                    if time_diff > timedelta(minutes=5):
                                        notify_print_and_telegram(f"💰 HIGH TIP: {out} (>= {threshold})")
                                        try:
                                            browser_notify(f"{username} 高额小费", f"金额：${amt}（≥ {threshold}）")
                                        except Exception:
                                            pass
                                    else:
                                        # 5分钟内的打赏，发送通知并记录
                                        notify_print_and_telegram(f"💰 HIGH TIP: {out} (>= {threshold})")
                                        # 记录高额打赏统计
                                        try:
                                            state = ROOM_STATE.get(username) or {}
                                            state["high_tip_count"] = int(state.get("high_tip_count", 0)) + 1
                                            
                                            # 检查时间戳，只保留最新的
                                            current_last_tip = state.get("last_high_tip")
                                            should_update = False
                                            if not current_last_tip:
                                                should_update = True
                                            else:
                                                current_ts = current_last_tip.get("timestamp", "")
                                                if ts and current_ts:
                                                    if ts > current_ts:
                                                        should_update = True
                                                else:
                                                    should_update = True
                                            
                                            if should_update:
                                                state["last_high_tip"] = {
                                                    "amount": amt,
                                                    "user": user,
                                                    "timestamp": ts,
                                                    "id": mid,
                                                    "type": mtype
                                                }
                                            ROOM_STATE[username] = state
                                        except Exception:
                                            pass
                                except Exception as e:
                                    # 时间解析失败，仍然发送通知但不记录
                                    notify_print_and_telegram(f"💰 HIGH TIP: {out} (>= {threshold})")
                                    if VERBOSE:
                                        print(f"[{username}] ⚠️ 高额打赏时间解析失败: {ts}, 错误: {e}")
                            else:
                                # 没有时间戳，仍然发送通知但不记录
                                notify_print_and_telegram(f"💰 HIGH TIP: {out} (>= {threshold})")
                                try:
                                    browser_notify(f"{username} 高额小费", f"金额：${amt}（≥ {threshold}）")
                                except Exception:
                                    pass
                        # 不再打印通用消息，避免小额打赏刷屏
                        else:
                            pass

            # 定期检查直播状态（基于搜索/suggestion API）- 移到 async with 块外，确保每次循环都会执行
            now = time.time()
            state = ROOM_STATE.get(username, {})  # 重新获取最新状态
            offline_check_count = state.get("offline_check_count", 0)
            low_freq_mode = state.get("low_freq_mode", False)
            
            # 根据下播检查计数和在线状态决定状态检查间隔
            # 如果已下播/未知但计数器<2，每5秒检查一次（快速连续检查）
            # 如果已切换到低频模式，每10分钟检查一次状态（与轮询间隔一致）
            # 如果直播中，每3分钟检查一次状态（及时检测下播，避免状态错误保持为直播中）
            # 如果状态未知或已下播，与已下播做相同处理（快速检查2次后进入低频模式）
            online_status = state.get("online_status")
            if low_freq_mode:
                # 低频模式：状态检查间隔也是10分钟（与轮询间隔一致）
                status_check_interval = OFFLINE_POLL_INTERVAL
            elif offline_check_count > 0 and offline_check_count < 2:
                # 已检测到下播/未知但还未确认：每5秒检查一次
                status_check_interval = POLL_INTERVAL
            elif online_status is True:
                # 直播中：定期检查状态（每3分钟），及时检测下播
                # 避免状态被错误保持为直播中而无法检测到下播
                status_check_interval = ONLINE_CHECK_INTERVAL
            else:
                # 状态未知或已下播：与已下播做相同处理，每5秒检查一次（快速确认）
                # 如果是首次检测到未知状态，会在下面的逻辑中设置计数器
                status_check_interval = POLL_INTERVAL
            
            if now - state.get("last_status_check", 0) > status_check_interval:
                # 立即更新时间戳，防止在同一个循环中重复触发
                state = ROOM_STATE.get(username, {})
                state["last_status_check"] = now
                ROOM_STATE[username] = state
                
                if VERBOSE:
                    print(f"[{username}] 开始检查直播状态...")
                # 从 state 重新获取最新值
                state = ROOM_STATE.get(username, {})
                uniq = state.get("uniq")
                cookies = state.get("cookies", {})
                ua = state.get("ua") or "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36"
                # 如果 state 中没有 uniq，尝试从 api_url 中提取
                if not uniq:
                    import urllib.parse as up
                    parsed = up.urlparse(state.get("api_url", ""))
                    qs = up.parse_qs(parsed.query)
                    uniq_vals = qs.get("uniq") or []
                    if uniq_vals:
                        uniq = uniq_vals[0]
                        state["uniq"] = uniq  # 保存到 state 中
                
                if uniq:
                    new_status = await check_online_status_via_search(session, username, cookies, ua, uniq)
                    old_status = state.get("online_status")
                    # 状态检查已完成，保持已更新的时间戳
                    state["status_loading"] = False
                    
                    # 判断是否为直播状态：只有 new_status is True 才算直播
                    is_live = (new_status is True)
                    is_offline = (new_status is False)  # 明确下播
                    is_unknown = (new_status is None)    # 无法确定状态
                    
                    if is_live:
                        # 直播中：重置计数器和低频模式
                        state["online_status"] = True
                        state["offline_check_count"] = 0
                        state["low_freq_mode"] = False
                        
                        if old_status is None:
                            # 首次检测到直播状态
                            ROOM_STATE[username] = state
                            notify_print_and_telegram(f"[{username}] 直播状态: 🟢 直播中")
                            print(f"[{username}] 直播状态: 🟢 直播中")
                            # 首次检测到直播时也立即移动到第一行
                            try:
                                move_streamer_to_top(username)
                                refresh_streamers_list()
                            except Exception:
                                pass
                        elif old_status != True:
                            # 从下播/未知变为直播
                            ROOM_STATE[username] = state
                            state["last_status_check"] = now  # 重置状态检查时间
                            notify_print_and_telegram(f"[{username}] 直播状态变化: 🟢 开播")
                            print(f"[{username}] 直播状态更新: {old_status} -> True (开播)")
                            if VERBOSE:
                                print(f"[{username}] 状态从下播/未知变为直播，恢复正常轮询模式")
                            # 自动排序：新上播移动到第一行
                            try:
                                move_streamer_to_top(username)
                                refresh_streamers_list()
                            except Exception:
                                pass
                        else:
                            # 仍然是直播状态
                            ROOM_STATE[username] = state
                            if VERBOSE:
                                print(f"[{username}] 直播状态检查: 🟢 直播中 (未变化)")
                    else:
                        # 非直播状态（下播或未知）：统一处理逻辑
                        # 设置状态：明确下播设为False，未知设为None
                        state["online_status"] = False if is_offline else None
                        current_count = state.get("offline_check_count", 0)
                        
                        # 统一处理非直播状态的计数器逻辑
                        if old_status is True:
                            # 从直播变为非直播：计数器重置为1，立即开始快速检查
                            state["offline_check_count"] = 1
                            state["low_freq_mode"] = False
                            # 不修改 last_status_check，让它自然等待下次检查间隔
                            
                            status_str = "🟤 下播" if is_offline else "🟡 未知"
                            status_detail = "已下播" if is_offline else "未知"
                            ROOM_STATE[username] = state
                            notify_print_and_telegram(f"[{username}] 直播状态变化: {status_str}")
                            print(f"[{username}] 直播状态更新: True -> {state['online_status']} ({status_detail})")
                            if VERBOSE:
                                print(f"[{username}] 状态从直播变为{status_detail}，开始快速检查（每5秒检查一次，共检查2次）")
                            # 自动排序：新下播移动到当前最后一名直播中的下一行
                            try:
                                move_streamer_below_last_live(username)
                                refresh_streamers_list()
                            except Exception:
                                pass
                        elif current_count == 0:
                            # 首次检测到非直播状态（计数器为0表示从未检测过）
                            state["offline_check_count"] = 1
                            state["low_freq_mode"] = False
                            # 不修改 last_status_check，让它自然等待下次检查间隔
                            
                            status_str = "🟤 已下播" if is_offline else "🟡 未知"
                            ROOM_STATE[username] = state
                            notify_print_and_telegram(f"[{username}] 直播状态: {status_str}")
                            print(f"[{username}] 直播状态: {status_str}")
                            if VERBOSE:
                                print(f"[{username}] 首次检测到{status_str}，开始快速检查（每5秒检查一次，共检查2次）")
                        else:
                            # 状态未变化或从下播/未知变为未知：计数器+1
                            state["offline_check_count"] = current_count + 1
                            
                            # 如果计数器>=2且还未切换到低频模式，则切换
                            if state["offline_check_count"] >= 2 and not state.get("low_freq_mode", False):
                                state["low_freq_mode"] = True
                                status_detail = "下播" if is_offline else "状态未知"
                                if VERBOSE:
                                    print(f"[{username}] 已连续检测到{state['offline_check_count']}次{status_detail}，切换到低频轮询模式（10分钟一次）")
                            
                            ROOM_STATE[username] = state
                            
                            # 状态未变化时的日志
                            if old_status == state["online_status"]:
                                status_str = "🟤 已下播" if is_offline else "🟡 未知"
                                if VERBOSE:
                                    print(f"[{username}] 直播状态检查: {status_str} (未变化，计数器: {state['offline_check_count']})")
                            else:
                                # 从下播变为未知，或从未知变为下播
                                status_str = "🟡 未知" if is_unknown else "🟤 已下播"
                                notify_print_and_telegram(f"[{username}] 直播状态变化: {status_str}")
                                print(f"[{username}] 直播状态更新: {old_status} -> {state['online_status']}")
                else:
                    if VERBOSE:
                        print(f"[{username}] 直播状态检查: 跳过（未获取到 uniq）")

            # 根据在线状态和低频模式决定轮询间隔
            state = ROOM_STATE.get(username, {})  # 重新获取最新状态
            low_freq_mode = state.get("low_freq_mode", False)
            online_status = state.get("online_status")
            
            # 如果处于低频模式（已下播且连续检测2次以上），使用10分钟间隔
            # 否则使用正常间隔（3秒）
            if low_freq_mode:
                poll_interval = OFFLINE_POLL_INTERVAL  # 10分钟
                if VERBOSE:
                    # 只在低频模式下第一次打印，避免频繁打印
                    if not state.get("low_freq_logged", False):
                        print(f"[{username}] 进入低频轮询模式，每10分钟检查一次状态变化")
                        state["low_freq_logged"] = True
                        ROOM_STATE[username] = state
            else:
                poll_interval = POLL_INTERVAL  # 3秒
                # 退出低频模式时，清除日志标志
                if state.get("low_freq_logged", False):
                    state["low_freq_logged"] = False
                    ROOM_STATE[username] = state
            
            await asyncio.sleep(poll_interval)
        except asyncio.TimeoutError:
            print(f"[{username}] 请求超时，稍后重试")
            await asyncio.sleep(3)
        except Exception as e:
            print(f"[{username}] 轮询异常: {e}")
            await asyncio.sleep(5)


# ---------- 任务与会话管理（供 UI 调用） ----------
async def ensure_session() -> aiohttp.ClientSession:
    global ASYNC_SESSION
    if ASYNC_SESSION is None or ASYNC_SESSION.closed:
        connector = ProxyConnector.from_url(PROXY) if PROXY else None
        ASYNC_SESSION = aiohttp.ClientSession(connector=connector)
    return ASYNC_SESSION


async def start_monitor(username: str):
    if username in RUNNING_TASKS and not RUNNING_TASKS[username].done():
        return
    # 设置加载状态
    if username not in ROOM_STATE:
        ROOM_STATE[username] = {}
    ROOM_STATE[username]["status_loading"] = True
    session = await ensure_session()
    task = asyncio.create_task(poll_room(session, username))
    RUNNING_TASKS[username] = task
    set_streamer_running(username, True)


def stop_monitor(username: str):
    task = RUNNING_TASKS.get(username)
    if task and not task.done():
        task.cancel()
    RUNNING_TASKS.pop(username, None)
    set_streamer_running(username, False)
    # 清除加载状态并将状态置为未知
    if username in ROOM_STATE:
        ROOM_STATE[username]["status_loading"] = False
        ROOM_STATE[username]["online_status"] = None


async def stop_all_monitors():
    for u in list(RUNNING_TASKS.keys()):
        stop_monitor(u)


async def close_session():
    global ASYNC_SESSION
    if ASYNC_SESSION is not None and not ASYNC_SESSION.closed:
        await ASYNC_SESSION.close()
    ASYNC_SESSION = None


# ---------- 持久化存储 ----------
# load_streamers 和 save_streamers 已在文件开头定义


# ---------- NiceGUI UI ----------
UI_BINDINGS: Dict[str, Dict[str, Any]] = {}
STREAMERS_CONTAINER = None  # 用于动态更新主播列表容器
DELETE_MODE = False  # 删除模式标志
SELECTED_STREAMERS = set()  # 选中的主播集合


def human_status(username: str) -> str:
    state = ROOM_STATE.get(username) or {}
    # 如果正在加载状态，显示加载中
    if state.get("status_loading", False):
        return "🟡 加载中..."
    status = state.get("online_status")
    if status is True:
        return "🟢 直播中"
    if status is False:
        return "🟤 已下播"
    return "⚫️ 未知"
    # ⚫️ 🟤 🟠

def to_beijing_time(iso_ts: str) -> str:
    """将 UTC 时间转换为北京时间"""
    try:
        iso_ts = iso_ts.replace('Z', '+00:00')
        dt = datetime.fromisoformat(iso_ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        bj = dt.astimezone(timezone(timedelta(hours=8)))
        return bj.strftime('%H:%M:%S')
    except Exception:
        return iso_ts if iso_ts else "—"


def get_high_tip_amount(username: str) -> str:
    """获取最新高额打赏的金额（如果有5分钟内的记录，显示整数金额+圆点，否则显示"小费"）"""
    state = ROOM_STATE.get(username) or {}
    last_high = state.get("last_high_tip") or {}
    if last_high:
        ts_utc = last_high.get("timestamp", "")
        if ts_utc:
            minutes_ago = get_minutes_ago(ts_utc)
            if minutes_ago is not None:
                # 如果超过5分钟，清除记录
                if minutes_ago > 5:
                    try:
                        state = ROOM_STATE.get(username) or {}
                        state["last_high_tip"] = None
                        ROOM_STATE[username] = state
                    except Exception:
                        pass
                    return "小费"
                # 5分钟内有记录，显示整数金额+圆点
                if minutes_ago <= 5:
                    amt = last_high.get("amount")
                    if amt is not None:
                        amt_int = int(amt)  # 转换为整数
                        return f"${amt_int}●"  # 返回金额+圆点，圆点将通过UI处理为粉色
    return "小费"  # 没有满足条件的记录，显示"小费"

def get_high_tip_time(username: str) -> str:
    """获取最新高额打赏的时间（显示为"x分钟前"）"""
    state = ROOM_STATE.get(username) or {}
    last_high = state.get("last_high_tip") or {}
    if last_high:
        ts_utc = last_high.get("timestamp", "")
        if ts_utc:
            minutes_ago = get_minutes_ago(ts_utc)
            if minutes_ago is not None:
                # 如果超过5分钟，清除记录
                if minutes_ago > 5:
                    try:
                        state = ROOM_STATE.get(username) or {}
                        state["last_high_tip"] = None
                        ROOM_STATE[username] = state
                    except Exception:
                        pass
                    return "—"
                # 5分钟内，显示"x分钟前"
                if minutes_ago == 0:
                    return "刚刚"
                else:
                    return f"{minutes_ago}分钟前"
    return "—"


def has_active_events(username: str) -> bool:
    """检查是否有满足条件的小费、菜单或达标事件（即是否有粉色圆点）"""
    state = ROOM_STATE.get(username) or {}
    
    # 检查是否有满足条件的高额打赏（5分钟内）
    last_high = state.get("last_high_tip") or {}
    if last_high:
        ts_utc = last_high.get("timestamp", "")
        if ts_utc:
            minutes_ago = get_minutes_ago(ts_utc)
            if minutes_ago is not None and minutes_ago <= 5:
                return True
    
    # 检查是否有满足条件的菜单打赏（5分钟内）
    last_menu_tip = state.get("last_menu_tip")
    if last_menu_tip:
        ts_utc = last_menu_tip.get("timestamp", "")
        if ts_utc:
            minutes_ago = get_minutes_ago(ts_utc)
            if minutes_ago is not None and minutes_ago <= 5:
                return True
    
    # 检查是否有满足条件的达标事件（5分钟内）
    last_goal = state.get("last_threshold_goal")
    if last_goal:
        ts_utc = last_goal.get("timestamp", "")
        if ts_utc:
            minutes_ago = get_minutes_ago(ts_utc)
            if minutes_ago is not None and minutes_ago <= 5:
                return True
    
    return False

def get_menu_info(username: str) -> str:
    """获取菜单信息（如果有匹配的菜单打赏，显示"选单●"，否则显示"选单"）"""
    state = ROOM_STATE.get(username) or {}
    last_menu_tip = state.get("last_menu_tip")
    if last_menu_tip:
        # 检查时间是否在5分钟内
        try:
            ts_utc = last_menu_tip.get("timestamp", "")
            if ts_utc:
                ts_iso = ts_utc.replace('Z', '+00:00')
                tip_time = datetime.fromisoformat(ts_iso)
                if tip_time.tzinfo is None:
                    tip_time = tip_time.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                time_diff = now - tip_time
                # 如果超过5分钟，清除记录
                if time_diff > timedelta(minutes=5):
                    state["last_menu_tip"] = None
                    ROOM_STATE[username] = state
                    return "选单"
                # 5分钟内，显示带圆点的"选单"
                return "选单●"
        except Exception:
            pass
    return "选单"

def get_minutes_ago(iso_ts: str) -> int:
    """计算时间戳距离现在的分钟数，返回None表示解析失败"""
    try:
        ts_iso = iso_ts.replace('Z', '+00:00')
        tip_time = datetime.fromisoformat(ts_iso)
        if tip_time.tzinfo is None:
            tip_time = tip_time.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        time_diff = now - tip_time
        return int(time_diff.total_seconds() / 60)
    except Exception:
        return None

def get_threshold_info(username: str) -> str:
    """获取达标信息（如果5分钟内有达标事件，显示"达标●"，否则显示"达标"）"""
    state = ROOM_STATE.get(username) or {}
    last_goal = state.get("last_threshold_goal")
    if last_goal:
        ts_utc = last_goal.get("timestamp", "")
        if ts_utc:
            minutes_ago = get_minutes_ago(ts_utc)
            if minutes_ago is not None:
                if minutes_ago > 5:
                    try:
                        state["last_threshold_goal"] = None
                        ROOM_STATE[username] = state
                    except Exception:
                        pass
                    return "达标"
                return "达标●"
    return "达标"

def get_threshold_time(username: str) -> str:
    """获取达标时间（显示为"x分钟前"，超过5分钟或无记录显示—）"""
    state = ROOM_STATE.get(username) or {}
    last_goal = state.get("last_threshold_goal")
    if last_goal:
        ts_utc = last_goal.get("timestamp", "")
        if ts_utc:
            minutes_ago = get_minutes_ago(ts_utc)
            if minutes_ago is not None:
                if minutes_ago > 5:
                    try:
                        state["last_threshold_goal"] = None
                        ROOM_STATE[username] = state
                    except Exception:
                        pass
                    return "—"
                return "刚刚" if minutes_ago == 0 else f"{minutes_ago}分钟前"
    return "—"

def get_menu_tip_time(username: str) -> str:
    """获取菜单打赏时间（显示为"x分钟前"）"""
    state = ROOM_STATE.get(username) or {}
    last_menu_tip = state.get("last_menu_tip")
    if last_menu_tip:
        ts_utc = last_menu_tip.get("timestamp", "")
        if ts_utc:
            minutes_ago = get_minutes_ago(ts_utc)
            if minutes_ago is not None:
                # 如果超过5分钟，清除记录
                if minutes_ago > 5:
                    try:
                        state = ROOM_STATE.get(username) or {}
                        state["last_menu_tip"] = None
                        ROOM_STATE[username] = state
                    except Exception:
                        pass
                    return "—"
                # 5分钟内，显示"x分钟前"
                if minutes_ago == 0:
                    return "刚刚"
                else:
                    return f"{minutes_ago}分钟前"
    return "—"

def get_menu_detail(username: str) -> str:
    """获取菜单详情（完整的菜单项内容）"""
    state = ROOM_STATE.get(username) or {}
    last_menu_tip = state.get("last_menu_tip")
    if last_menu_tip:
        ts_utc = last_menu_tip.get("timestamp", "")
        if ts_utc:
            minutes_ago = get_minutes_ago(ts_utc)
            if minutes_ago is not None and minutes_ago <= 5:
                # 5分钟内有记录，返回菜单文本
                menu_text = last_menu_tip.get("menu_text", "")
                if menu_text:
                    return menu_text
    return "—"


def is_running(username: str) -> bool:
    t = RUNNING_TASKS.get(username)
    return bool(t and not t.done())


def build_streamer_row(username: str):
    # 总宽度114.125%，固定百分比宽度：36.3%, 13.2%, 6.875%, 6.875%, 6.875%, 11%, 11%, 11%, 11%
    # 3个堆叠列（金额、达标、选单）各6.875%，4个按钮列各11%
    with ui.row().classes('items-center gap-3 flex-nowrap').style('width:100%'):
        # 删除模式下的选择框（最左边）
        checkbox = None
        if DELETE_MODE:
            def on_checkbox_change(e):
                global SELECTED_STREAMERS
                if e.value:
                    SELECTED_STREAMERS.add(username)
                else:
                    SELECTED_STREAMERS.discard(username)
            checkbox = ui.checkbox('', value=username in SELECTED_STREAMERS, on_change=on_checkbox_change).style('width:30px; flex-shrink:0')
        
        # 名称列宽度：如果有选择框则减少，否则保持36.3%
        name_width = 'calc(36.3% - 30px)' if DELETE_MODE else '36.3%'
        # 检查是否有满足条件的事件，决定背景色
        has_events = has_active_events(username)
        name_bg_color = '#f9a8d4' if has_events else 'transparent'  # 更深的粉色背景或透明
        name_label = ui.label(username).classes('text-lg font-medium whitespace-nowrap').style(f'width:{name_width}; background-color: {name_bg_color}; padding: 4px 8px; border-radius: 4px;')
        status_label = ui.label(human_status(username)).classes('text-primary whitespace-nowrap').style('width:13.2%')
        
        # 金额/时间（上下堆叠）
        with ui.column().classes('gap-0').style('width:6.875%'):
            tip_amount_info = get_high_tip_amount(username)
            # 统一使用ui.html，方便后续更新
            if "●" in tip_amount_info:
                # 使用HTML来显示金额和粉色圆点
                amount_text = tip_amount_info.replace("●", "")
                tip_amount_label = ui.html(f'<span style="color: #6b7280;">{amount_text}</span><span style="color: #ec4899; font-size: 1.2em; margin-left: 2px;">●</span>', sanitize=False).classes('whitespace-nowrap text-sm')
            else:
                # 即使没有圆点，也使用ui.html以便后续更新
                tip_amount_label = ui.html(f'<span style="color: #6b7280;">{tip_amount_info}</span>', sanitize=False).classes('whitespace-nowrap text-sm')
            tip_time_label = ui.label(get_high_tip_time(username)).classes('text-gray-500 whitespace-nowrap text-xs')
        
        # 达标/时间（上下堆叠）
        with ui.column().classes('gap-0').style('width:6.875%'):
            threshold_text = get_threshold_info(username)
            # 统一使用ui.html，方便后续更新，并在有圆点时使用粉色圆点
            if "●" in threshold_text:
                base_text = threshold_text.replace("●", "")
                threshold_label = ui.html(
                    f'<span style="color: #6b7280;">{base_text}</span>'
                    f'<span style="color: #ec4899; font-size: 1.2em; margin-left: 2px;">●</span>',
                    sanitize=False
                ).classes('whitespace-nowrap text-sm')
            else:
                threshold_label = ui.html(
                    f'<span style="color: #6b7280;">{threshold_text}</span>',
                    sanitize=False
                ).classes('whitespace-nowrap text-sm')
            threshold_time_label = ui.label(get_threshold_time(username)).classes('text-gray-500 whitespace-nowrap text-xs')
        
        # 选单/时间（上下堆叠）
        with ui.column().classes('gap-0').style('width:6.875%'):
            menu_info = get_menu_info(username)
            # 统一使用ui.html，方便后续更新
            if "●" in menu_info:
                # 使用HTML来显示"选单"和粉色圆点
                menu_label = ui.html('<span style="color: #6b7280;">选单</span><span style="color: #ec4899; font-size: 1.2em; margin-left: 2px;">●</span>', sanitize=False).classes('whitespace-nowrap text-sm')
            else:
                # 即使没有圆点，也使用ui.html以便后续更新
                menu_label = ui.html(f'<span style="color: #6b7280;">{menu_info}</span>', sanitize=False).classes('whitespace-nowrap text-sm')
            menu_time_label = ui.label(get_menu_tip_time(username)).classes('text-gray-500 whitespace-nowrap text-xs')
        
        async def on_switch_change(e):
            set_streamer_running(username, e.value)
            if e.value:
                await start_monitor(username)
            else:
                stop_monitor(username)

        with ui.row().classes('justify-center').style('width:11%'):
            toggle_switch = ui.switch('', value=get_streamer_running(username), on_change=on_switch_change).classes('whitespace-nowrap')

        # 配置按钮
        def open_config():
            # 获取当前配置
            current_threshold = get_streamer_threshold(username)
            current_menu_items = get_streamer_menu_items(username)
            current_selected = set(get_streamer_selected_menu_items(username))
            
            # 创建对话框
            with ui.dialog() as config_dialog, ui.card().style('width: 760px; min-height: 78vh; max-height: 92vh; padding: 16px; display: flex; flex-direction: column;'):
                ui.label('配置设置').classes('text-h6').style('font-weight: bold; margin-bottom: 4px;')
                
                # 阈值设置区域
                with ui.column().classes('w-full').style('margin-bottom: 4px;'):
                    ui.label('设置打赏金额提醒阈值').classes('text-subtitle2').style('margin-bottom: 2px;')
                    threshold_input = ui.number(
                        label='阈值金额',
                        value=current_threshold,
                        min=0,
                        step=0.1
                    ).classes('w-full').style('margin-bottom: 0;')
                
                # 菜单列表区域
                with ui.column().classes('w-full').style('margin-bottom: 4px;'):
                    ui.label('完整小费选单').classes('text-subtitle2').style('margin-bottom: 2px;')
                    
                    # 菜单列表容器（可滚动，去掉边框）
                    menu_container = ui.column().classes('w-full').style('max-height: 240px; overflow-y: auto; padding: 4px;')
                    
                    # 存储菜单项复选框的字典
                    menu_checkboxes = {}
                    menu_items_list = []  # 存储菜单项数据
                    
                    def update_menu_list(menu_data):
                        """更新菜单列表显示"""
                        nonlocal menu_items_list
                        menu_container.clear()
                        menu_checkboxes.clear()
                        menu_items_list = menu_data if menu_data else []

                        with menu_container:
                            if not menu_items_list:
                                ui.label('暂无菜单项，请点击"刷新菜单"获取').classes('text-gray-500 text-sm').style('padding: 4px;')
                            else:
                                for idx, item in enumerate(menu_items_list):
                                    # 提取菜单项文本
                                    if isinstance(item, dict):
                                        activity = item.get("activity") or item.get("text") or ""
                                        price = item.get("price") or ""
                                        item_key = activity  # 使用activity作为唯一标识
                                    else:
                                        activity = str(item)
                                        price = ""
                                        item_key = str(item)

                                    with ui.row().classes('w-full items-center gap-2').style('margin-bottom: 1px; justify-content: space-between;'):
                                        checkbox = ui.checkbox(
                                            activity,
                                            value=item_key in current_selected
                                        ).classes('flex-1')
                                        menu_checkboxes[item_key] = checkbox
                                        if price:
                                            ui.label(f"{price}代币").classes('text-gray-600 text-sm').style('flex-shrink: 0; margin-left: 8px;')
                    
                    # 初始加载已保存的菜单
                    update_menu_list(current_menu_items)
                    
                    # 刷新菜单按钮
                    with ui.row().classes('w-full gap-2').style('margin-top: 2px;'):
                        refresh_btn = ui.button('刷新菜单').classes('q-btn--no-uppercase')
                        # 仅在主播直播中才允许刷新菜单
                        state = ROOM_STATE.get(username) or {}
                        can_refresh_menu = state.get("online_status") is True
                        refresh_btn.set_enabled(can_refresh_menu)
                        if not can_refresh_menu:
                            refresh_btn.tooltip('主播未直播，无法刷新菜单')
                        
                        async def refresh_menu():
                            refresh_btn.props('loading')
                            refresh_btn.set_enabled(False)
                            try:
                                ui.notify('正在获取菜单，请稍候...', type='info')
                                
                                # 先获取当前对话框中的选中状态（如果有菜单项的话）
                                current_dialog_selected = set()
                                for item_key, checkbox in menu_checkboxes.items():
                                    if checkbox.value:
                                        current_dialog_selected.add(item_key)
                                
                                # 在后台线程中执行extract_menu_from_dom
                                loop = asyncio.get_event_loop()
                                result = await loop.run_in_executor(None, extract_menu_from_dom, username, True, 30000)
                                
                                if result.get("error"):
                                    ui.notify(f'获取菜单失败: {result["error"]}', type='negative')
                                elif result.get("detailed_items"):
                                    # 更新菜单列表
                                    menu_data = result["detailed_items"]
                                    # 保持当前对话框中的选中状态（如果菜单项还在新菜单中）
                                    new_selected = set()
                                    for item in menu_data:
                                        if isinstance(item, dict):
                                            activity = item.get("activity") or item.get("text") or ""
                                        else:
                                            activity = str(item)
                                        if activity in current_dialog_selected:
                                            new_selected.add(activity)
                                    
                                    # 更新current_selected（用于后续的update_menu_list）
                                    current_selected.clear()
                                    current_selected.update(new_selected)
                                    update_menu_list(menu_data)
                                    # 立即持久化最新菜单列表，防止对话框意外关闭导致数据丢失
                                    try:
                                        set_streamer_menu_items(username, menu_data)
                                    except Exception as pers_err:
                                        print(f"[{username}] 保存菜单列表失败: {pers_err}")
                                    ui.notify(f'成功获取 {len(menu_data)} 个菜单项', type='positive')
                                else:
                                    ui.notify('未获取到菜单项', type='warning')
                            except Exception as e:
                                ui.notify(f'刷新菜单失败: {str(e)}', type='negative')
                                import traceback
                                traceback.print_exc()
                            finally:
                                refresh_btn.props('loading=false')
                                refresh_btn.set_enabled(True)
                        
                        refresh_btn.on_click(refresh_menu)
                
                # 底部按钮
                with ui.row().classes('w-full justify-end gap-2').style('margin-top: 6px;'):
                    def cancel_config():
                        config_dialog.close()
                    
                    async def confirm_config():
                        # 保存阈值
                        try:
                            threshold_val = float(threshold_input.value)
                            set_streamer_threshold(username, threshold_val)
                        except (ValueError, TypeError):
                            ui.notify('阈值必须是有效数字', type='warning')
                            return
                        
                        # 保存完整菜单
                        set_streamer_menu_items(username, menu_items_list)
                        
                        # 保存选中的菜单项
                        selected_items = []
                        for item_key, checkbox in menu_checkboxes.items():
                            if checkbox.value:
                                selected_items.append(item_key)
                        set_streamer_selected_menu_items(username, selected_items)
                        
                        ui.notify('配置已保存', type='positive')
                        config_dialog.close()
                    
                    ui.button('取消', on_click=cancel_config).classes('q-btn--no-uppercase')
                    ui.button('确定', on_click=confirm_config).classes('q-btn--no-uppercase')
            
            config_dialog.open()

        cfg_btn = ui.button('配置', on_click=open_config).classes('q-btn--outline q-btn--no-uppercase whitespace-nowrap').style('width:11%')

        def open_room():
            url = f"https://zh.superchat.live/{username}"
            ui.run_javascript(f'window.open("{url}", "_blank")')

        open_btn = ui.button('进入直播间', on_click=open_room).classes('q-btn--outline q-btn--no-uppercase whitespace-nowrap').style('width:11%')
        
        # 选单详情列（支持换行显示完整菜单内容）
        menu_detail_text = get_menu_detail(username)
        menu_detail_label = ui.label(menu_detail_text).classes('text-gray-600 text-sm').style('width:11%; word-wrap: break-word; overflow-wrap: break-word; white-space: normal; max-height: 60px; overflow-y: auto;')

        UI_BINDINGS[username] = {
            "name": name_label,
            "status": status_label,
            "tip_amount": tip_amount_label,
            "tip_time": tip_time_label,
            "threshold": threshold_label,
            "threshold_time": threshold_time_label,
            "menu": menu_label,
            "menu_time": menu_time_label,
            "menu_detail": menu_detail_label,
            "switch": toggle_switch,
        }


def refresh_ui():
    stale_users = []
    for username, widgets in list(UI_BINDINGS.items()):
        try:
            # 更新名字列背景色（根据是否有满足条件的事件）
            if "name" in widgets:
                has_events = has_active_events(username)
                name_bg_color = '#f9a8d4' if has_events else 'transparent'  # 更深的粉色背景或透明
                widgets["name"].style(f'width:{"calc(36.3% - 30px)" if DELETE_MODE else "36.3%"}; background-color: {name_bg_color}; padding: 4px 8px; border-radius: 4px;')
            
            widgets["status"].text = human_status(username)
            # 更新金额信息
            tip_amount_info = get_high_tip_amount(username)
            if "●" in tip_amount_info:
                # 使用content属性更新ui.html的内容
                try:
                    amount_text = tip_amount_info.replace("●", "")
                    widgets["tip_amount"].content = f'<span style="color: #6b7280;">{amount_text}</span><span style="color: #ec4899; font-size: 1.2em; margin-left: 2px;">●</span>'
                except AttributeError:
                    # 如果不支持content，可能是label，使用text
                    widgets["tip_amount"].text = tip_amount_info
            else:
                # 只显示"小费"
                try:
                    widgets["tip_amount"].content = f'<span style="color: #6b7280;">{tip_amount_info}</span>'
                except AttributeError:
                    widgets["tip_amount"].text = tip_amount_info
            widgets["tip_time"].text = get_high_tip_time(username)
            # 更新达标信息
            if "threshold" in widgets:
                th_info = get_threshold_info(username)
                # 如果有达标（显示"达标●"），用粉色圆点
                if "●" in th_info:
                    try:
                        base_text = th_info.replace("●", "")
                        widgets["threshold"].content = f'<span style="color: #6b7280;">{base_text}</span><span style="color: #ec4899; font-size: 1.2em; margin-left: 2px;">●</span>'
                    except AttributeError:
                        widgets["threshold"].text = th_info
                else:
                    try:
                        widgets["threshold"].content = f'<span style="color: #6b7280;">{th_info}</span>'
                    except AttributeError:
                        widgets["threshold"].text = th_info
            if "threshold_time" in widgets:
                widgets["threshold_time"].text = get_threshold_time(username)
            # 更新菜单信息
            if "menu" in widgets:
                menu_info = get_menu_info(username)
                # 如果有菜单打赏（显示"选单●"），需要更新HTML内容
                if "●" in menu_info:
                    # 使用content属性更新ui.html的内容
                    try:
                        widgets["menu"].content = '<span style="color: #6b7280;">选单</span><span style="color: #ec4899; font-size: 1.2em; margin-left: 2px;">●</span>'
                    except AttributeError:
                        # 如果不支持content，可能是label，使用text
                        widgets["menu"].text = menu_info
                else:
                    # 只显示"选单"
                    try:
                        widgets["menu"].content = '<span style="color: #6b7280;">选单</span>'
                    except AttributeError:
                        widgets["menu"].text = menu_info
            # 更新菜单打赏时间
            if "menu_time" in widgets:
                widgets["menu_time"].text = get_menu_tip_time(username)
            # 更新菜单详情
            if "menu_detail" in widgets:
                widgets["menu_detail"].text = get_menu_detail(username)
            # 同步切换按钮状态与 running 值
            desired = get_streamer_running(username)
            sw = widgets.get("switch")
            if sw is not None and sw.value != desired:
                sw.value = desired
        except RuntimeError as e:
            # 如果组件已被销毁，记录该主播以清理绑定
            if "parent slot" in str(e).lower():
                stale_users.append(username)
            else:
                raise

    for username in stale_users:
        UI_BINDINGS.pop(username, None)


def sort_streamers_by_live_status():
    """按状态排序主播列表：直播中的排在最前面"""
    global STREAMERS
    def get_status_sort_key(streamer):
        username = get_streamer_username(streamer)
        if not username:
            return 1  # 无法获取用户名，排在后面
        state = ROOM_STATE.get(username) or {}
        status = state.get("online_status")
        if status is True:
            return 0  # 直播中，排在最前面
        else:
            return 1  # 其他状态，排在后面
    STREAMERS.sort(key=get_status_sort_key)

def move_streamer_to_index(username: str, target_index: int):
    """将主播移动到 STREAMERS 的指定位置"""
    global STREAMERS
    idx, streamer = find_streamer_by_username(username)
    if streamer is None:
        return
    # 移除并插入到目标位置（边界保护）
    STREAMERS.pop(idx)
    if target_index < 0:
        target_index = 0
    if target_index > len(STREAMERS):
        target_index = len(STREAMERS)
    STREAMERS.insert(target_index, streamer)

def move_streamer_to_top(username: str):
    """将主播移动到列表第一行"""
    move_streamer_to_index(username, 0)

def move_streamer_below_last_live(username: str):
    """将主播移动到当前最后一个直播中主播的下一行；如果没有直播中主播，则移动到列表开头"""
    global STREAMERS
    last_live_index = -1
    # 先移除自身，避免干扰计算
    idx, _ = find_streamer_by_username(username)
    if idx is None:
        return
    removed = STREAMERS.pop(idx)
    # 查找最后一名直播中的主播索引
    for i, s in enumerate(STREAMERS):
        uname = get_streamer_username(s)
        if uname:
            st = (ROOM_STATE.get(uname) or {}).get("online_status")
            if st is True:
                last_live_index = i
    # 计算插入位置（最后直播中的下一行；若无直播中，则插入到0）
    insert_index = last_live_index + 1
    if insert_index < 0:
        insert_index = 0
    if insert_index > len(STREAMERS):
        insert_index = len(STREAMERS)
    STREAMERS.insert(insert_index, removed)

def refresh_streamers_list():
    """刷新主播列表显示"""
    global STREAMERS_CONTAINER, STREAMERS, UI_BINDINGS
    if STREAMERS_CONTAINER is None:
        return
    
    # 清空容器
    STREAMERS_CONTAINER.clear()
    UI_BINDINGS.clear()
    
    # 重新渲染列表
    with STREAMERS_CONTAINER:
        # 顶部标题行
        # 计算总宽度：36.3 + 13.2 + 6.875*3 + 11*4 = 114.125%
        # 为了居中，使用114.125%，margin-left和margin-right各为-7.0625%
        with ui.card().style('width:114.125%; margin-left:-7.0625%; margin-right:-7.0625%'):
            with ui.row().classes('items-center gap-3 flex-nowrap').style('width:100%'):
                ui.label('主播名称').classes('text-gray-500 text-sm').style('width:35.8%')
                # 状态标题：恢复为普通标题
                ui.label('状态').classes('text-gray-500 text-sm').style('width:13.2%; text-align:left;')
                ui.label('金额').classes('text-gray-500 text-sm').style('width:6.875%; text-align:left;')
                ui.label('达标').classes('text-gray-500 text-sm').style('width:6.875%; text-align:left;')
                ui.label('选单').classes('text-gray-500 text-sm').style('width:6.875%; text-align:left;')
                ui.label('监控').classes('text-gray-500 text-sm').style('width:11.5%; text-align:center;')
                ui.label('配置').classes('text-gray-500 text-sm').style('width:11%; text-align:center;')
                ui.label('直播间').classes('text-gray-500 text-sm').style('width:11%; text-align:center;')
                ui.label('选单详情').classes('text-gray-500 text-sm').style('width:11%; text-align:center;')
        
        for streamer in STREAMERS:
            username = get_streamer_username(streamer)
            if username:
                with ui.card().style('width:114.125%; margin-left:-7.0625%; margin-right:-7.0625%'):
                    build_streamer_row(username)


def build_ui():
    global DELETE_MODE, SELECTED_STREAMERS, STREAMERS_CONTAINER
    
    ui.colors(primary='#4f46e5', secondary='#64748b')
    
    # 启动时初始化会话并根据 running 状态自动启动监控
    async def init_and_start():
        await ensure_session()
        
        # 启动时尝试按运行中状态启动
        for s in list(STREAMERS):
            username = get_streamer_username(s)
            if not username:
                continue
            if get_streamer_running(username):
                await start_monitor(username)
    
    # 使用 ui.timer 延迟执行，确保 UI 已初始化
    def start_init():
        asyncio.create_task(init_and_start())
    
    ui.timer(0.1, start_init, once=True)
    # 请求浏览器通知权限（如果还未授权）
    def _request_notif_perm():
        ui.run_javascript("if ('Notification' in window && Notification.permission === 'default') { Notification.requestPermission(); }")
    ui.timer(0.5, _headless := (lambda: _request_notif_perm()), once=True)
    # 从队列中发送系统通知（在客户端上下文执行）
    def _drain_notifications():
        try:
            while PENDING_BROWSER_NOTIFICATIONS:
                title, body = PENDING_BROWSER_NOTIFICATIONS.pop(0)
                js = f"""
                (function() {{
                  try {{
                    if ('Notification' in window) {{
                      if (Notification.permission === 'granted') {{
                        new Notification({json.dumps(''+title)}, {{ body: {json.dumps(''+body)} }});
                      }} else if (Notification.permission === 'default') {{
                        Notification.requestPermission().then(function (perm) {{
                          if (perm === 'granted') {{
                            new Notification({json.dumps(''+title)}, {{ body: {json.dumps(''+body)} }});
                          }}
                        }});
                      }}
                    }}
                  }} catch (e) {{}}
                }})();
                """
                ui.run_javascript(js)
        except Exception:
            pass
    ui.timer(1.0, _drain_notifications)
    
    # 顶部栏
    with ui.header().classes('items-center').style('display: flex; justify-content: space-between; position: relative;'):
        # 左侧：添加主播按钮和删除按钮
        with ui.row().classes('items-center gap-2'):
            async def add_streamer():
                global STREAMERS
                with ui.dialog() as dialog, ui.card().style('width: 500px; min-height: 200px; padding: 20px;'):
                    ui.label('添加主播').classes('text-h6 mb-4')
                    username_input = ui.input('主播名字', placeholder='输入主播用户名').classes('w-full mb-4')
                    with ui.row().classes('w-full gap-2 mt-4').style('display: flex; justify-content: space-between;'):
                        async def confirm_add():
                            global STREAMERS
                            username = username_input.value.strip()
                            if not username:
                                ui.notify('请输入主播名字', type='warning')
                                return
                            
                            # 检查是否已存在
                            _, existing = find_streamer_by_username(username)
                            if existing is not None:
                                ui.notify('该主播已存在', type='warning')
                                return
                            
                            # 添加新主播（字典格式，默认 running 为 True）
                            STREAMERS.append({"username": username, "running": True})
                            save_streamers()
                            await start_monitor(username)
                            refresh_streamers_list()
                            dialog.close()
                            ui.notify(f'已添加主播: {username}', type='positive')
                        ui.button('取消', on_click=dialog.close).classes('q-btn--no-uppercase').style('flex: 1; max-width: 48%;')
                        ui.button('确定', on_click=confirm_add).classes('q-btn--no-uppercase').style('flex: 1; max-width: 48%;')
                dialog.open()
            
            ui.button('添加主播', on_click=add_streamer).classes('q-btn--no-uppercase')
            
            def toggle_delete_mode():
                global DELETE_MODE, SELECTED_STREAMERS
                DELETE_MODE = not DELETE_MODE
                SELECTED_STREAMERS.clear()
                if DELETE_MODE:
                    delete_btn.props('color=negative')
                    confirm_delete_btn.set_visibility(True)
                else:
                    delete_btn.props('color=grey-7')
                    confirm_delete_btn.set_visibility(False)
                refresh_streamers_list()
            
            async def confirm_delete():
                global DELETE_MODE, SELECTED_STREAMERS, STREAMERS
                if not SELECTED_STREAMERS:
                    ui.notify('请选择要删除的主播', type='warning')
                    return
                
                # 保存要删除的数量
                deleted_count = len(SELECTED_STREAMERS)
                selected_list = list(SELECTED_STREAMERS)
                
                # 停止选中主播的监控并删除
                for username in selected_list:
                    stop_monitor(username)
                    idx, _ = find_streamer_by_username(username)
                    if idx is not None:
                        STREAMERS.pop(idx)
                
                save_streamers()
                SELECTED_STREAMERS.clear()
                DELETE_MODE = False
                delete_btn.props('color=grey-7')
                confirm_delete_btn.set_visibility(False)
                refresh_streamers_list()
                ui.notify(f'已删除 {deleted_count} 个主播', type='positive')
            
            delete_btn = ui.button('', on_click=toggle_delete_mode).props('icon=delete flat color=grey-7').style('min-width:auto; width:auto; height:auto; padding:0 4px')
            confirm_delete_btn = ui.button('确定删除', on_click=confirm_delete).classes('q-btn--negative q-btn--no-uppercase')
            confirm_delete_btn.set_visibility(False)
        
        # 中间：标题（居中）
        ui.label('SuperChat 多房间监控').classes('text-h5 absolute left-1/2 transform -translate-x-1/2')
        
        # 右侧：全部开启/关闭按钮
        with ui.row().classes('items-center gap-2'):
            async def start_all():
                for streamer in STREAMERS:
                    username = get_streamer_username(streamer)
                    if username and not is_running(username):
                        await start_monitor(username)
            async def stop_all():
                await stop_all_monitors()
            ui.button('全部开启', on_click=start_all).classes('q-btn--no-uppercase')
            ui.button('全部关闭', on_click=stop_all).classes('q-btn--no-uppercase')

    # 主播列表容器
    STREAMERS_CONTAINER = ui.column().classes('w-full max-w-5xl mx-auto p-4 gap-2').style('padding-top:0px; margin-top:-50px')
    refresh_streamers_list()

    ui.timer(1.0, refresh_ui)


# ---------- 应用生命周期 ----------
async def _on_startup():
    await ensure_session()
    # 根据 running 状态自动启动监控
    for streamer in STREAMERS:
        username = get_streamer_username(streamer)
        if username and get_streamer_running(username):
            await start_monitor(username)


async def _on_shutdown():
    await stop_all_monitors()
    await close_session()

async def poll_superchat(username: str):
    """
    演示：使用 Playwright 获取 uniq + cookies + UA，然后用 aiohttp 复用这些信息请求 chat API。
    """
    # 先用 Playwright 抓一次
    loop = asyncio.get_event_loop()
    uniq, cookies, ua, html = await loop.run_in_executor(None, fetch_page_uniq_and_cookies, username, True, 20000)
    if not uniq:
        print(f"[{username}] 未能通过 Playwright 获取 uniq，退出演示。")
        return
    api_url = f"https://zh.superchat.live/api/front/v2/models/username/{username}/chat?source=regular&uniq={uniq}"
    cookie_header = "; ".join([f"{k}={v}" for k, v in cookies.items()])
    headers = {
        "User-Agent": ua or "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": f"https://zh.superchat.live/{username}",
        "Cookie": cookie_header,
    }

    connector = ProxyConnector.from_url(PROXY)
    async with aiohttp.ClientSession(connector=connector) as session:
        async with session.get(api_url, headers=headers, timeout=15) as resp:
            print(f"[{username}] 状态码:", resp.status)
            text_ct = resp.headers.get("Content-Type","")
            if resp.status == 200 and "application/json" in text_ct:
                data = await resp.text()
                print(f"[{username}] 数据片段:", data[:300])
            else:
                # 打印部分 HTML 或文本，方便调试
                data = await resp.text()
                print(f"[{username}] 返回内容片段:", data[:300])

async def main():
    # 多房间异步轮询：共享一个会话与代理，分别跑每个主播
    connector = ProxyConnector.from_url(PROXY) if PROXY else None
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [asyncio.create_task(poll_room(session, get_streamer_username(streamer))) 
                 for streamer in STREAMERS if get_streamer_username(streamer)]
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    build_ui()
    ui.run(
        host="0.0.0.0",
        port=8080,
        title='SuperChat 监控面板', 
        reload=False, 
        favicon=''
    )