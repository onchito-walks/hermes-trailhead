"""Contract tests for the optional Agent Reach backend.

No network and no real Agent Reach install are required: a fake executable and
an injected runner stand in for upstream.  The suite pins the safety envelope
(read-only allowlist, no shell, public-mode behaviour, untrusted registry
validation) and the attribution contract.
"""
from __future__ import annotations

from types import SimpleNamespace
import inspect
import json
import os
import pathlib
import sys
import tempfile

import pytest

from hermes_trailhead import reach_backend as reach


# ── fixtures ──────────────────────────────────────────────────────────────


def _param(name: str, *, required: bool = False, ptype: str = "str") -> dict:
    return {"name": name, "help": "", "required": required, "type": ptype, "default": None}


def registry_payload() -> dict:
    """A trimmed but shape-accurate `agent-reach channels` payload (v1.6.0)."""
    return {
        "schema_version": 1,
        "ok": True,
        "commands": {
            "read": "agent-reach read <url>  (picks the channel from the URL)",
            "action": "agent-reach <channel> <action> [args] [--timeout SECONDS]",
        },
        "channels": [
            {
                "name": "github",
                "description": "GitHub 仓库和代码",
                "level": "default",
                "login": None,
                "actions": [
                    {
                        "name": "search",
                        "help": "Search repositories",
                        "usage": "agent-reach github search <query> [--limit LIMIT]",
                        "params": [_param("query", required=True), _param("limit", ptype="int")],
                        "backends": ["gh", "github-api"],
                        "public_web": [],
                    },
                    {
                        "name": "read",
                        "help": "Read a repository or an issue / PR",
                        "usage": "agent-reach github read <target>",
                        "params": [_param("target", required=True)],
                        "backends": ["gh", "github-api"],
                        "public_web": [],
                    },
                ],
            },
            {
                "name": "v2ex",
                "description": "V2EX 节点、主题与回复",
                "level": "default",
                "login": None,
                "actions": [
                    {
                        "name": "hot",
                        "help": "Hot topics",
                        "usage": "agent-reach v2ex hot [--limit LIMIT]",
                        "params": [_param("limit", ptype="int")],
                        "backends": ["v2ex-api"],
                        "public_web": [],
                    },
                    {
                        "name": "node",
                        "help": "A node's topics",
                        "usage": "agent-reach v2ex node <node_name> [--limit LIMIT]",
                        "params": [_param("node_name", required=True), _param("limit", ptype="int")],
                        "backends": ["v2ex-api"],
                        "public_web": [],
                    },
                ],
            },
            {
                "name": "twitter",
                "description": "Twitter/X 推文",
                "level": "experimental",
                "login": {"via": "browser", "logged_in": None, "command": "agent-reach login twitter"},
                "actions": [
                    {
                        "name": "search",
                        "help": "Search tweets",
                        "usage": "agent-reach twitter search <query> [--limit LIMIT]",
                        "params": [_param("query", required=True), _param("limit", ptype="int")],
                        "backends": ["opencli"],
                        "public_web": ["x.com/", "twitter.com/"],
                    },
                    {
                        "name": "profile",
                        "help": "A user's profile",
                        "usage": "agent-reach twitter profile <username>",
                        "params": [_param("username", required=True)],
                        "backends": ["opencli"],
                        "public_web": [],
                    },
                ],
            },
            {
                "name": "bilibili",
                "description": "B站视频、字幕和搜索",
                "level": "default",
                "login": {"via": "session", "logged_in": False, "command": "agent-reach login bilibili"},
                "actions": [
                    {
                        "name": "search",
                        "help": "Search videos",
                        "usage": "agent-reach bilibili search <query> [--limit LIMIT]",
                        "params": [_param("query", required=True), _param("limit", ptype="int")],
                        "backends": ["bili-cli"],
                        "public_web": [],
                    },
                    {
                        "name": "read",
                        "help": "Read one video",
                        "usage": "agent-reach bilibili read <target>",
                        "params": [_param("target", required=True)],
                        "backends": ["bili-cli", "bilibili-api"],
                        "public_web": [],
                    },
                    {
                        "name": "hot",
                        "help": "Hot videos",
                        "usage": "agent-reach bilibili hot [--limit LIMIT]",
                        "params": [_param("limit", ptype="int")],
                        "backends": ["bili-cli", "bilibili-api"],
                        "public_web": [],
                    },
                    {
                        "name": "subtitle",
                        "help": "Video subtitles (needs the bili-cli login)",
                        "usage": "agent-reach bilibili subtitle <target>",
                        "params": [_param("target", required=True)],
                        "backends": ["bili-cli"],
                        "public_web": [],
                    },
                ],
            },
            {
                "name": "xueqiu",
                "description": "雪球股票行情与社区动态",
                "level": "optional",
                "login": {"via": "browser", "logged_in": None, "command": "agent-reach login xueqiu"},
                "actions": [
                    {
                        "name": "quote",
                        "help": "Real-time quote",
                        "usage": "agent-reach xueqiu quote <symbol>",
                        "params": [_param("symbol", required=True)],
                        "backends": ["tencent", "xueqiu-api"],
                        "public_web": [],
                    },
                    {
                        "name": "search",
                        "help": "Find stocks",
                        "usage": "agent-reach xueqiu search <query> [--limit LIMIT]",
                        "params": [_param("query", required=True), _param("limit", ptype="int")],
                        "backends": ["tencent", "xueqiu-api"],
                        "public_web": [],
                    },
                    {
                        "name": "hot_posts",
                        "help": "Trending community posts (needs a session)",
                        "usage": "agent-reach xueqiu hot_posts [--limit LIMIT]",
                        "params": [_param("limit", ptype="int")],
                        "backends": ["xueqiu-api"],
                        "public_web": [],
                    },
                    {
                        "name": "hot_stocks",
                        "help": "Most-watched stocks (needs a session)",
                        "usage": "agent-reach xueqiu hot_stocks [--limit LIMIT]",
                        "params": [_param("limit", ptype="int")],
                        "backends": ["xueqiu-api"],
                        "public_web": [],
                    },
                ],
            },
            {
                "name": "youtube",
                "description": "YouTube 视频和字幕",
                "level": "default",
                "login": None,
                "actions": [
                    {
                        "name": "transcribe",
                        "help": "Transcribe audio",
                        "usage": "agent-reach youtube transcribe <target>",
                        "params": [_param("target", required=True)],
                        "backends": ["whisper"],
                        "public_web": [],
                    }
                ],
            },
            {
                "name": "xiaoyuzhou",
                "description": "小宇宙播客转文字",
                "level": "optional",
                "login": None,
                "actions": [
                    {
                        "name": "transcribe",
                        "help": "Transcribe a podcast",
                        "usage": "agent-reach xiaoyuzhou transcribe <target>",
                        "params": [_param("target", required=True)],
                        "backends": ["groq-whisper"],
                        "public_web": [],
                    }
                ],
            },
            {
                "name": "instagram",
                "description": "Instagram 主页与帖子",
                "level": "experimental",
                "login": {"via": "browser", "logged_in": None, "command": "agent-reach login instagram"},
                "actions": [
                    {
                        "name": "profile",
                        "help": "A user's profile",
                        "usage": "agent-reach instagram profile <username>",
                        "params": [_param("username", required=True)],
                        "backends": ["opencli"],
                        "public_web": [],
                    }
                ],
            },
            {
                "name": "rogue",
                "description": "a channel Trailhead never forwards",
                "level": "optional",
                "login": None,
                "actions": [
                    {
                        "name": "search",
                        "help": "not allowlisted",
                        "usage": "agent-reach rogue search <query>",
                        "params": [_param("query", required=True)],
                        "backends": ["opencli"],
                        "public_web": [],
                    }
                ],
            },
        ],
    }


def _p(name: str, help: str, *, required: bool = False, type: str = "str", default=None) -> dict:
    """One param declaration in the pinned registry shape."""
    return {"name": name, "help": help, "required": required, "type": type, "default": default}


