"""OpenClaw 技能市场、MCP 服务、技能导入、文件上传、旅行、记忆、搜索代理路由"""

import json
import logging
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from urllib.request import Request as UrlRequest, urlopen
from urllib.error import URLError

from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from system.config import get_config
from apiserver import naga_auth
from apiserver.api_server import _call_agentserver, FileUploadResponse

logger = logging.getLogger(__name__)

router = APIRouter()


# ============ OpenClaw Skill Market ============

OPENCLAW_STATE_DIR = Path.home() / ".openclaw"
OPENCLAW_SKILLS_DIR = OPENCLAW_STATE_DIR / "skills"
OPENCLAW_CONFIG_PATH = OPENCLAW_STATE_DIR / "openclaw.json"
SKILLS_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "skills_templates"
MCPORTER_DIR = Path.home() / ".mcporter"
MCPORTER_CONFIG_PATH = MCPORTER_DIR / "config.json"

MARKET_ITEMS: List[Dict[str, Any]] = [
    {
        "id": "agent-browser",
        "title": "Agent Browser",
        "description": "Browser automation skill (offline template install, prebundled runtime preferred).",
        "skill_name": "agent-browser",
        "enabled": True,
        "install": {
            "type": "template_dir",
            "template": "agent-browser",
        },
    },
    {
        "id": "office-docs",
        "title": "Office Docs (docx + xlsx)",
        "description": "Extract docx/xlsx content with local scripts (no extra deps).",
        "skill_name": "office-docs",
        "enabled": True,
        "install": {
            "type": "template_dir",
            "template": "office-docs",
        },
    },
    {
        "id": "brainstorming",
        "title": "Brainstorming",
        "description": "Guided ideation and design exploration skill.",
        "skill_name": "brainstorming",
        "enabled": True,
        "install": {
            "type": "remote_skill",
            "url": "https://raw.githubusercontent.com/obra/superpowers/refs/heads/main/skills/brainstorming/SKILL.md",
        },
    },
    {
        "id": "context7",
        "title": "Context7 Docs",
        "description": "Query library/API docs via mcporter + context7 MCP (stdio).",
        "skill_name": "context7",
        "enabled": True,
        "install": {
            "type": "template_dir",
            "template": "context7",
        },
    },
    {
        "id": "search",
        "title": "Search (Firecrawl MCP)",
        "description": "Search MCP integration via mcporter + firecrawl-mcp.",
        "skill_name": "search",
        "enabled": True,
        "install": {
            "type": "template_dir",
            "template": "search",
        },
    },
]


# ============ OpenClaw 辅助函数 ============


def _run_command(command: List[str], timeout: int = 30) -> Tuple[int, str, str]:
    import locale
    enc = locale.getpreferredencoding() or "utf-8"
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, shell=(sys.platform == "win32"), encoding=enc, errors="replace")
    return result.returncode, (result.stdout or "").strip(), (result.stderr or "").strip()


def _download_text(url: str, timeout: int = 20) -> str:
    try:
        request = UrlRequest(url, headers={"User-Agent": "NagaAgent/market-installer"})
        with urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except URLError as exc:
        raise RuntimeError(f"下载失败: {exc}")


def _write_skill_file(skill_name: str, content: str) -> Path:
    skill_dir = OPENCLAW_SKILLS_DIR / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(content, encoding="utf-8")
    return skill_path


def _copy_template_dir(template_name: str, skill_name: str) -> None:
    template_dir = SKILLS_TEMPLATE_DIR / template_name
    if not template_dir.exists():
        raise FileNotFoundError(f"模板不存在: {template_dir}")
    skill_dir = OPENCLAW_SKILLS_DIR / skill_name
    for path in template_dir.rglob("*"):
        if path.is_dir():
            continue
        relative = path.relative_to(template_dir)
        target_path = skill_dir / relative
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target_path)


def _agent_browser_bin_name() -> str:
    return "agent-browser.cmd" if sys.platform == "win32" else "agent-browser"


def _resolve_packaged_openclaw_runtime_dir() -> Optional[Path]:
    candidates: List[Path] = []
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        meipass = Path(sys._MEIPASS)  # type: ignore[attr-defined]
        candidates.append(meipass.parent.parent / "openclaw-runtime" / "openclaw")
    # 开发环境下也允许直接复用本地构建产物中的预装运行时
    candidates.append(Path(__file__).resolve().parent.parent.parent / "frontend" / "backend-dist" / "openclaw-runtime" / "openclaw")
    for candidate in candidates:
        if (candidate / "node_modules").exists():
            return candidate
    return None