def pinned_registry_payload() -> dict:
    """Exact ``agent-reach channels`` payload for Agent Reach 1.6.0 @ 14c2134.

    Transcribed field for field from the pinned upstream registry (14 channels,
    40 actions), not from this package's own inventory: a parity test that read
    the inventory back would prove nothing.  No network access is involved.
    """
    return {
        "schema_version": 1,
        "ok": True,
        "commands": {
            "read": "agent-reach read <url>  (picks the channel from the URL)",
            "action": "agent-reach <channel> <action> [args] [--timeout SECONDS]",
        },
        "channels": [
            {
                "name": "github",
                "description": "GitHub 仓库和代码",
                "level": "default",
                "login": None,
                "actions": [
                    {
                        "name": "search",
                        "help": "Search repositories",
                        "usage": "agent-reach github search <query> [--limit LIMIT]",
                        "params": [_p("query", "what to search for", required=True), _p("limit", "max results", type="int", default=5)],
                        "backends": ["gh", "github-api"],
                        "public_web": [],
                    },
                    {
                        "name": "read",
                        "help": "Read a repository (with README) or an issue / PR (with comments)",
                        "usage": "agent-reach github read <target>",
                        "params": [_p("target", "owner/repo, or a repo / issue / PR link", required=True)],
                        "backends": ["gh", "github-api"],
                        "public_web": [],
                    },
                ],
            },
            {
                "name": "twitter",
                "description": "Twitter/X 推文",
                "level": "experimental",
                "login": {"via": "browser", "logged_in": None, "command": "agent-reach login twitter"},
                "actions": [
                    {
                        "name": "search",
                        "help": "Search tweets",
                        "usage": "agent-reach twitter search <query> [--limit LIMIT]",
                        "params": [_p("query", "what to search for", required=True), _p("limit", "max results", type="int", default=5)],
                        "backends": ["opencli"],
                        "public_web": ["x.com/", "twitter.com/"],
                    },
                    {
                        "name": "profile",
                        "help": "A user's profile",
                        "usage": "agent-reach twitter profile <username>",
                        "params": [_p("username", "handle without @", required=True)],
                        "backends": ["opencli"],
                        "public_web": [],
                    },
                    {
                        "name": "tweets",
                        "help": "A user's recent tweets",
                        "usage": "agent-reach twitter tweets <username> [--limit LIMIT]",
                        "params": [_p("username", "handle without @", required=True), _p("limit", "max tweets", type="int", default=5)],
                        "backends": ["opencli"],
                        "public_web": [],
                    },
                    {
                        "name": "thread",
                        "help": "A tweet with its replies",
                        "usage": "agent-reach twitter thread <target>",
                        "params": [_p("target", "tweet id or link", required=True)],
                        "backends": ["opencli"],
                        "public_web": [],
                    },
                ],
            },
            {
                "name": "youtube",
                "description": "YouTube 视频和字幕",
                "level": "default",
                "login": None,
                "actions": [
                    {
                        "name": "read",
                        "help": "Video title, channel, date and description",
                        "usage": "agent-reach youtube read <target>",
                        "params": [_p("target", "video link or id", required=True)],
                        "backends": ["yt-dlp"],
                        "public_web": [],
                    },
                    {
                        "name": "search",
                        "help": "Search videos",
                        "usage": "agent-reach youtube search <query> [--limit LIMIT]",
                        "params": [_p("query", "what to search for", required=True), _p("limit", "max results", type="int", default=5)],
                        "backends": ["yt-dlp"],
                        "public_web": [],
                    },
                    {
                        "name": "subtitle",
                        "help": "Full subtitle text of a video (manual or auto captions)",
                        "usage": "agent-reach youtube subtitle <target> [--lang LANG]",
                        "params": [_p("target", "video link or id", required=True), _p("lang", "preferred languages, comma separated", default="zh-Hans,zh,en,en-orig")],
                        "backends": ["yt-dlp"],
                        "public_web": [],
                    },
                    {
                        "name": "transcribe",
                        "help": "Speech-to-text of a video's audio (uses Groq/OpenAI Whisper quota)",
                        "usage": "agent-reach youtube transcribe <target>",
                        "params": [_p("target", "video link or id", required=True)],
                        "backends": ["whisper"],
                        "public_web": [],
                    },
                ],
            },
            {
                "name": "reddit",
                "description": "Reddit 帖子和评论",
                "level": "optional",
                "login": {"via": "browser", "logged_in": None, "command": "agent-reach login reddit"},
                "actions": [
                    {
                        "name": "search",
                        "help": "Search public posts first; --backend opencli uses site search",
                        "usage": "agent-reach reddit search <query> [--limit LIMIT]",
                        "params": [_p("query", "what to search for", required=True), _p("limit", "max results", type="int", default=5)],
                        "backends": ["opencli"],
                        "public_web": ["reddit.com/r/"],
                    },
                    {
                        "name": "read",
                        "help": "Read public page text first; --backend opencli requests the post and top comments",
                        "usage": "agent-reach reddit read <target>",
                        "params": [_p("target", "post link or id", required=True)],
                        "backends": ["opencli"],
                        "public_web": ["reddit.com/r/", "redd.it/"],
                    },
                    {
                        "name": "subreddit",
                        "help": "Latest posts in a subreddit",
                        "usage": "agent-reach reddit subreddit <name> [--limit LIMIT]",
                        "params": [_p("name", "subreddit name without r/, e.g. python", required=True), _p("limit", "max posts", type="int", default=5)],
                        "backends": ["opencli"],
                        "public_web": [],
                    },
                ],
            },
            {
                "name": "facebook",
                "description": "Facebook 帖子、主页和群组",
                "level": "experimental",
                "login": {"via": "browser", "logged_in": None, "command": "agent-reach login facebook"},
                "actions": [
                    {
                        "name": "search",
                        "help": "Search Facebook",
                        "usage": "agent-reach facebook search <query> [--limit LIMIT]",
                        "params": [_p("query", "what to search for", required=True), _p("limit", "max results", type="int", default=5)],
                        "backends": ["opencli"],
                        "public_web": ["facebook.com/"],
                    },
                    {
                        "name": "profile",
                        "help": "A user's or page's profile",
                        "usage": "agent-reach facebook profile <username>",
                        "params": [_p("username", "username or page name", required=True)],
                        "backends": ["opencli"],
                        "public_web": [],
                    },
                ],
            },
            {
                "name": "instagram",
                "description": "Instagram 用户、主页和指定用户帖子",
                "level": "experimental",
                "login": {"via": "browser", "logged_in": None, "command": "agent-reach login instagram"},
                "actions": [
                    {
                        "name": "search",
                        "help": "Search users (not posts)",
                        "usage": "agent-reach instagram search <query> [--limit LIMIT]",
                        "params": [_p("query", "what to search for", required=True), _p("limit", "max results", type="int", default=5)],
                        "backends": ["opencli"],
                        "public_web": [],
                    },
                    {
                        "name": "profile",
                        "help": "A user's profile",
                        "usage": "agent-reach instagram profile <username>",
                        "params": [_p("username", "Instagram username", required=True)],
                        "backends": ["opencli"],
                        "public_web": [],
                    },
                    {
                        "name": "posts",
                        "help": "A user's recent posts",
                        "usage": "agent-reach instagram posts <username> [--limit LIMIT]",
                        "params": [_p("username", "Instagram username", required=True), _p("limit", "max posts", type="int", default=6)],
                        "backends": ["opencli"],
                        "public_web": [],
                    },
                ],
            },
            {
                "name": "bilibili",
                "description": "B站视频、字幕和搜索",
                "level": "default",
                "login": {"via": "session", "logged_in": False, "command": "agent-reach login bilibili"},
                "actions": [
                    {
                        "name": "search",
                        "help": "Search videos",
                        "usage": "agent-reach bilibili search <query> [--limit LIMIT]",
                        "params": [_p("query", "what to search for", required=True), _p("limit", "max results", type="int", default=5)],
                        "backends": ["bili-cli"],
                        "public_web": [],
                    },
                    {
                        "name": "read",
                        "help": "Video title, uploader, description and stats",
                        "usage": "agent-reach bilibili read <target>",
                        "params": [_p("target", "BV id or video link", required=True)],
                        "backends": ["bili-cli", "bilibili-api"],
                        "public_web": [],
                    },
                    {
                        "name": "hot",
                        "help": "Trending videos",
                        "usage": "agent-reach bilibili hot [--limit LIMIT]",
                        "params": [_p("limit", "max items", type="int", default=10)],
                        "backends": ["bili-cli", "bilibili-api"],
                        "public_web": [],
                    },
                    {
                        "name": "subtitle",
                        "help": "Subtitle text of the first video part, when available (may need a Bilibili login)",
                        "usage": "agent-reach bilibili subtitle <target>",
                        "params": [_p("target", "BV id or video link", required=True)],
                        "backends": ["bili-cli"],
                        "public_web": [],
                    },
                ],
            },
            {
                "name": "xiaohongshu",
                "description": "小红书笔记",
                "level": "optional",
                "login": {"via": "browser", "logged_in": None, "command": "agent-reach login xiaohongshu"},
                "actions": [
                    {
                        "name": "search",
                        "help": "Search notes",
                        "usage": "agent-reach xiaohongshu search <query> [--limit LIMIT]",
                        "params": [_p("query", "what to search for", required=True), _p("limit", "max results", type="int", default=5)],
                        "backends": ["opencli"],
                        "public_web": ["xiaohongshu.com/explore/", "xiaohongshu.com/search_result/", "xhslink.com/"],
                    },
                    {
                        "name": "read",
                        "help": "Read a note (full link including xsec_token, as returned by search)",
                        "usage": "agent-reach xiaohongshu read <target>",
                        "params": [_p("target", "full note link with xsec_token", required=True)],
                        "backends": ["opencli"],
                        "public_web": ["xiaohongshu.com/explore/", "xiaohongshu.com/search_result/", "xhslink.com/"],
                    },
                    {
                        "name": "comments",
                        "help": "Read loaded comments and replies from a note; not an exhaustive export",
                        "usage": "agent-reach xiaohongshu comments <target> [--limit LIMIT]",
                        "params": [_p("target", "full note link with xsec_token", required=True), _p("limit", "max top-level comments (1..50); loaded replies are included", type="int", default=20)],
                        "backends": ["opencli"],
                        "public_web": [],
                    },
                ],
            },
            {
                "name": "linkedin",
                "description": "LinkedIn 职位搜索与详情",
                "level": "optional",
                "login": {"via": "browser", "logged_in": None, "command": "agent-reach login linkedin"},
                "actions": [
                    {
                        "name": "jobs",
                        "help": "Search LinkedIn jobs",
                        "usage": "agent-reach linkedin jobs <query> [--location LOCATION] [--limit LIMIT]",
                        "params": [_p("query", "job keywords", required=True), _p("location", "city or country"), _p("limit", "max results", type="int", default=5)],
                        "backends": ["opencli"],
                        "public_web": ["linkedin.com/jobs/view/"],
                    },
                    {
                        "name": "read",
                        "help": "Read a LinkedIn job description",
                        "usage": "agent-reach linkedin read <target>",
                        "params": [_p("target", "full job URL", required=True)],
                        "backends": ["opencli"],
                        "public_web": ["linkedin.com/jobs/view/"],
                    },
                ],
            },
            {
                "name": "boss",
                "description": "Boss直聘 职位搜索与 JD",
                "level": "optional",
                "login": {"via": "browser", "logged_in": None, "command": "agent-reach login boss"},
                "actions": [
                    {
                        "name": "search",
                        "help": "Search jobs using a configured browser session",
                        "usage": "agent-reach boss search <query> [--city CITY] [--limit LIMIT]",
                        "params": [_p("query", "job keywords", required=True), _p("city", "city, e.g. 深圳"), _p("limit", "max results", type="int", default=10)],
                        "backends": ["opencli", "boss-agent-cli"],
                        "public_web": ["zhipin.com/job_detail/"],
                    },
                    {
                        "name": "read",
                        "help": "Read a direct BOSS job URL",
                        "usage": "agent-reach boss read <target>",
                        "params": [_p("target", "full job URL", required=True)],
                        "backends": ["boss-agent-cli", "opencli"],
                        "public_web": ["zhipin.com/job_detail/"],
                    },
                ],
            },
            {
                "name": "v2ex",
                "description": "V2EX 节点、主题与回复",
                "level": "default",
                "login": None,
                "actions": [
                    {
                        "name": "hot",
                        "help": "Today's hot topics",
                        "usage": "agent-reach v2ex hot [--limit LIMIT]",
                        "params": [_p("limit", "max items", type="int", default=10)],
                        "backends": ["v2ex-api"],
                        "public_web": [],
                    },
                    {
                        "name": "node",
                        "help": "Latest topics in a node",
                        "usage": "agent-reach v2ex node <node_name> [--limit LIMIT]",
                        "params": [_p("node_name", "node name, e.g. python, programmer, jobs", required=True), _p("limit", "max items", type="int", default=10)],
                        "backends": ["v2ex-api"],
                        "public_web": [],
                    },
                    {
                        "name": "read",
                        "help": "Read a topic and its replies",
                        "usage": "agent-reach v2ex read <target>",
                        "params": [_p("target", "topic link or id", required=True)],
                        "backends": ["v2ex-api"],
                        "public_web": [],
                    },
                    {
                        "name": "user",
                        "help": "A member's profile",
                        "usage": "agent-reach v2ex user <username>",
                        "params": [_p("username", "V2EX username", required=True)],
                        "backends": ["v2ex-api"],
                        "public_web": [],
                    },
                ],
            },
            {
                "name": "xueqiu",
                "description": "雪球股票行情与社区动态",
                "level": "optional",
                "login": {"via": "browser", "logged_in": None, "command": "agent-reach login xueqiu"},
                "actions": [
                    {
                        "name": "quote",
                        "help": "Real-time stock quote (A-share, HK, US)",
                        "usage": "agent-reach xueqiu quote <symbol>",
                        "params": [_p("symbol", "e.g. SH600519, 600519, 00700, AAPL", required=True)],
                        "backends": ["tencent", "xueqiu-api"],
                        "public_web": [],
                    },
                    {
                        "name": "search",
                        "help": "Find stocks by name or code",
                        "usage": "agent-reach xueqiu search <query> [--limit LIMIT]",
                        "params": [_p("query", "name or code, e.g. 茅台", required=True), _p("limit", "max results", type="int", default=5)],
                        "backends": ["tencent", "xueqiu-api"],
                        "public_web": [],
                    },
                    {
                        "name": "hot_posts",
                        "help": "Trending Xueqiu community posts (needs a browser session)",
                        "usage": "agent-reach xueqiu hot_posts [--limit LIMIT]",
                        "params": [_p("limit", "max items", type="int", default=10)],
                        "backends": ["xueqiu-api"],
                        "public_web": [],
                    },
                    {
                        "name": "hot_stocks",
                        "help": "Most-watched stocks on Xueqiu (needs a browser session)",
                        "usage": "agent-reach xueqiu hot_stocks [--limit LIMIT]",
                        "params": [_p("limit", "max items", type="int", default=10)],
                        "backends": ["xueqiu-api"],
                        "public_web": [],
                    },
                ],
            },
            {
                "name": "xiaoyuzhou",
                "description": "小宇宙播客转文字",
                "level": "optional",
                "login": None,
                "actions": [
                    {
                        "name": "transcribe",
                        "help": "Full transcript of a podcast episode (uses Groq Whisper quota)",
                        "usage": "agent-reach xiaoyuzhou transcribe <target>",
                        "params": [_p("target", "episode link", required=True)],
                        "backends": ["groq-whisper"],
                        "public_web": [],
                    },
                ],
            },
            {
                "name": "web",
                "description": "网页搜索与阅读（Agent 自带工具不可用时的保底）",
                "level": "default",
                "login": None,
                "actions": [
                    {
                        "name": "search",
                        "help": "Search the web (Exa semantic search)",
                        "usage": "agent-reach web search <query> [--limit LIMIT]",
                        "params": [_p("query", "what to search for", required=True), _p("limit", "max results", type="int", default=5)],
                        "backends": ["exa"],
                        "public_web": [],
                    },
                    {
                        "name": "read",
                        "help": "Read a web page as clean text",
                        "usage": "agent-reach web read <target>",
                        "params": [_p("target", "page URL", required=True)],
                        "backends": ["jina", "exa"],
                        "public_web": [],
                    },
                ],
            },
        ],
    }


#: Backend label a cooperating upstream reports for each channel's default
#: route.  Forced-route tests override it to simulate a mismatched upstream.
DEFAULT_BACKEND = {
    "github": "github-api",
    "v2ex": "v2ex-api",
    "bilibili": "bilibili-api",
    "xueqiu": "tencent",
    "twitter": "public-web",
}


def ok_envelope(channel: str, action: str, *, items=None, backend=None, attempts=None) -> dict:
    if backend is None:
        backend = DEFAULT_BACKEND.get(channel, "public-web")
    return {
        "schema_version": 1,
        "ok": True,
        "channel": channel,
        "action": action,
        "backend": backend,
        "items": items
        if items is not None
        else [
            {
                "title": "thedevs-network/kutt",
                "url": "https://github.com/thedevs-network/kutt",
                "author": "thedevs-network",
                "published_at": "2018-02-13T12:33:16Z",
                "text": "Free Modern URL Shortener.",
                "raw": {"stargazers_count": 11179},
            }
        ],
        "meta": {
            "elapsed_ms": 332,
            "attempts": attempts
            if attempts is not None
            else [{"backend": "gh", "result": "NEED_SETUP", "message": "no credentials"},
                  {"backend": "github-api", "result": "ok"}],
        },
        "error": None,
    }


def error_envelope(channel: str, action: str, code="UPSTREAM_BROKEN", message="boom", hint="") -> dict:
    return {
        "schema_version": 1,
        "ok": False,
        "channel": channel,
        "action": action,
        "backend": None,
        "items": [],
        "meta": {"elapsed_ms": 12, "attempts": []},
        "error": {"code": code, "message": message, "hint": hint},
    }


class FakeRunner:
    """Records argv/timeout/env and replays a queued upstream response."""

    def __init__(self, payload=None, *, action_response=None, raise_timeout=False):
        self.payload = payload if payload is not None else registry_payload()
        self.action_response = action_response
        self.raise_timeout = raise_timeout
        self.calls: list[dict] = []

    def __call__(self, argv, *, timeout, env):
        self.calls.append({"argv": list(argv), "timeout": timeout, "env": dict(env)})
        if list(argv)[1:] == ["channels"]:
            return SimpleNamespace(returncode=0, stdout=json.dumps(self.payload, ensure_ascii=False), stderr="")
        if self.raise_timeout:
            raise __import__("subprocess").TimeoutExpired(argv, timeout)
        response = self.action_response
        if response is None:
            response = ok_envelope(argv[1], argv[2], backend=self.forced_backend(argv))
        if isinstance(response, str):
            return SimpleNamespace(returncode=0, stdout=response, stderr="")
        return SimpleNamespace(returncode=0, stdout=json.dumps(response, ensure_ascii=False), stderr="")

    @staticmethod
    def forced_backend(argv) -> str | None:
        """Real upstream echoes the pinned label; None means 'pick the default'."""
        argv = list(argv)
        if "--backend" in argv:
            return argv[argv.index("--backend") + 1]
        return None

    @property
    def action_calls(self) -> list[dict]:
        return [c for c in self.calls if c["argv"][1:2] != ["channels"]]


@pytest.fixture()
def backend_factory(tmp_path_factory):
    stub = tmp_path_factory.mktemp("agent-reach") / "agent-reach"
    stub.write_text("#!/usr/bin/env python3\n")
    stub.chmod(0o755)

    def make(payload=None, *, action_response=None, raise_timeout=False, executable=None, **kwargs):
        runner = FakeRunner(payload, action_response=action_response, raise_timeout=raise_timeout)
        backend = reach.AgentReachBackend(str(stub) if executable is None else executable, runner=runner, **kwargs)
        return backend, runner

    return make


# ── discovery ─────────────────────────────────────────────────────────────


def test_discover_prefers_explicit_then_env_then_path(tmp_path):
    exe = tmp_path / "agent-reach"
    exe.write_text("#!/bin/sh\nexit 0\n")
    exe.chmod(0o755)
    other = tmp_path / "other-agent-reach"
    other.write_text("#!/bin/sh\nexit 0\n")
    other.chmod(0o755)

    found = reach.discover_agent_reach(str(exe), env={reach.AGENT_REACH_ENV: str(other)})
    assert found.found is True
    assert found.path == str(exe)
    assert found.reason == "explicit_ok"

    found = reach.discover_agent_reach(None, env={reach.AGENT_REACH_ENV: str(other)})
    assert found.path == str(other)
    assert found.reason == "env_ok"

    found = reach.discover_agent_reach(None, env={}, which=lambda name: str(exe) if name == "agent-reach" else None)
    assert found.path == str(exe)
    assert found.reason == "path_ok"


def test_discover_reports_missing_and_non_executable(tmp_path):
    missing = reach.discover_agent_reach(str(tmp_path / "nope"), env={})
    assert missing.found is False
    assert missing.reason == "explicit_missing"

    plain = tmp_path / "plain"
    plain.write_text("not executable")
    plain.chmod(0o644)
    found = reach.discover_agent_reach(str(plain), env={})
    assert found.found is False
    assert found.reason == "explicit_not_executable"

    directory = tmp_path / "dir"
    directory.mkdir()
    found = reach.discover_agent_reach(str(directory), env={})
    assert found.found is False
    assert found.reason == "explicit_is_directory"

    not_installed = reach.discover_agent_reach(None, env={}, which=lambda name: None)
    assert not_installed.found is False
    assert not_installed.reason == "not_installed"


def test_params_must_be_a_mapping(backend_factory):
    backend, runner = backend_factory()
    result = backend.execute("github", "search", ["query"])  # type: ignore[arg-type]
    assert result.ok is False
    assert result.error["code"] == "invalid_params"
    assert runner.action_calls == []


def test_discover_accepts_pathlib_and_relative_names(tmp_path):
    exe = tmp_path / "agent-reach"
    exe.write_text("#!/bin/sh\nexit 0\n")
    exe.chmod(0o755)
    found = reach.discover_agent_reach(exe)  # type: ignore[arg-type]
    assert found.found is True
    assert found.path == str(exe)

    found = reach.discover_agent_reach("agent-reach", env={}, which=lambda name: str(exe))
    assert found.found is True
    assert found.reason == "explicit_ok"


# ── untrusted registry validation ─────────────────────────────────────────


def test_parse_registry_accepts_real_shape():
    registry = reach.parse_registry(registry_payload())
    assert registry.schema_version == 1
    assert set(registry.channels) >= {"github", "v2ex", "twitter", "bilibili"}
    github = registry.channels["github"]
    assert github.login_via is None
    assert github.actions["search"].required_params[0].name == "query"
    assert github.actions["search"].optional_params[0].type == "int"