def _resolve_prebundled_agent_browser_cmd() -> Optional[str]:
    runtime_dir = _resolve_packaged_openclaw_runtime_dir()
    if not runtime_dir:
        return None
    cmd = runtime_dir / "node_modules" / ".bin" / _agent_browser_bin_name()
    return str(cmd) if cmd.exists() else None


def _update_mcporter_firecrawl_config(api_key: Optional[str]) -> Path:
    MCPORTER_DIR.mkdir(parents=True, exist_ok=True)
    mcporter_config: Dict[str, Any] = {}
    if MCPORTER_CONFIG_PATH.exists():
        try:
            mcporter_config = json.loads(MCPORTER_CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            mcporter_config = {}
    servers = mcporter_config.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    server_entry = servers.get("firecrawl-mcp")
    if not isinstance(server_entry, dict):
        server_entry = {}
    env = server_entry.get("env")
    if not isinstance(env, dict):
        env = {}
    if api_key:
        env["FIRECRAWL_API_KEY"] = api_key
    elif "FIRECRAWL_API_KEY" not in env:
        env["FIRECRAWL_API_KEY"] = "YOUR_FIRECRAWL_API_KEY"
    server_entry.update({"command": "npx", "args": ["-y", "firecrawl-mcp"], "env": env})
    servers["firecrawl-mcp"] = server_entry
    mcporter_config["mcpServers"] = servers
    MCPORTER_CONFIG_PATH.write_text(json.dumps(mcporter_config, ensure_ascii=True, indent=2), encoding="utf-8")
    return MCPORTER_CONFIG_PATH


def _install_agent_browser() -> None:
    prebundled_cmd = _resolve_prebundled_agent_browser_cmd()
    if prebundled_cmd:
        logger.info(f"检测到预装 agent-browser，跳过在线安装: {prebundled_cmd}")
        return

    existing_cmd = shutil.which("agent-browser")
    if existing_cmd:
        logger.info(f"检测到系统已安装 agent-browser，跳过安装: {existing_cmd}")
        return

    if shutil.which("npm") is None:
        raise RuntimeError("未检测到预装 agent-browser，且系统未找到 npm，无法在线安装")
    logger.info("未检测到预装 agent-browser，降级为 npm 在线安装...")
    code, stdout, stderr = _run_command(["npm", "install", "-g", "agent-browser", "--force"], timeout=3000)
    if code != 0:
        raise RuntimeError(stderr or stdout or "npm install -g agent-browser --force 失败")
    installed_cmd = shutil.which("agent-browser")
    if installed_cmd is None:
        raise RuntimeError("agent-browser 未安装成功或未在 PATH 中")
    logger.info("正在 agent-browser install（下载浏览器，可能需要数分钟）...")
    code, stdout, stderr = _run_command([installed_cmd, "install"], timeout=3000)
    if code != 0:
        raise RuntimeError(stderr or stdout or "agent-browser install 失败")
    logger.info("agent-browser 安装完成")


def _build_market_item(item: Dict[str, Any]) -> Dict[str, Any]:
    skill_name = str(item.get("skill_name") or item.get("id") or "unknown")
    skill_path = OPENCLAW_SKILLS_DIR / skill_name / "SKILL.md"
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "description": item.get("description"),
        "skill_name": skill_name,
        "enabled": item.get("enabled", True),
        "installed": skill_path.exists(),
        "skill_path": str(skill_path),
        "install_type": item.get("install", {}).get("type"),
    }


def _get_market_items_status() -> Dict[str, Any]:
    return {
        "openclaw": {
            "skills_dir": str(OPENCLAW_SKILLS_DIR),
            "config_path": str(OPENCLAW_CONFIG_PATH),
        },
        "items": [_build_market_item(item) for item in MARKET_ITEMS],
    }


# ============ OpenClaw 技能市场端点 ============


@router.get("/openclaw/market/items")
def list_openclaw_market_items():
    """获取OpenClaw技能市场条目（同步端点，由 FastAPI 在线程池中执行）"""
    try:
        status = _get_market_items_status()
        return {"status": "success", **status}
    except Exception as e:
        logger.error(f"获取技能市场失败: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取技能市场失败: {str(e)}")