@pytest.mark.parametrize(
    "mutate, needle",
    [
        (lambda p: p.update(schema_version=2), "schema_version"),
        (lambda p: p.update(schema_version=True), "schema_version"),
        (lambda p: p.update(ok=False), "ok=true"),
        (lambda p: p.update(channels=None), "channel list"),
        (lambda p: p.update(channels=[]), "channel list"),
        (lambda p: p["channels"].append(dict(p["channels"][0])), "duplicate channel"),
        (lambda p: p["channels"][0].update(name="Bad Name"), "invalid channel name"),
        (lambda p: p["channels"][0].update(name="github;rm -rf /"), "invalid channel name"),
        (lambda p: p["channels"][0].update(actions=[]), "no actions"),
        (lambda p: p["channels"][0].update(login={"via": "cookie"}), "login.via"),
        (lambda p: p["channels"][0].update(login={"via": "browser", "logged_in": "yes"}), "logged_in"),
        (lambda p: p["channels"][0]["actions"][0].update(params="query"), "params"),
        (lambda p: p["channels"][0]["actions"][0].update(public_web="x.com"), "public_web"),
        (lambda p: p["channels"][0]["actions"][0].update(public_web=["bad prefix"]), "public_web"),
        (lambda p: p["channels"][0]["actions"][0].update(backends=["ok", "bad label!"]), "backend label"),
        (lambda p: p["channels"][0]["actions"][0]["params"][0].update(required="yes"), "required"),
        (lambda p: p["channels"][0]["actions"][0]["params"][0].update(type="dict"), "type"),
        (lambda p: p["channels"][0]["actions"][0]["params"].append(dict(p["channels"][0]["actions"][0]["params"][0])), "duplicate param"),
    ],
)
def test_parse_registry_rejects_malformed_payloads(mutate, needle):
    payload = registry_payload()
    mutate(payload)
    with pytest.raises(reach.RegistryError) as excinfo:
        reach.parse_registry(payload)
    assert needle in str(excinfo.value)


def test_malformed_channels_output_never_spawns_an_action(backend_factory):
    backend, runner = backend_factory(action_response="this is not json")
    runner.payload = {"schema_version": 1, "ok": False, "channels": []}
    result = backend.execute("github", "search", {"query": "rust"})
    assert result.ok is False
    assert result.error["code"] == "registry_invalid"
    assert runner.action_calls == []


# ── allowlist / forbidden surface ─────────────────────────────────────────


def test_unknown_channel_and_action_are_rejected_without_spawning(backend_factory):
    backend, runner = backend_factory()
    unknown_channel = backend.execute("myspace", "search", {"query": "x"})
    assert unknown_channel.error["code"] == "unknown_channel"

    unknown_action = backend.execute("github", "delete", {"query": "x"})
    assert unknown_action.error["code"] == "unknown_action"
    assert runner.action_calls == []


@pytest.mark.parametrize("channel", ["login", "setup", "browser", "configure", "update", "uninstall", "skill", "read", "doctor"])
def test_management_verbs_are_rejected_as_channels(backend_factory, channel):
    backend, runner = backend_factory()
    result = backend.execute(channel, "search", {"query": "x"})
    assert result.ok is False
    assert result.error["code"] == "forbidden_command"
    assert runner.action_calls == []


def test_registry_action_outside_allowlist_is_rejected(backend_factory):
    backend, runner = backend_factory()
    result = backend.execute("rogue", "search", {"query": "x"})
    assert result.error["code"] == "action_not_allowlisted"
    assert runner.action_calls == []


def test_transcription_is_discoverable_but_never_runs_by_default(backend_factory):
    """The gap is advertised; the billable call is not."""
    backend, runner = backend_factory()
    for channel in ("youtube", "xiaoyuzhou"):
        result = backend.execute(channel, "transcribe", {"target": "abc"})
        assert result.ok is False
        assert result.error["code"] == "quota_required"
        assert "--allow-quota-consuming" in result.error["message"]
        assert result.provenance["quota_consuming"] is True
        assert result.provenance["route"] is None
    assert runner.calls == []  # not even the registry was read


def test_allowlist_contains_no_mutating_or_quota_actions():
    names = {a for actions in reach.READ_ONLY_ACTION_ALLOWLIST.values() for a in actions}
    assert names.isdisjoint(reach.FORBIDDEN_ACTIONS)
    assert "transcribe" not in names
    assert "xiaoyuzhou" not in reach.READ_ONLY_ACTION_ALLOWLIST
    # ...but transcription is discoverable through its own allowlist.
    assert reach.DISCOVERABLE_ACTION_ALLOWLIST["youtube"] >= {"transcribe"}
    assert reach.DISCOVERABLE_ACTION_ALLOWLIST["xiaoyuzhou"] == frozenset({"transcribe"})


# ── public mode ───────────────────────────────────────────────────────────


def test_public_mode_forces_public_web_backend(backend_factory):
    backend, runner = backend_factory(
        action_response=ok_envelope("twitter", "search", backend="public-web/exa", items=[])
    )
    result = backend.execute("twitter", "search", {"query": "rust lang", "limit": 2})
    assert result.ok is True
    argv = runner.action_calls[0]["argv"]
    assert argv[1:3] == ["twitter", "search"]
    assert ["--backend", "public-web"] == argv[argv.index("--backend"): argv.index("--backend") + 2]
    assert ["--limit", "2"] == argv[argv.index("--limit"): argv.index("--limit") + 2]
    assert argv[-2:] == ["--", "rust lang"]
    assert result.provenance["route"] == "public_web"
    assert result.provenance["forced_backend"] == "public-web"
    assert result.provenance["public_only"] is True


@pytest.mark.parametrize(
    "channel, action, params, label",
    [
        ("github", "search", {"query": "rust"}, "github-api"),
        ("github", "read", {"target": "owner/repo"}, "github-api"),
        ("v2ex", "hot", {"limit": 3}, "v2ex-api"),
        ("v2ex", "node", {"node_name": "python", "limit": 1}, "v2ex-api"),
        ("bilibili", "hot", {"limit": 1}, "bilibili-api"),
        ("bilibili", "read", {"target": "BV1xx411c7mD"}, "bilibili-api"),
        ("bilibili", "search", {"query": "rust", "limit": 1}, "bili-cli"),
        ("xueqiu", "quote", {"symbol": "SH600519"}, "tencent"),
        ("xueqiu", "search", {"query": "茅台", "limit": 1}, "tencent"),
    ],
)
def test_public_mode_forces_the_per_action_public_backend(
    backend_factory, channel, action, params, label
):
    """Public CN/API actions are reachable without consent via a pinned backend."""
    backend, runner = backend_factory()
    result = backend.execute(channel, action, params)
    assert result.ok is True, result.error
    argv = runner.action_calls[0]["argv"]
    assert argv[argv.index("--backend") + 1] == label
    assert result.provenance["route"] == "public_api"
    assert result.provenance["forced_backend"] == label
    assert result.provenance["public_only"] is True
    assert result.backend == label


def test_public_chinese_channels_need_no_login(backend_factory):
    """A declared session/browser login must not gate public actions."""
    backend, runner = backend_factory()
    for channel, action, params in (
        ("bilibili", "hot", {"limit": 1}),
        ("bilibili", "read", {"target": "BV1xx411c7mD"}),
        ("xueqiu", "quote", {"symbol": "SH600519"}),
    ):
        result = backend.execute(channel, action, params)
        assert result.ok is True, (channel, action, result.error)
    assert len(runner.action_calls) == 3
    assert all("--backend" in call["argv"] for call in runner.action_calls)


@pytest.mark.parametrize(
    "channel, action, params",
    [
        ("bilibili", "subtitle", {"target": "BV1xx411c7mD"}),
        ("xueqiu", "hot_posts", {"limit": 1}),
        ("xueqiu", "hot_stocks", {"limit": 1}),
        ("twitter", "profile", {"username": "nasa"}),
        ("instagram", "profile", {"username": "nasa"}),
    ],
)
def test_session_only_actions_require_explicit_consent(backend_factory, channel, action, params):
    backend, runner = backend_factory()
    result = backend.execute(channel, action, params)
    assert result.ok is False
    assert result.error["code"] == "auth_required"
    assert "allow_authenticated=True" in result.error["message"]
    assert result.provenance["route"] == "authenticated"
    assert result.provenance["forced_backend"] is None
    assert runner.action_calls == []


def test_authenticated_consent_runs_without_public_web(backend_factory):
    backend, runner = backend_factory(action_response=ok_envelope("bilibili", "subtitle", backend="bili-cli", items=[]))
    result = backend.execute("bilibili", "subtitle", {"target": "BV1xx411c7mD"}, allow_authenticated=True)
    assert result.ok is True
    argv = runner.action_calls[0]["argv"]
    assert "--backend" not in argv
    assert result.provenance["public_only"] is False
    assert result.provenance["home_mode"] == "operator"
    assert any("allow_authenticated=True" in line for line in result.limitations)


def test_consent_constructor_flag_also_allows_session_actions(backend_factory):
    backend, runner = backend_factory(
        action_response=ok_envelope("xueqiu", "hot_posts", backend="xueqiu-api", items=[]),
        allow_authenticated=True,
    )
    result = backend.execute("xueqiu", "hot_posts", {"limit": 1})
    assert result.ok is True
    assert result.provenance["public_only"] is False
    assert "--backend" not in runner.action_calls[0]["argv"]


# ── public mode runs blind (B1) ───────────────────────────────────────────


def test_public_mode_ignores_the_operator_home_and_home_override(backend_factory, tmp_path):
    op_home = tmp_path / "operator-home"
    (op_home / ".agent-reach").mkdir(parents=True)
    (op_home / ".agent-reach" / "config.yaml").write_text("xueqiu_cookie: secret\n")
    (op_home / ".config" / "gh").mkdir(parents=True)
    (op_home / ".config" / "gh" / "hosts.yml").write_text("oauth_token: secret\n")
    backend, runner = backend_factory(
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(op_home),
            "TRAILHEAD_AGENT_REACH_HOME": str(op_home),
            "XDG_CONFIG_HOME": str(op_home / ".config"),
            "GH_TOKEN": "secret",
        }
    )
    result = backend.execute("github", "search", {"query": "rust"})
    assert result.ok is True
    for call in runner.calls:  # registry call and action call alike
        env = call["env"]
        home = env["HOME"]
        assert home != str(op_home)
        assert pathlib.Path(home).is_absolute()
        assert not str(home).startswith(str(op_home))
        assert env["USERPROFILE"] == home
        assert env["XDG_CONFIG_HOME"] != str(op_home / ".config")
        assert str(env["XDG_CONFIG_HOME"]).startswith(home)
        assert str(env["XDG_CACHE_HOME"]).startswith(home)
        assert str(env["XDG_DATA_HOME"]).startswith(home)
        assert str(env["XDG_STATE_HOME"]).startswith(home)
        assert "GH_TOKEN" not in env
    assert result.provenance["home_mode"] == "isolated-temp"
    assert reach.LIMITATION_PUBLIC_HOME in result.limitations


def test_public_home_is_empty_and_removed_after_the_call(backend_factory, tmp_path):
    observed = {}

    backend, runner = backend_factory(env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})
    original = runner.__call__

    def spying(argv, *, timeout, env):
        if list(argv)[1:2] != ["channels"]:
            observed["home"] = env["HOME"]
            observed["entries"] = sorted(os.listdir(env["HOME"]))
            observed["exists"] = os.path.isdir(env["HOME"])
        return original(argv, timeout=timeout, env=env)

    backend._runner = spying
    result = backend.execute("github", "search", {"query": "rust"})
    assert result.ok is True
    assert observed["exists"] is True
    assert observed["entries"] == []  # fresh, no operator config copied in
    assert not os.path.exists(observed["home"])  # cleaned up on return


def test_public_home_is_cleaned_up_on_upstream_failure(tmp_path):
    exe = tmp_path / "agent-reach"
    exe.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"PAYLOAD = {registry_payload()!r}\n"
        "if sys.argv[1:2] == ['channels']:\n"
        "    print(json.dumps(PAYLOAD))\n"
        "    sys.exit(0)\n"
        "import os\n"
        "print(os.environ['HOME'], file=sys.stderr)\n"
        "sys.exit(3)\n"
    )
    exe.chmod(0o755)
    backend = reach.AgentReachBackend(str(exe), env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})
    result = backend.execute("github", "search", {"query": "rust"})
    assert result.ok is False
    assert result.error["code"] == "malformed_output"
    reported_home = result.error["message"].rsplit(": ", 1)[-1].strip()
    assert reported_home.startswith(os.sep) and reported_home != str(tmp_path)
    assert result.provenance["home_mode"] == "isolated-temp"
    assert not os.path.exists(reported_home)


def test_authenticated_mode_uses_the_configured_home(tmp_path):
    exe = tmp_path / "agent-reach"
    exe.write_text("#!/usr/bin/env python3\n")
    exe.chmod(0o755)
    seen = {}

    def spy(argv, *, timeout, env):
        seen.update(env)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(ok_envelope("bilibili", "subtitle", backend="bili-cli", items=[])),
            stderr="",
        )

    backend = reach.AgentReachBackend(
        str(exe),
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path / "op"), "TRAILHEAD_AGENT_REACH_HOME": str(tmp_path / "alt")},
        runner=spy,
        allow_authenticated=True,
    )
    backend.execute("bilibili", "subtitle", {"target": "BV1xx411c7mD"})
    assert seen["HOME"] == str(tmp_path / "alt")
    # the override isolates the whole config surface, not just HOME
    assert seen["XDG_CONFIG_HOME"] == str(tmp_path / "alt" / ".config")
    assert seen["USERPROFILE"] == str(tmp_path / "alt")


# ── forced-route verification (B2) ───────────────────────────────────────


def test_backend_mismatch_is_a_route_violation(backend_factory):
    """A payload from a different route must not be forwarded as success."""
    backend, runner = backend_factory(action_response=ok_envelope("v2ex", "hot", backend="opencli"))
    result = backend.execute("v2ex", "hot", {"limit": 2})
    assert result.ok is False
    assert result.error["code"] == "route_violation"
    assert "opencli" in result.error["message"] and "v2ex-api" in result.error["message"]
    assert result.items == ()
    assert result.provenance["forced_backend"] == "v2ex-api"
    assert result.provenance["reported_backend"] == "opencli"


def test_missing_reported_backend_on_a_forced_route_is_a_violation(backend_factory):
    envelope = ok_envelope("xueqiu", "quote", items=[])
    envelope["backend"] = None
    backend, _ = backend_factory(action_response=envelope)
    result = backend.execute("xueqiu", "quote", {"symbol": "SH600519"})
    assert result.ok is False
    assert result.error["code"] == "route_violation"
    assert result.items == ()


def test_public_web_route_accepts_its_own_sub_labels_only(backend_factory):
    backend, _ = backend_factory(
        action_response=ok_envelope("twitter", "search", backend="public-web/exa", items=[])
    )
    assert backend.execute("twitter", "search", {"query": "rust"}).ok is True

    backend2, _ = backend_factory(
        action_response=ok_envelope("twitter", "search", backend="opencli", items=[])
    )
    mismatch = backend2.execute("twitter", "search", {"query": "rust"})
    assert mismatch.ok is False
    assert mismatch.error["code"] == "route_violation"


def test_missing_declared_public_backend_is_not_silently_unforced(backend_factory):
    """If upstream renames its public backend, do not fall back to an unverified route."""
    payload = registry_payload()
    github = next(ch for ch in payload["channels"] if ch["name"] == "github")
    for action in github["actions"]:
        action["backends"] = ["gh"]
    backend, runner = backend_factory(payload)
    result = backend.execute("github", "search", {"query": "rust"})
    assert result.ok is False
    assert result.error["code"] == "auth_required"
    assert result.provenance["route"] == "authenticated"
    assert result.provenance["forced_backend"] is None
    assert runner.action_calls == []
    rows = {(r["channel"], r["action"]): r for r in backend.capabilities()}
    assert rows[("github", "search")]["public"] is False


def test_consented_calls_are_not_route_checked(backend_factory):
    """Without a pinned backend there is nothing to compare against."""
    backend, _ = backend_factory(
        action_response=ok_envelope("xueqiu", "hot_posts", backend="xueqiu-api", items=[]),
        allow_authenticated=True,
    )
    assert backend.execute("xueqiu", "hot_posts", {"limit": 1}).ok is True


# ── process safety ────────────────────────────────────────────────────────


def test_argument_array_has_no_shell_and_minimal_env(backend_factory, monkeypatch, tmp_path):
    """The child is always an argv list, never a shell, with a minimal env.

    The behavioural contract is what matters — argv list, ``shell=False``, no
    inherited stdin, no credential variable, no operator ``HOME`` in public mode
    — not which ``subprocess`` entry point is used.  The runner is deliberately
    ``Popen``-based now (capped drain + killable process group, see F5), so this
    test asserts the *invocation* rather than one call to ``subprocess.run``.
    """
    backend, runner = backend_factory(env={"PATH": "/usr/bin:/bin", "HOME": "/home/op", "GROQ_API_KEY": "secret", "OPENAI_API_KEY": "secret"})
    backend.execute("github", "search", {"query": "rust"})
    call = runner.action_calls[0]
    assert isinstance(call["argv"], list)
    child_env = call["env"]
    assert "GROQ_API_KEY" not in child_env
    assert "OPENAI_API_KEY" not in child_env
    # Public mode never hands the operator's home to the child.
    assert child_env["HOME"] != "/home/op"
    assert child_env["HOME"].startswith(tempfile.gettempdir())

    stub = tmp_path / "agent-reach"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"REGISTRY = {registry_payload()!r}\n"
        "argv = sys.argv[1:]\n"
        "if argv[:1] == ['channels']:\n"
        "    print(json.dumps(REGISTRY))\n"
        "    sys.exit(0)\n"
        "backend = argv[argv.index('--backend') + 1] if '--backend' in argv else None\n"
        "print(json.dumps({'schema_version': 1, 'ok': True, 'channel': argv[0],\n"
        "                  'action': argv[1], 'backend': backend, 'items': [],\n"
        "                  'meta': {}, 'error': None}))\n"
    )
    stub.chmod(0o755)
    calls: list[dict] = []
    real_popen = reach.subprocess.Popen

    def spy(argv, **kwargs):
        # Record the real invocation, then let the bounded runner do its job.
        calls.append({"argv": argv, "kwargs": kwargs})
        return real_popen(argv, **kwargs)

    monkeypatch.setattr(reach.subprocess, "Popen", spy)
    direct = reach.AgentReachBackend(str(stub), env={"PATH": "/usr/bin:/bin"})
    result = direct.execute("github", "search", {"query": "rust"})

    # Registry read and action call both go through the same bounded runner.
    assert result.ok is True
    assert len(calls) == 2
    for invocation in calls:
        argv = invocation["argv"]
        kwargs = invocation["kwargs"]
        assert isinstance(argv, list)
        assert all(isinstance(part, str) for part in argv)
        assert kwargs["shell"] is False
        assert kwargs["stdin"] is reach.subprocess.DEVNULL
        # No implicit capture helper: the drain owns both pipes.
        assert "capture_output" not in kwargs
        assert kwargs["stdout"] is reach.subprocess.PIPE
        assert kwargs["stderr"] is reach.subprocess.PIPE
        assert "GROQ_API_KEY" not in kwargs["env"]
        assert "OPENAI_API_KEY" not in kwargs["env"]
        if os.name == "posix":
            # Own session => own process group, so the kill reaches descendants.
            assert kwargs["start_new_session"] is True
    action_argv = calls[-1]["argv"]
    assert action_argv[:3] == [str(stub), "github", "search"]
    assert action_argv[-2:] == ["--", "rust"]


@pytest.mark.parametrize(
    "value",
    [
        "--limit",
        "-rf",
        "query\n--backend public-web",
        "query\x00suffix",
        "tab\there",
    ],
)
def test_option_injection_and_control_chars_are_rejected(backend_factory, value):
    backend, runner = backend_factory()
    result = backend.execute("github", "search", {"query": value})
    assert result.ok is False
    assert result.error["code"] in {"unsafe_target", "invalid_params"}
    assert runner.action_calls == []


@pytest.mark.parametrize(
    "value",
    [
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "ftp://example.com/x",
    ],
)
def test_dangerous_url_schemes_are_rejected(backend_factory, value):
    backend, runner = backend_factory()
    result = backend.execute("github", "read", {"target": value})
    assert result.ok is False
    assert result.error["code"] == "unsafe_target"
    assert runner.action_calls == []


def test_url_credentials_are_rejected_for_targets(backend_factory):
    backend, runner = backend_factory()
    result = backend.execute("github", "read", {"target": "https://user:pass@github.com/a/b"})
    assert result.error["code"] == "unsafe_target"
    assert runner.action_calls == []


def test_literal_identifiers_are_preserved(backend_factory):
    payload = registry_payload()
    payload["channels"][0]["actions"][1]["params"] = [_param("target", required=True)]
    backend, runner = backend_factory(payload)
    for target in ("owner/repo", "NousResearch/hermes-agent", "https://github.com/owner/repo/issues/42"):
        result = backend.execute("github", "read", {"target": target})
        assert result.ok is True
        assert runner.action_calls[-1]["argv"][-1] == target