@router.post("/openclaw/market/items/{item_id}/install")
def install_openclaw_market_item(item_id: str, payload: Optional[Dict[str, Any]] = None):
    """安装指定OpenClaw技能市场条目（同步端点，由 FastAPI 在线程池中执行）"""
    item = next((entry for entry in MARKET_ITEMS if entry.get("id") == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="条目不存在")
    if not item.get("enabled", True):
        raise HTTPException(status_code=400, detail="条目暂不可安装")

    install_spec = item.get("install", {})
    install_type = install_spec.get("type")
    skill_name_value = item.get("skill_name") or item.get("id")
    if not skill_name_value:
        raise HTTPException(status_code=500, detail="技能名称缺失")
    skill_name = str(skill_name_value)

    try:
        if install_type == "remote_skill":
            url = install_spec.get("url")
            if not url:
                raise HTTPException(status_code=500, detail="缺少安装URL")
            content = _download_text(url)
            _write_skill_file(skill_name, content)
        elif install_type == "template_dir":
            template_name = install_spec.get("template")
            if not template_name:
                raise HTTPException(status_code=500, detail="缺少模板名称")
            _copy_template_dir(template_name, skill_name)
        elif install_type == "none":
            raise HTTPException(status_code=400, detail="该条目不支持安装")
        else:
            raise HTTPException(status_code=400, detail="未知安装方式")

        if item_id == "agent-browser":
            _install_agent_browser()
        if item_id == "search":
            api_key = None
            if payload and isinstance(payload, dict):
                api_key = payload.get("api_key") or payload.get("FIRECRAWL_API_KEY")
            _update_mcporter_firecrawl_config(api_key)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"安装技能失败({item_id}): {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"安装失败: {str(e)}")

    status = _get_market_items_status()
    installed_item = next((entry for entry in status.get("items", []) if entry.get("id") == item_id), None)
    return {
        "status": "success",
        "message": "安装完成",
        "item": installed_item,
        "openclaw": status.get("openclaw"),
    }


# ============ OpenClaw 任务状态查询 ============


@router.get("/openclaw/tasks")
async def api_openclaw_list_tasks():
    """列出本地缓存的 OpenClaw 任务（来自 agentserver）"""
    return await _call_agentserver("GET", "/openclaw/tasks")


@router.get("/openclaw/tasks/{task_id}")
async def api_openclaw_get_task(
    task_id: str,
    include_history: bool = False,
    history_limit: int = 50,
    include_tools: bool = False,
):
    """获取 OpenClaw 任务状态（支持查看中间过程）"""
    return await _call_agentserver(
        "GET",
        f"/openclaw/tasks/{task_id}/detail",
        params={
            "include_history": str(include_history).lower(),
            "history_limit": history_limit,
            "include_tools": str(include_tools).lower(),
        },
    )


# ============ MCP 服务列表 & 导入 ============


def _load_mcporter_config() -> Dict[str, Any]:
    """读取 ~/.mcporter/config.json，不存在或格式错误时返回空 dict"""
    if not MCPORTER_CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(MCPORTER_CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _check_agent_available(manifest: Dict[str, Any]) -> bool:
    """检查内置 agent 模块是否可导入"""
    entry = manifest.get("entryPoint", {})
    module_path = entry.get("module", "")
    if not module_path:
        return False
    try:
        __import__(module_path)
        return True
    except Exception as e:
        logger.warning(f"MCP 模块导入失败 {module_path}: {e}")
        return False


@router.get("/mcp/status")
async def get_mcp_status_offline():
    """MCP Server 未启动时返回离线状态，避免前端 503"""
    return {
        "server": "offline",
        "timestamp": datetime.now().isoformat(),
        "tasks": {"total": 0, "active": 0, "completed": 0, "failed": 0},
    }


@router.get("/mcp/tasks")
async def get_mcp_tasks_offline(status: Optional[str] = None):
    """MCP Server 未启动时返回空任务列表，避免前端 503"""
    return {"tasks": [], "total": 0}


@router.get("/mcp/services")
def get_mcp_services():
    """列出所有 MCP 服务并检查可用性（同步端点，由 FastAPI 在线程池中执行）"""
    services: List[Dict[str, Any]] = []

    # 1. 内置 agent（扫描 mcpserver 下所有 agent-manifest.json，与 mcp_registry 一致）
    mcpserver_dir = Path(__file__).resolve().parent.parent.parent / "mcpserver"
    if not mcpserver_dir.exists():
        logger.warning(f"MCP 目录不存在: {mcpserver_dir}")
    for manifest_path in sorted(mcpserver_dir.glob("**/agent-manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if manifest.get("agentType") != "mcp":
            continue
        available = _check_agent_available(manifest)
        services.append({
            "name": manifest.get("name", manifest_path.parent.name),
            "display_name": manifest.get("displayName", manifest.get("name", "")),
            "description": manifest.get("description", ""),
            "source": "builtin",
            "available": available,
            "enabled": True,
        })

    # 2. mcporter 外部配置（~/.mcporter/config.json 中的 mcpServers）
    mcporter_config = _load_mcporter_config()
    for name, cfg in mcporter_config.get("mcpServers", {}).items():
        cmd = cfg.get("command", "")
        available = shutil.which(cmd) is not None if cmd else False
        # 提取 meta 字段（以 _ 开头的不属于 MCP 协议本身）
        display_name = cfg.get("_displayName", name)
        description = cfg.get("_description", "")
        disabled = cfg.get("_disabled", False)
        if not description and cmd:
            description = f"{cmd} {' '.join(cfg.get('args', []))}"
        # 构建干净的 config（去掉 _ 开头的 meta 字段）
        clean_config = {k: v for k, v in cfg.items() if not k.startswith("_")}
        services.append({
            "name": name,
            "display_name": display_name,
            "description": description,
            "source": "mcporter",
            "available": available,
            "enabled": not disabled,
            "config": clean_config,
        })

    return JSONResponse(
        content={"status": "success", "services": services},
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


class McpImportRequest(BaseModel):
    name: str
    config: Dict[str, Any]


@router.post("/mcp/import")
async def import_mcp_config(request: McpImportRequest):
    """将 MCP JSON 配置写入 ~/.mcporter/config.json"""
    MCPORTER_DIR.mkdir(parents=True, exist_ok=True)
    mcporter_config = _load_mcporter_config()
    servers = mcporter_config.setdefault("mcpServers", {})
    servers[request.name] = request.config
    mcporter_config["mcpServers"] = servers
    MCPORTER_CONFIG_PATH.write_text(
        json.dumps(mcporter_config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"status": "success", "message": f"已添加 MCP 服务: {request.name}"}


@router.put("/mcp/services/{name}")
async def update_mcp_service(name: str, body: Dict[str, Any]):
    """更新 MCP 服务配置（支持 config / displayName / description / enabled）"""
    mcporter_config = _load_mcporter_config()
    servers = mcporter_config.get("mcpServers", {})
    if name not in servers:
        raise HTTPException(status_code=404, detail=f"MCP 服务 {name} 不存在")
    if "config" in body:
        # 替换整个配置（但保留 meta 字段）
        meta_keys = {"_displayName", "_description", "_disabled"}
        old_meta = {k: v for k, v in servers[name].items() if k in meta_keys}
        servers[name] = {**body["config"], **old_meta}
    if "displayName" in body:
        servers[name]["_displayName"] = body["displayName"]
    if "description" in body:
        servers[name]["_description"] = body["description"]
    if "enabled" in body:
        if body["enabled"]:
            servers[name].pop("_disabled", None)
        else:
            servers[name]["_disabled"] = True
    mcporter_config["mcpServers"] = servers
    MCPORTER_CONFIG_PATH.write_text(
        json.dumps(mcporter_config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"status": "success", "message": f"已更新 MCP 服务: {name}"}


@router.delete("/mcp/services/{name}")
async def delete_mcp_service(name: str):
    """删除外部 MCP 服务配置"""
    mcporter_config = _load_mcporter_config()
    servers = mcporter_config.get("mcpServers", {})
    if name not in servers:
        raise HTTPException(status_code=404, detail=f"MCP 服务 {name} 不存在")
    del servers[name]
    mcporter_config["mcpServers"] = servers
    MCPORTER_CONFIG_PATH.write_text(
        json.dumps(mcporter_config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"status": "success", "message": f"已删除 MCP 服务: {name}"}


# ============ 技能导入 ============


class SkillImportRequest(BaseModel):
    name: str
    content: str


@router.post("/skills/import")
async def import_custom_skill(request: SkillImportRequest):
    """创建自定义技能 SKILL.md"""
    skill_content = f"""---
name: {request.name}
description: 用户自定义技能
version: 1.0.0
author: User
tags:
  - custom
enabled: true
---

{request.content}
"""
    skill_path = _write_skill_file(request.name, skill_content)
    return {"status": "success", "message": f"技能已创建: {skill_path}"}


# ============ 文件上传 ============


@router.post("/upload/document", response_model=FileUploadResponse)
async def upload_document(file: UploadFile = File(...), description: str = Form(None)):
    """上传文档接口"""
    try:
        # 确保上传目录存在
        upload_dir = Path("uploaded_documents")
        upload_dir.mkdir(exist_ok=True)

        # 使用原始文件名
        filename = file.filename
        file_path = upload_dir / filename

        # 保存文件
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 获取文件信息
        stat = file_path.stat()

        return FileUploadResponse(
            filename=filename,
            file_path=str(file_path.absolute()),
            file_size=stat.st_size,
            file_type=file_path.suffix,
            upload_time=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
        )
    except Exception as e:
        logger.error(f"文件上传失败: {e}")
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")


@router.post("/upload/parse")
async def upload_parse(file: UploadFile = File(...)):
    """上传并解析文档内容（支持 .docx / .xlsx / .txt）"""
    import tempfile
    filename = file.filename or "unknown"
    suffix = Path(filename).suffix.lower()

    if suffix not in (".docx", ".xlsx", ".txt", ".csv", ".md"):
        raise HTTPException(status_code=400, detail=f"不支持的文件格式: {suffix}，支持 .docx / .xlsx / .txt / .csv / .md")

    # 写入临时文件
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        if suffix == ".docx":
            import importlib.util
            _docx_spec = importlib.util.spec_from_file_location(
                "docx_extract", Path(__file__).parent.parent / "skills_templates" / "office-docs" / "tools" / "docx_extract.py"
            )
            _docx_mod = importlib.util.module_from_spec(_docx_spec)
            _docx_spec.loader.exec_module(_docx_mod)
            lines = _docx_mod.extract_docx_text(tmp_path)
            content = "\n".join(lines)
        elif suffix == ".xlsx":
            import importlib.util, zipfile as _zf
            _xlsx_spec = importlib.util.spec_from_file_location(
                "xlsx_extract", Path(__file__).parent.parent / "skills_templates" / "office-docs" / "tools" / "xlsx_extract.py"
            )
            _xlsx_mod = importlib.util.module_from_spec(_xlsx_spec)
            _xlsx_spec.loader.exec_module(_xlsx_mod)
            with _zf.ZipFile(tmp_path, "r") as archive:
                shared_strings = _xlsx_mod._load_shared_strings(archive)
                sheets = _xlsx_mod._load_sheet_targets(archive)
                parts = []
                for name, path in sheets:
                    rows = _xlsx_mod._parse_sheet(archive, path, shared_strings, max_rows=500)
                    parts.append(f"## Sheet: {name}\n{_xlsx_mod._format_sheet_csv(rows, ',')}")
                content = "\n".join(parts)
        else:
            # txt / csv / md 直接读取
            content = tmp_path.read_text(encoding="utf-8", errors="replace")

        # 截断过长内容
        max_chars = 50000
        truncated = len(content) > max_chars
        if truncated:
            content = content[:max_chars]

        return {
            "status": "success",
            "filename": filename,
            "content": content,
            "truncated": truncated,
            "char_count": len(content),
        }
    except Exception as e:
        logger.error(f"文档解析失败: {e}")
        raise HTTPException(status_code=500, detail=f"解析失败: {str(e)}")
    finally:
        tmp_path.unlink(missing_ok=True)


# ============ 旅行端点 ============


@router.post("/travel/start")
async def travel_start(payload: Dict[str, Any]):
    """创建旅行 session 并代理到 agent server 执行"""
    from apiserver.travel_service import create_session, get_active_session

    # 拒绝已有活跃 session
    active = get_active_session()
    if active:
        raise HTTPException(409, f"已有进行中的旅行: {active.session_id}")

    session = create_session(
        time_limit_minutes=payload.get("time_limit_minutes", 300),
        credit_limit=payload.get("credit_limit", 1000),
        want_friends=payload.get("want_friends", True),
        friend_description=payload.get("friend_description"),
    )
    # 代理到 agent server
    try:
        await _call_agentserver(
            "POST", "/travel/execute",
            json_body={"session_id": session.session_id},
            timeout_seconds=10.0,
        )
    except Exception as e:
        logger.warning(f"代理旅行到 agent server 失败（将本地标记失败）: {e}")
        from apiserver.travel_service import load_session as _ls, save_session as _ss, TravelStatus
        s = _ls(session.session_id)
        s.status = TravelStatus.FAILED
        s.error = f"agent server 不可达: {e}"
        _ss(s)
        raise HTTPException(503, f"agent server 不可达: {e}")

    return {"status": "success", "session_id": session.session_id}


@router.get("/travel/status")
async def travel_status():
    """返回当前活跃 session 或最新完成的"""
    from apiserver.travel_service import get_active_session, list_sessions

    active = get_active_session()
    if active:
        return {"status": "success", "session": active.model_dump(), "active": True}

    sessions = list_sessions()
    if sessions:
        return {"status": "success", "session": sessions[0].model_dump(), "active": False}

    return {"status": "success", "session": None, "active": False}


@router.post("/travel/stop")
async def travel_stop(payload: Dict[str, Any] = None):
    """取消活跃 session"""
    from apiserver.travel_service import get_active_session, save_session, TravelStatus

    active = get_active_session()
    if not active:
        raise HTTPException(404, "没有进行中的旅行")

    active.status = TravelStatus.CANCELLED
    active.completed_at = datetime.now().isoformat()
    save_session(active)
    return {"status": "success", "session_id": active.session_id}


@router.get("/travel/history")
async def travel_history():
    """历史列表"""
    from apiserver.travel_service import list_sessions

    sessions = list_sessions()
    return {"status": "success", "sessions": [s.model_dump() for s in sessions]}


@router.get("/travel/history/{session_id}")
async def travel_history_detail(session_id: str):
    """单个详情"""
    from apiserver.travel_service import load_session

    try:
        session = load_session(session_id)
    except FileNotFoundError:
        raise HTTPException(404, f"旅行 session 不存在: {session_id}")
    return {"status": "success", "session": session.model_dump()}


# ============ 记忆 ============


@router.get("/memory/stats")
async def get_memory_stats():
    """获取记忆统计信息"""

    try:
        # 优先使用远程 NagaMemory 服务
        from summer_memory.memory_client import get_remote_memory_client

        remote = get_remote_memory_client()
        if remote is not None:
            try:
                stats = await remote.get_stats()
                if stats.get("success") is not False:
                    return {"status": "success", "memory_stats": stats}
                logger.warning(f"远程记忆统计获取失败: {stats.get('error')}，降级到本地")
            except Exception as e:
                logger.warning(f"远程记忆统计异常: {e}，降级到本地")

        # 回退到本地 summer_memory
        try:
            from summer_memory.memory_manager import memory_manager

            if memory_manager and memory_manager.enabled:
                stats = memory_manager.get_memory_stats()
                return {"status": "success", "memory_stats": stats}
            else:
                return {"status": "success", "memory_stats": {"enabled": False, "message": "记忆系统未启用"}}
        except ImportError:
            return {"status": "success", "memory_stats": {"enabled": False, "message": "记忆系统模块未找到"}}
    except Exception as e:
        print(f"获取记忆统计错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取记忆统计失败: {str(e)}")


@router.get("/memory/quintuples")
async def get_quintuples():
    """获取所有五元组 (用于知识图谱可视化)"""
    try:
        # 优先使用远程 NagaMemory 服务
        from summer_memory.memory_client import get_remote_memory_client

        remote = get_remote_memory_client()
        remote_quintuples = []
        if remote is not None:
            try:
                result = await remote.get_quintuples(limit=500)
                if result.get("success") is not False:
                    quintuples_raw = result.get("quintuples") or result.get("results") or result.get("data") or []
                    # 兼容 NagaMemory 返回格式：可能是 dict 列表或 tuple 列表
                    for q in quintuples_raw:
                        if isinstance(q, dict):
                            remote_quintuples.append({
                                "subject": q.get("subject", ""),
                                "subject_type": q.get("subject_type", ""),
                                "predicate": q.get("predicate", q.get("relation", "")),
                                "object": q.get("object", ""),
                                "object_type": q.get("object_type", ""),
                            })
                        elif isinstance(q, (list, tuple)) and len(q) >= 5:
                            remote_quintuples.append({
                                "subject": q[0], "subject_type": q[1],
                                "predicate": q[2], "object": q[3], "object_type": q[4],
                            })
                else:
                    logger.warning(f"远程五元组获取失败: {result.get('error')}，降级到本地")
            except Exception as e:
                logger.warning(f"远程五元组获取异常: {e}，降级到本地")

        # 合并本地 summer_memory 数据（远程为空或失败时补充本地数据）
        local_quintuples = []
        try:
            from summer_memory.quintuple_graph import get_all_quintuples
            local_data = get_all_quintuples()  # returns set[tuple]
            local_quintuples = [
                {"subject": q[0], "subject_type": q[1], "predicate": q[2], "object": q[3], "object_type": q[4]}
                for q in local_data
            ]
        except ImportError:
            pass

        # 合并去重：以 (subject, predicate, object) 为唯一键
        seen = set()
        merged = []
        for q in remote_quintuples + local_quintuples:
            key = (q["subject"], q["predicate"], q["object"])
            if key not in seen:
                seen.add(key)
                merged.append(q)

        return {
            "status": "success",
            "quintuples": merged,
            "count": len(merged),
        }
    except ImportError:
        return {"status": "success", "quintuples": [], "count": 0, "message": "记忆系统模块未找到"}
    except Exception as e:
        logger.error(f"获取五元组错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取五元组失败: {str(e)}")


@router.get("/memory/quintuples/search")
async def search_quintuples(keywords: str = ""):
    """按关键词搜索五元组"""
    try:
        keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]
        if not keyword_list:
            raise HTTPException(status_code=400, detail="请提供搜索关键词")

        # 优先使用远程 NagaMemory 服务
        from summer_memory.memory_client import get_remote_memory_client

        remote = get_remote_memory_client()
        if remote is not None:
            try:
                result = await remote.query_by_keywords(keyword_list)
                if result.get("success") is not False:
                    quintuples_raw = result.get("quintuples") or result.get("results") or result.get("data") or []
                    quintuples = []
                    for q in quintuples_raw:
                        if isinstance(q, dict):
                            quintuples.append({
                                "subject": q.get("subject", ""),
                                "subject_type": q.get("subject_type", ""),
                                "predicate": q.get("predicate", q.get("relation", "")),
                                "object": q.get("object", ""),
                                "object_type": q.get("object_type", ""),
                            })
                        elif isinstance(q, (list, tuple)) and len(q) >= 5:
                            quintuples.append({
                                "subject": q[0], "subject_type": q[1],
                                "predicate": q[2], "object": q[3], "object_type": q[4],
                            })
                    return {"status": "success", "quintuples": quintuples, "count": len(quintuples)}
                else:
                    logger.warning(f"远程五元组搜索失败: {result.get('error')}，降级到本地")
            except Exception as e:
                logger.warning(f"远程五元组搜索异常: {e}，降级到本地")

        # 回退到本地 summer_memory
        from summer_memory.quintuple_graph import query_graph_by_keywords

        results = query_graph_by_keywords(keyword_list)
        return {
            "status": "success",
            "quintuples": [
                {"subject": q[0], "subject_type": q[1], "predicate": q[2], "object": q[3], "object_type": q[4]}
                for q in results
            ],
            "count": len(results),
        }
    except ImportError:
        return {"status": "success", "quintuples": [], "count": 0, "message": "记忆系统模块未找到"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"搜索五元组错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"搜索五元组失败: {str(e)}")


# ============ 搜索代理 ============


@router.api_route("/tools/search", methods=["GET", "POST"])
async def proxy_search(request: Request):
    """Brave Search 兼容代理 → NagaModel /v1/tools/search"""
    if not naga_auth.is_authenticated():
        raise HTTPException(status_code=401, detail="未登录 NagaModel")

    if request.method == "GET":
        params = dict(request.query_params)
    else:
        params = await request.json()

    import httpx
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                naga_auth.NAGA_MODEL_URL + "/tools/search",
                json=params,
                headers={"Authorization": f"Bearer {naga_auth.get_access_token()}"},
                timeout=30,
            )
        return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except Exception as e:
        logger.warning(f"搜索代理失败: {e}")
        return JSONResponse(
            content={"error": {"message": f"搜索服务不可用: {e}", "type": "upstream_error"}},
            status_code=502,
        )