def test_missing_unknown_and_out_of_bounds_params(backend_factory):
    backend, runner = backend_factory()
    assert backend.execute("github", "search", {}).error["code"] == "invalid_params"
    assert backend.execute("github", "search", {"query": "x", "evil": "y"}).error["code"] == "invalid_params"
    assert backend.execute("github", "search", {"query": "x", "limit": 0}).error["code"] == "invalid_params"
    assert backend.execute("github", "search", {"query": "x", "limit": 500}).error["code"] == "invalid_params"
    assert backend.execute("github", "search", {"query": "x", "limit": "abc"}).error["code"] == "invalid_params"
    assert backend.execute("github", "search", {"query": "x"}, timeout=0.5).error["code"] == "invalid_params"
    assert backend.execute("github", "search", {"query": "x"}, timeout=999).error["code"] == "invalid_params"
    assert backend.execute("github", "search", {"query": "x"}, max_items="many").error["code"] == "invalid_params"
    assert backend.execute("github", "search", {"query": "x"}, max_items=0).error["code"] == "invalid_params"
    assert runner.action_calls == []


def test_build_argv_terminator_and_option_order():
    argv = reach.build_argv(
        "/bin/agent-reach",
        "github",
        "search",
        positionals=["my query"],
        options=[("limit", "2")],
        backend="public-web",
        timeout=12.5,
    )
    assert argv == [
        "/bin/agent-reach",
        "github",
        "search",
        "--limit",
        "2",
        "--backend",
        "public-web",
        "--timeout",
        "12.5",
        "--",
        "my query",
    ]
    no_positionals = reach.build_argv("/bin/agent-reach", "v2ex", "hot", options=[("limit", "1")], timeout=5)
    assert "--" not in no_positionals


# ── upstream failures ─────────────────────────────────────────────────────


def test_timeout_is_reported_without_partial_output(backend_factory):
    backend, runner = backend_factory(raise_timeout=True)
    result = backend.execute("github", "search", {"query": "rust"}, timeout=1)
    assert result.ok is False
    assert result.error["code"] == "timeout"
    assert result.timed_out is True
    assert result.items == ()
    assert result.provenance["engine"] == "agent-reach"


def test_real_executable_timeout_is_killed(tmp_path):
    exe = tmp_path / "agent-reach"
    payload = registry_payload()
    exe.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys, time\n"
        f"PAYLOAD = {payload!r}\n"
        "if sys.argv[1:2] == ['channels']:\n"
        "    print(json.dumps(PAYLOAD))\n"
        "    sys.exit(0)\n"
        "time.sleep(30)\n"
    )
    exe.chmod(0o755)
    backend = reach.AgentReachBackend(
        str(exe),
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
        timeout=1,
    )
    backend.timeout_grace = 0.05
    result = backend.execute("github", "search", {"query": "rust"})
    assert result.ok is False
    assert result.error["code"] == "timeout"
    assert result.timed_out is True


def test_malformed_json_is_an_error(backend_factory):
    backend, _ = backend_factory(action_response="<html>not json</html>")
    result = backend.execute("github", "search", {"query": "rust"})
    assert result.ok is False
    assert result.error["code"] == "malformed_output"


def test_empty_stdout_and_non_object_payload(backend_factory):
    backend, _ = backend_factory(action_response="")
    assert backend.execute("github", "search", {"query": "rust"}).error["code"] == "malformed_output"

    backend2, _ = backend_factory(action_response="[]")
    assert backend2.execute("github", "search", {"query": "rust"}).error["code"] == "malformed_output"


def test_payload_without_ok_boolean_is_malformed(backend_factory):
    backend, _ = backend_factory(action_response={"channel": "github", "action": "search", "items": []})
    result = backend.execute("github", "search", {"query": "rust"})
    assert result.error["code"] == "malformed_output"


def test_upstream_error_envelope_is_forwarded_verbatim(backend_factory):
    backend, _ = backend_factory(
        action_response=error_envelope(
            "twitter", "search", code="UPSTREAM_BROKEN", message="Public web returned no usable content", hint="try the site tool"
        )
    )
    result = backend.execute("twitter", "search", {"query": "rust"})
    assert result.ok is False
    assert result.error["code"] == "upstream_error"
    assert result.error["upstream_code"] == "UPSTREAM_BROKEN"
    assert "Public web returned no usable content" in result.error["message"]
    assert result.error["hint"] == "try the site tool"
    assert result.items == ()


def test_mismatched_channel_echo_is_malformed(backend_factory):
    backend, _ = backend_factory(action_response=ok_envelope("v2ex", "search"))
    result = backend.execute("github", "search", {"query": "rust"})
    assert result.error["code"] == "malformed_output"
    assert "reported channel" in result.error["message"]


def test_spawn_failure_is_a_process_error(tmp_path):
    exe = tmp_path / "agent-reach"
    exe.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"PAYLOAD = {registry_payload()!r}\n"
        "if sys.argv[1:2] == ['channels']:\n"
        "    print(json.dumps(PAYLOAD))\n"
    )
    exe.chmod(0o755)
    backend = reach.AgentReachBackend(str(exe), env={"PATH": "/usr/bin:/bin"})
    real_registry = backend.registry

    def registry_then_disable(refresh: bool = False):
        registry = real_registry(refresh=refresh)  # channels succeeds first
        exe.chmod(0o000)  # then the binary becomes unrunnable
        return registry

    backend.registry = registry_then_disable  # type: ignore[assignment]
    result = backend.execute("github", "search", {"query": "rust"})
    assert result.ok is False
    assert result.error["code"] == "process_error"


def test_uninstalled_backend_returns_not_configured():
    backend = reach.AgentReachBackend("/nonexistent/agent-reach")
    result = backend.execute("github", "search", {"query": "rust"})
    assert result.ok is False
    assert result.error["code"] == "not_configured"
    assert reach.AGENT_REACH_ENV in result.error["message"]


# ── provenance and item normalisation ─────────────────────────────────────


def test_provenance_pins_upstream_attribution(backend_factory):
    backend, _ = backend_factory()
    result = backend.execute("github", "search", {"query": "rust", "limit": 2})
    payload = result.to_dict()
    assert payload["engine"] == "agent-reach"
    assert payload["provenance"]["engine"] == "agent-reach"
    assert payload["provenance"]["native"] is False
    assert "Agent Reach" in payload["provenance"]["attribution"]
    assert payload["provenance"]["schema_version"] == 1
    assert payload["provenance"]["route"] == "public_api"
    assert payload["provenance"]["reported_backend"] == "github-api"
    assert payload["provenance"]["requested"] == "github search"
    assert payload["backend"] == "github-api"
    assert payload["attempts"][0] == {"backend": "gh", "result": "NEED_SETUP", "message": "no credentials"}
    assert any("third-party Agent Reach" in line for line in payload["limitations"])
    assert any("never installs" in line for line in payload["limitations"])


def test_items_are_normalised_and_bounded(backend_factory):
    long_text = "x" * (reach.MAX_TEXT_CHARS + 500)
    raw_items = [
        {
            "title": "ok",
            "url": "https://example.com/a",
            "author": "a",
            "published_at": "2026-01-01T00:00:00Z",
            "text": long_text,
            "raw": {"big": "y" * 5000},
        },
        {"title": "evil", "url": "javascript:alert(1)", "text": "nope"},
        {"title": "no url"},
        "not a dict",
    ]
    backend, _ = backend_factory(action_response=ok_envelope("github", "search", items=raw_items))
    result = backend.execute("github", "search", {"query": "rust"})
    assert result.ok is True
    assert len(result.items) == 3
    first = result.items[0]
    assert first["text_truncated"] is True
    assert len(first["text"]) == reach.MAX_TEXT_CHARS
    assert first["raw"] is None
    assert result.items[1]["url"] is None
    assert result.items[1]["url_rejected"] is True
    assert any("not http(s)" in line for line in result.limitations)
    assert any("dropped" in line for line in result.limitations)


def test_respects_max_items(backend_factory):
    items = [{"title": str(i), "url": f"https://example.com/{i}"} for i in range(10)]
    backend, _ = backend_factory(action_response=ok_envelope("github", "search", items=items))
    result = backend.execute("github", "search", {"query": "rust"}, max_items=2)
    assert len(result.items) == 2
    assert any("kept the first 2" in line for line in result.limitations)


def test_error_results_still_carry_attribution(backend_factory):
    backend, _ = backend_factory()
    result = backend.execute("xueqiu", "hot_posts", {"limit": 1})
    assert result.error["code"] == "auth_required"
    assert result.provenance["engine"] == "agent-reach"
    assert result.provenance["native"] is False
    assert result.limitations[0] == reach.LIMITATION_FORWARDED


# ── registry caching / capability surface ─────────────────────────────────


def test_registry_is_cached_between_calls(backend_factory):
    backend, runner = backend_factory()
    backend.execute("github", "search", {"query": "one"})
    backend.execute("github", "search", {"query": "two"})
    channels_calls = [c for c in runner.calls if c["argv"][1:2] == ["channels"]]
    assert len(channels_calls) == 1
    assert len(runner.action_calls) == 2


def test_capabilities_mark_public_and_authenticated_routes(backend_factory):
    backend, _ = backend_factory()
    rows = {(r["channel"], r["action"]): r for r in backend.capabilities()}
    assert ("github", "search") in rows
    assert rows[("github", "search")]["mode"] == "public_api"
    assert rows[("github", "search")]["public"] is True
    assert rows[("github", "search")]["forced_backend"] == "github-api"
    assert rows[("v2ex", "hot")]["forced_backend"] == "v2ex-api"
    assert rows[("twitter", "search")]["mode"] == "public_web"
    assert rows[("twitter", "search")]["forced_backend"] == "public-web"
    assert rows[("twitter", "profile")]["mode"] == "authenticated"
    assert rows[("twitter", "profile")]["public"] is False
    # bilibili and xueqiu declare a login, but their public actions stay public.
    assert rows[("bilibili", "hot")]["public"] is True
    assert rows[("bilibili", "hot")]["forced_backend"] == "bilibili-api"
    assert rows[("bilibili", "read")]["forced_backend"] == "bilibili-api"
    assert rows[("bilibili", "subtitle")]["public"] is False
    assert rows[("xueqiu", "quote")]["forced_backend"] == "tencent"
    assert rows[("xueqiu", "search")]["public"] is True
    assert rows[("xueqiu", "hot_posts")]["public"] is False
    # Transcription is discoverable but double-gated; it is never public.
    assert ("youtube", "transcribe") in rows
    assert rows[("youtube", "transcribe")]["mode"] == "quota"
    assert rows[("youtube", "transcribe")]["public"] is False
    assert rows[("youtube", "transcribe")]["quota_consuming"] is True
    assert rows[("youtube", "transcribe")]["blocked_by_default"] is True
    assert rows[("youtube", "transcribe")]["gate"] == "quota"
    assert rows[("xiaoyuzhou", "transcribe")]["gate"] == "quota"
    assert all(row["gate"] != "quota" for (_, action), row in rows.items() if action != "transcribe")


def test_describe_reports_missing_executable_without_raising():
    payload = reach.AgentReachBackend("/nonexistent/agent-reach").describe()
    assert payload["found"] is False
    assert payload["reason"] == "explicit_missing"
    assert payload["error"]["code"] == "not_configured"
    assert payload["capabilities"] == []
    assert payload["public_only"] is True


def test_describe_reports_registry_error(backend_factory):
    backend, runner = backend_factory()
    runner.payload = {"schema_version": 1, "ok": True, "channels": [{"name": "github"}]}
    payload = backend.describe()
    assert payload["found"] is True
    assert payload["error"]["code"] == "registry_invalid"


# ── quota gate: transcription is visible, double-gated, and never automatic ──

TRANSCRIPTION_CALLS = (
    ("youtube", "transcribe", {"target": "https://youtu.be/dQw4w9WgXcQ"}, "whisper"),
    ("xiaoyuzhou", "transcribe", {"target": "https://www.xiaoyuzhoufm.com/episode/abc"}, "groq-whisper"),
)


@pytest.mark.parametrize("channel, action, params, backend", TRANSCRIPTION_CALLS)
def test_quota_actions_need_quota_and_auth_consent_separately(
    backend_factory, channel, action, params, backend
):
    """Both flags are required; neither one alone spawns anything."""
    response = ok_envelope(channel, action, backend=backend, items=[])
    backend_obj, runner = backend_factory(action_response=response)

    neither = backend_obj.execute(channel, action, params)
    assert neither.error["code"] == "quota_required"
    assert "--allow-quota-consuming" in neither.error["message"]

    quota_only = backend_obj.execute(channel, action, params, allow_quota_consuming=True)
    assert quota_only.error["code"] == "auth_required"
    assert "allow_authenticated" in quota_only.error["message"]

    auth_only = backend_obj.execute(channel, action, params, allow_authenticated=True)
    assert auth_only.error["code"] == "quota_required"

    assert runner.calls == []  # not even `channels` was executed


@pytest.mark.parametrize("channel, action, params, backend", TRANSCRIPTION_CALLS)
def test_quota_actions_run_only_with_both_consents(backend_factory, channel, action, params, backend):
    backend_obj, runner = backend_factory(
        action_response=ok_envelope(channel, action, backend=backend, items=[])
    )
    result = backend_obj.execute(
        channel, action, params, allow_quota_consuming=True, allow_authenticated=True
    )
    assert result.ok is True, result.error
    call = runner.action_calls[0]
    assert call["argv"][1:3] == [channel, action]
    assert "--backend" not in call["argv"]  # quota actions pin nothing
    assert result.provenance["quota_consuming"] is True
    assert result.provenance["route"] == "quota"
    assert result.provenance["public_only"] is False
    assert result.provenance["home_mode"] == "operator"
    assert result.provenance["forced_backend"] is None
    assert reach.LIMITATION_QUOTA in result.limitations
    assert reach.LIMITATION_AUTHENTICATED in result.limitations


def test_quota_consent_via_constructor_flags(backend_factory):
    backend, runner = backend_factory(
        action_response=ok_envelope("xiaoyuzhou", "transcribe", backend="groq-whisper", items=[]),
        allow_authenticated=True,
        allow_quota_consuming=True,
    )
    result = backend.execute("xiaoyuzhou", "transcribe", {"target": "abc"})
    assert result.ok is True
    assert runner.action_calls


@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_asr_veto_wins_over_explicit_quota_consent(backend_factory, value):
    backend, runner = backend_factory(
        action_response=ok_envelope("youtube", "transcribe", backend="whisper", items=[]),
        env={"PATH": "/usr/bin:/bin", reach.ASR_DISABLE_ENV: value},
    )
    result = backend.execute(
        "youtube",
        "transcribe",
        {"target": "https://youtu.be/abc"},
        allow_quota_consuming=True,
        allow_authenticated=True,
    )
    assert result.ok is False
    assert result.error["code"] == "asr_disabled"
    assert reach.ASR_DISABLE_ENV in result.error["message"]
    assert runner.calls == []


def test_asr_veto_from_the_real_environment(backend_factory, monkeypatch):
    monkeypatch.setenv(reach.ASR_DISABLE_ENV, "1")
    backend, runner = backend_factory(
        action_response=ok_envelope("youtube", "transcribe", backend="whisper", items=[])
    )
    result = backend.execute(
        "youtube",
        "transcribe",
        {"target": "https://youtu.be/abc"},
        allow_quota_consuming=True,
        allow_authenticated=True,
    )
    assert result.error["code"] == "asr_disabled"
    assert runner.calls == []


def test_asr_veto_does_not_block_read_only_actions(backend_factory):
    backend, runner = backend_factory(env={reach.ASR_DISABLE_ENV: "1"})
    result = backend.execute("github", "search", {"query": "rust"})
    assert result.ok is True
    assert runner.action_calls


# ── process-wide veto: OR semantics, no override bypass ─────────────────────


def test_asr_veto_is_an_or_and_cannot_be_cleared_by_a_mapping(monkeypatch):
    monkeypatch.setenv(reach.ASR_DISABLE_ENV, "1")
    assert reach.asr_disabled() is True
    # An empty (or partial) override can only add a veto, never clear one.
    assert reach.asr_disabled({}) is True
    assert reach.asr_disabled({"PATH": "/usr/bin:/bin"}) is True
    monkeypatch.delenv(reach.ASR_DISABLE_ENV, raising=False)
    assert reach.asr_disabled({}) is False
    assert reach.asr_disabled({reach.ASR_DISABLE_ENV: "yes"}) is True


def test_empty_env_override_cannot_bypass_the_process_veto(tmp_path, monkeypatch):
    """OS flag + env={} + both consents still spawns zero processes."""
    monkeypatch.setenv(reach.ASR_DISABLE_ENV, "1")
    marker = tmp_path / "spawned.txt"
    stub = tmp_path / "agent-reach"
    stub.write_text(
        f"#!{sys.executable}\n"
        "import pathlib, sys\n"
        f"pathlib.Path({str(marker)!r}).write_text(' '.join(sys.argv[1:]))\n"
        "print('{}')\n"
    )
    stub.chmod(0o755)

    backend = reach.AgentReachBackend(
        str(stub), env={}, allow_authenticated=True, allow_quota_consuming=True
    )
    result = backend.execute("youtube", "transcribe", {"target": "https://youtu.be/abc"})
    assert result.ok is False
    assert result.error["code"] == "asr_disabled"
    assert result.argv == ()
    assert not marker.exists(), "the veto must refuse before any process exists"

    diagnostics = backend.describe()
    assert diagnostics["asr_disabled"] is True
    assert diagnostics["asr_vetoed"] is True
    assert diagnostics["quota_ready"] is False


def test_capability_diagnostics_report_a_veto_with_an_empty_override(
    backend_factory, monkeypatch
):
    monkeypatch.setenv(reach.ASR_DISABLE_ENV, "1")
    backend, _ = backend_factory(
        env={}, allow_authenticated=True, allow_quota_consuming=True
    )
    rows = {(row["channel"], row["action"]): row for row in backend.capabilities()}
    assert rows[("youtube", "transcribe")]["asr_veto"] is True
    assert rows[("xiaoyuzhou", "transcribe")]["asr_veto"] is True

    payload = backend.describe()
    assert payload["quota_consuming_allowed"] is True
    assert payload["authenticated_allowed"] is True
    assert payload["asr_disabled"] is True
    assert payload["quota_ready"] is False
    assert payload["credential_source"] == "upstream-home-config"


@pytest.mark.parametrize(
    "quota, auth, veto, expected",
    (
        (False, False, False, False),
        (True, False, False, False),
        (False, True, False, False),
        (True, True, False, True),
        (True, True, True, False),
    ),
)
def test_quota_consent_and_quota_readiness_are_distinct(
    backend_factory, monkeypatch, quota, auth, veto, expected
):
    if veto:
        monkeypatch.setenv(reach.ASR_DISABLE_ENV, "1")
    else:
        monkeypatch.delenv(reach.ASR_DISABLE_ENV, raising=False)
    backend, _ = backend_factory(allow_quota_consuming=quota, allow_authenticated=auth)
    payload = backend.describe()
    # Consent is what the caller passed; readiness also needs the veto clear.
    assert payload["quota_consuming_allowed"] is quota
    assert payload["authenticated_allowed"] is auth
    assert payload["asr_vetoed"] is veto
    assert payload["quota_ready"] is expected


# ── untrusted error redaction ───────────────────────────────────────────────


def _sequenced_runner(action_response, registry=None):
    """A runner that answers ``channels`` normally and then replays a response."""

    def run(argv, *, timeout, env):
        if list(argv)[1:] == ["channels"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(registry if registry is not None else registry_payload()),
                stderr="",
            )
        response = action_response
        if callable(response):
            response = response(argv)
        stdout = response.stdout
        return SimpleNamespace(
            returncode=response.returncode, stdout=stdout, stderr=response.stderr
        )

    return run


def _stub_backend(tmp_path, runner, **kwargs):
    stub = tmp_path / "agent-reach"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)
    return reach.AgentReachBackend(str(stub), runner=runner, env={}, **kwargs)


def test_redaction_leaves_ordinary_text_alone_and_truncates_after_redacting():
    plain = "agent-reach channels exited 2: no credentials for github-api"
    assert reach.redact_secrets(plain) == plain
    token = "ghp_" + "B" * 36
    out = reach.redact_secrets("Authorization: Bearer " + token, limit=25)
    assert token[:12] not in out
    assert len(out) <= 25


def test_registry_stderr_is_redacted(tmp_path):
    secret = "sk-proj-LIVEKEY1234567890abcd"
    # Registry call itself fails with credential-bearing stderr.
    failing = SimpleNamespace(
        returncode=3,
        stdout="",
        stderr=(
            f"auth failed for {secret} "
            "https://alice:hunter2pass@api.example.test/v1"
        ),
    )

    def run(argv, *, timeout, env):
        return failing

    backend = _stub_backend(tmp_path, run)
    with pytest.raises(reach.RegistryError) as excinfo:
        backend.registry()
    text = str(excinfo.value)
    assert secret not in text
    assert "hunter2pass" not in text
    assert "[redacted" in text

    payload = backend.describe()
    assert payload["error"]["code"] == "registry_invalid"
    assert secret not in payload["error"]["message"]
    assert "hunter2pass" not in payload["error"]["message"]


def test_execution_stderr_is_redacted(tmp_path):
    secret = "sk-live-ABCDEFGHIJKLMNOP"
    token = "ghp_" + "B" * 36
    stderr = (
        f"boom OPENAI_API_KEY={secret} Authorization: Bearer {token} "
        "url https://bob:swordfish123@example.test/x"
    )
    runner = _sequenced_runner(
        SimpleNamespace(returncode=1, stdout="", stderr=stderr)
    )
    backend = _stub_backend(tmp_path, runner)
    result = backend.execute("github", "search", {"query": "rust"})
    assert result.error["code"] == "malformed_output"
    blob = json.dumps(result.to_dict())
    for leaked in (secret, token, "swordfish123"):
        assert leaked not in blob
    assert "[redacted" in result.error["message"]


def test_upstream_error_fields_and_attempts_are_redacted(tmp_path):
    secret = "sk-proj-QQQQQQQQQQQQQQQQQ"
    token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJlLXZhbHVl"
    response = {
        "schema_version": 1,
        "ok": False,
        "channel": "github",
        "action": "search",
        "backend": "github-api",
        "error": {
            "code": f"BAD_KEY {secret}",
            "message": f"upstream rejected key {secret}",
            "hint": f"Authorization: Bearer {token}",
        },
        "meta": {
            "attempts": [
                {"backend": "gh", "result": "FAILED", "message": f"token={secret}"}
            ]
        },
        "items": [],
    }
    runner = _sequenced_runner(SimpleNamespace(returncode=0, stdout=json.dumps(response), stderr=""))
    backend = _stub_backend(tmp_path, runner)
    result = backend.execute("github", "search", {"query": "rust"})
    assert result.error["code"] == "upstream_error"
    blob = json.dumps(result.to_dict())
    assert secret not in blob
    assert token not in blob
    assert "[redacted" in blob
    # The upstream code stays visible in shape, without the credential.
    assert "BAD_KEY" in result.error["upstream_code"]


def test_quota_run_forwards_no_api_keys_or_secrets(backend_factory):
    """Consent uses the operator's configured key store, never env passthrough."""
    backend, runner = backend_factory(
        action_response=ok_envelope("youtube", "transcribe", backend="whisper", items=[]),
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": "/home/op",
            "GROQ_API_KEY": "gsk-live-secret",
            "OPENAI_API_KEY": "sk-live-secret",
        },
    )
    result = backend.execute(
        "youtube", "transcribe", {"target": "abc"}, allow_quota_consuming=True, allow_authenticated=True
    )
    assert result.ok is True
    child_env = runner.action_calls[0]["env"]
    assert "GROQ_API_KEY" not in child_env
    assert "OPENAI_API_KEY" not in child_env
    assert "gsk-live-secret" not in json.dumps(child_env)
    assert "gsk-live-secret" not in json.dumps(result.to_dict())
    assert "sk-live-secret" not in json.dumps(result.to_dict())


def test_quota_consent_does_not_widen_the_read_only_route(backend_factory):
    """--allow-quota-consuming must not turn a session action into a public one."""
    backend, runner = backend_factory()
    result = backend.execute(
        "twitter", "profile", {"username": "nasa"}, allow_quota_consuming=True
    )
    assert result.error["code"] == "auth_required"
    assert runner.action_calls == []


def test_normal_search_code_has_no_quota_path():
    """Search is structurally incapable of reaching this module's quota gate."""
    from hermes_trailhead import search as search_module

    source = inspect.getsource(search_module)
    assert "reach_backend" not in source
    assert "allow_quota_consuming" not in source
    assert "transcribe" not in source


# ── pinned 40-action parity inventory ─────────────────────────────────────


def _registry_pairs() -> set[tuple[str, str]]:
    payload = pinned_registry_payload()
    return {
        (channel["name"], action["name"])
        for channel in payload["channels"]
        for action in channel["actions"]
    }


def test_parity_inventory_is_exactly_40_actions_across_14_channels():
    inventory = reach.parity_inventory()
    assert inventory["reference"]["commit"] == "14c213405669414492bda0f8d52cc6531d062c45"
    assert inventory["reference"]["version"] == "1.6.0"
    assert inventory["counts"]["actions"] == 40
    assert inventory["counts"]["channels"] == 14
    assert inventory["counts"]["surfaced"] == 40
    pairs = {(row["channel"], row["action"]) for row in inventory["actions"]}
    assert len(pairs) == 40
    reach.validate_parity_inventory()


def test_parity_inventory_matches_the_pinned_registry_exactly():
    payload = pinned_registry_payload()
    assert _registry_pairs() == {(row.channel, row.action) for row in reach.PARITY_ACTIONS}
    registry = reach.parse_registry(payload)
    reach.validate_parity_inventory(registry)


def test_every_inventory_gate_matches_runtime_route_policy():
    """Static inventory gates must equal what execute() would actually do."""
    registry = reach.parse_registry(pinned_registry_payload())
    for row in reach.PARITY_ACTIONS:
        channel = registry.channels[row.channel]
        action = channel.actions[row.action]
        if reach.AgentReachBackend.is_quota_action(row.channel, row.action):
            mode = reach.AgentReachBackend.quota_mode(channel, action)
            assert row.gate == "quota"
        else:
            mode = reach.AgentReachBackend.reach_mode(channel, action)
            assert row.gate == ("public" if mode.public else "consent"), row
        assert mode.quota_consuming is (row.gate == "quota")


def test_discoverable_capabilities_cover_the_whole_inventory(backend_factory):
    backend, _ = backend_factory(pinned_registry_payload())
    caps = {(row["channel"], row["action"]) for row in backend.capabilities()}
    assert caps == {(row.channel, row.action) for row in reach.PARITY_ACTIONS}
    quota_rows = [row for row in backend.capabilities() if row["gate"] == "quota"]
    assert {(row["channel"], row["action"]) for row in quota_rows} == {
        ("youtube", "transcribe"),
        ("xiaoyuzhou", "transcribe"),
    }
    assert all(row["blocked_by_default"] for row in quota_rows)


def test_capability_gates_use_the_same_vocabulary_as_the_inventory(backend_factory):
    """One gate vocabulary everywhere: public / consent / quota."""
    backend, _ = backend_factory(pinned_registry_payload())
    caps = backend.capabilities()
    gates = {row["gate"] for row in caps}
    assert gates <= set(reach.GATE_STATES)
    assert "authenticated" not in gates  # route word, never a gate word
    consent_pairs = {(row["channel"], row["action"]) for row in caps if row["gate"] == "consent"}
    assert consent_pairs == {row.pair for row in reach.PARITY_ACTIONS if row.gate == "consent"}
    rows = {(row["channel"], row["action"]): row for row in caps}
    assert rows[("twitter", "profile")]["mode"] == "authenticated"
    assert rows[("twitter", "profile")]["gate"] == "consent"
    assert rows[("github", "search")]["gate"] == "public"
    inventory = reach.parity_inventory()
    assert {row["gate"] for row in inventory["actions"]} <= set(reach.GATE_STATES)


def test_states_start_with_the_exact_coverage_word():
    rows = {(row.channel, row.action): row.to_dict() for row in reach.PARITY_ACTIONS}
    for pair, row in rows.items():
        assert row["states"][0] == row["coverage"], pair
    partial = rows[("github", "read")]
    assert partial["coverage"] == "native-partial"
    assert partial["states"][0] == "native-partial"
    assert "partial" not in partial["states"]
    assert "upstream" not in partial["states"]
    assert rows[("twitter", "profile")]["states"] == [
        "upstream",
        "gated-auth",
        "testing-fixture",
    ]
    assert rows[("youtube", "transcribe")]["states"][0] == "native-partial"
    assert rows[("youtube", "transcribe")]["states"][1] == "gated-quota"


def test_surfaced_ratio_is_computed_and_cannot_exceed_one(monkeypatch):
    inventory = reach.parity_inventory()
    counts = inventory["counts"]
    assert counts["surfaced"] == len(inventory["actions"]) == 40
    assert counts["surfaced_ratio"] == counts["surfaced"] / counts["actions"] == 1.0
    assert {row.pair for row in reach.PARITY_ACTIONS} == reach._SURFACED_PAIRS
    reach.validate_parity_inventory()

    # A surfaced pair with no inventory row would push the ratio above 1.
    monkeypatch.setattr(
        reach, "_SURFACED_PAIRS", reach._SURFACED_PAIRS | {("rogue", "search")}
    )
    with pytest.raises(ValueError, match="surfaced pairs are missing"):
        reach.validate_parity_inventory()


def test_parity_counts_never_promote_fixtures_to_live():
    inventory = reach.parity_inventory()
    rows = inventory["actions"]
    live = [row for row in rows if row["live_verified"]]
    assert inventory["counts"]["live_verified"] == len(live) == 5
    assert inventory["counts"]["fixture_only"] == 40 - len(live) == 35
    assert {f"{row['channel']} {row['action']}" for row in live} == {
        "github search",
        "reddit search",
        "bilibili hot",
        "v2ex hot",
        "xueqiu quote",
    }
    # Rows whose live claim rested on an aggregate (not a per-call) record are
    # fixture-only until the parent records a fresh run for them.
    for pair in (("github", "read"), ("bilibili", "read"), ("xueqiu", "search")):
        row = next(r for r in rows if (r["channel"], r["action"]) == pair)
        assert row["live_verified"] is False, pair
        assert "live" not in row["evidence"], pair
    for row in rows:
        # Evidence must be a list of vocabulary words, never a split string.
        assert isinstance(row["evidence"], list) and row["evidence"]
        assert set(row["evidence"]) <= {"fixture", "native-tests", "live"}
        assert all(len(item) > 1 for item in row["evidence"])
        if "live" not in row["evidence"]:
            assert row["live_verified"] is False
            assert "testing-fixture" in row["states"]
    assert "not live" in inventory["states"]["legend"] or "not live evidence" in inventory["states"]["legend"]


def test_validate_parity_inventory_rejects_upstream_drift():
    payload = pinned_registry_payload()
    payload["channels"] = [c for c in payload["channels"] if c["name"] != "xiaoyuzhou"]
    registry = reach.parse_registry(payload)
    with pytest.raises(ValueError, match="does not match the pinned registry"):
        reach.validate_parity_inventory(registry)
