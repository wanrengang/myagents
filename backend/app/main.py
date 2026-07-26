"""FastAPI 网关：消息 SSE 流、七段流水线事件、HITL 审批恢复、多员工路由。

链路：前端选员工 → POST 开会话（conv→emp 映射）→ 发消息
→ runtime.get_agent(emp) 取编译好的 agent → astream 双流模式
（messages 出 token，updates 出 规划/工具/技能激活/中断）→ SSE 下发。
中断时不挂协程：状态在 SqliteSaver，审批决策走另一个请求 resume。
"""
import asyncio
import datetime
import io
import json
import logging
import os
import re
import shutil
import sqlite3
import time
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

import dotenv
from fastapi import (APIRouter, Depends, FastAPI, File, Header, HTTPException,
                     Request, UploadFile)
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import AIMessageChunk, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.sqlite import AsyncSqliteStore
from langgraph.types import Command
from pydantic import BaseModel

from app import auth, runtime, approvals, conversations, catalog, traces
from app.compiler import _init_model
from app.paths import db_path, DB_FILES, PROJECT_ROOT
from app.logging_setup import setup_logging, request_id_var, get_logger
from app.errors import register_exception_handlers

ROOT = Path(__file__).resolve().parent.parent
APP_VERSION = os.environ.get("APP_VERSION", "0.3.0")
log = get_logger("app.main")

@asynccontextmanager
async def lifespan(app):
    dotenv.load_dotenv(PROJECT_ROOT / ".env")
    setup_logging()
    log.info("启动 myagents v%s | 数据目录=%s", APP_VERSION, db_path("catalog.db").parent)
    catalog.init()          # 建目录库表（幂等）
    catalog.seed_if_empty() # 首次启动把小苏/小数原样种子进库
    catalog.seed_admin_if_empty()  # 首次启动创建初始管理员
    catalog.flag_default_admin_password()  # admin 仍默认密码则强制首登改密
    catalog.seed_assignments_if_empty()  # 已有用户全预分配（demo 不崩）
    async with AsyncSqliteSaver.from_conn_string(str(db_path("demo.db"))) as cp:
        runtime.set_checkpointer(cp)
        async with AsyncSqliteStore.from_conn_string(str(db_path("store.db"))) as store:
            runtime.set_store(store)
            await runtime.warmup_all()  # 预热编译全部员工（含拉起各自 MCP stdio 连接器）
            await recover_conversations()   # 把今天已有的历史线程登记进会话清单
            log.info("启动完成，开始接收请求")
            yield
            log.info("服务关闭")

app = FastAPI(lifespan=lifespan)
register_exception_handlers(app)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """给每个请求分配一个 ID（可经 X-Request-Id 透传），记录方法与耗时；
    请求上下文里的日志都会带上这个 rid，便于串联排查。"""
    rid = request.headers.get("X-Request-Id") or uuid.uuid4().hex[:12]
    token = request_id_var.set(rid)
    start = time.time()
    try:
        response = await call_next(request)
    except Exception:
        raise
    finally:
        request_id_var.reset(token)
    dur_ms = (time.time() - start) * 1000
    rl = get_logger("app.request")
    rl.info("%s %s -> %d (%.1fms)", request.method, request.url.path,
            response.status_code, dur_ms)
    response.headers["X-Request-Id"] = rid
    return response


@app.get("/health")
async def health():
    """健康检查（无需登录）：供容器探针 / 监控 / 负载均衡使用。
    依次探测每个 SQLite 库能否连接；全部正常返回 status=ok，否则 degraded。"""
    dbs: dict[str, str] = {}
    for name in DB_FILES:
        try:
            con = sqlite3.connect(str(db_path(name)))
            con.execute("SELECT 1")
            con.close()
            dbs[name] = "ok"
        except Exception as e:  # noqa: BLE001 - 探测失败也要在响应里暴露
            dbs[name] = f"error: {e}"
    all_ok = all(v == "ok" for v in dbs.values())
    return {
        "status": "ok" if all_ok else "degraded",
        "version": APP_VERSION,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "databases": dbs,
    }


# 会话 → 员工 映射（进程内存热路径；持久清单见 conversations.py）。
_conversations: dict[str, str] = {}

def employee_of(conv_id: str) -> str:
    """会话归属的员工：先看内存热映射，再回退到持久清单，最后取首个员工。"""
    if conv_id in _conversations:
        return _conversations[conv_id]
    meta = conversations.get(conv_id)
    if meta:
        return meta["employee_id"]
    return runtime.discover_employees()[0]["id"]

def text_of(msg) -> str:
    """把 LangChain 消息内容统一成字符串（兼容多模态 list 形式）。"""
    c = getattr(msg, "content", "")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
    return str(c)

def reconstruct(messages: list) -> list[dict]:
    """把 LangGraph 的扁平消息流重构成前端好渲染的"轮次"：
    每轮 = 一条 user 消息 + 其后的 assistant 回复（含该轮内调用的工具）。"""
    turns: list[dict] = []
    cur_ai: dict | None = None
    pending: list[dict] = []  # 等待 ToolMessage 回填结果的工具调用
    for m in messages:
        tname = type(m).__name__
        if tname == "HumanMessage":
            turns.append({"role": "user", "content": text_of(m)})
            cur_ai, pending = None, []
        elif tname == "AIMessage":
            tcs = [{"name": tc.get("name"), "args": tc.get("args"), "result": None}
                    for tc in (getattr(m, "tool_calls", None) or [])]
            txt = text_of(m)
            if tcs:  # 这一 AI 步发起了工具调用
                if cur_ai is None:
                    cur_ai = {"role": "assistant", "content": "", "tool_calls": []}
                    turns.append(cur_ai)
                cur_ai["tool_calls"].extend(tcs)
                pending.extend(tcs)
            if txt.strip():  # 这一 AI 步产出了可见文本
                if cur_ai is not None and not cur_ai["content"]:
                    cur_ai["content"] = txt
                else:
                    cur_ai = {"role": "assistant", "content": txt, "tool_calls": []}
                    turns.append(cur_ai)
                pending = []
        elif tname == "ToolMessage":
            for tc in pending:
                if tc["result"] is None:
                    tc["result"] = text_of(m)[:2000]
                    break
    # 丢弃既无文本也无工具调用的空 assistant 占位
    return [t for t in turns
            if t["role"] == "user" or t["content"].strip() or t["tool_calls"]]

async def recover_conversations():
    """启动恢复：扫描 checkpointer 里所有 c_ 开头的历史线程，
    按"checkpoint 里的 skills_metadata 命中哪个员工的技能"判定归属，
    把今天已有的对话登记进会话清单（幂等，已登记的跳过）。"""
    con = sqlite3.connect(str(db_path("demo.db")))
    threads = [r[0] for r in con.execute(
        "SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id LIKE 'c_%'").fetchall()]
    con.close()

    emps = runtime.discover_employees()
    skill_index: dict[str, str] = {}
    for e in emps:
        for sk in e["skills"]:
            skill_index.setdefault(sk, e["id"])
    default_emp = emps[0]["id"]
    known = set(conversations.all_conv_ids())

    for tid in threads:
        if tid in known:
            continue
        emp = default_emp
        # 用最新 checkpoint 的 blob 做技能命中匹配
        con = sqlite3.connect(str(db_path("demo.db")))
        row = con.execute(
            "SELECT checkpoint FROM checkpoints WHERE thread_id=? ORDER BY rowid DESC LIMIT 1",
            (tid,)).fetchone()
        con.close()
        if row and row[0]:
            blob = row[0] if isinstance(row[0], bytes) else row[0].encode("utf-8", "replace")
            for skill, eid in skill_index.items():
                if skill.encode("utf-8") in blob:
                    emp = eid
                    break
        first = ""
        try:
            agent, _ = await runtime.get_agent(emp)
            states = [s async for s in agent.aget_state_history(
                {"configurable": {"thread_id": tid}}, limit=1)]
            msgs = states[0].values.get("messages", []) if states else []
            first = next((text_of(m) for m in msgs if type(m).__name__ == "HumanMessage"), "")
        except Exception:
            pass
        conversations.create(tid, emp, title=(first[:40] or "历史对话"), preview=first[:60])


class MessageIn(BaseModel):
    message: str

class DecisionIn(BaseModel):
    decision: str  # approve / reject

def sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


async def _gen_title(conv_id: str, user_text: str, bot_text: str):
    """用模型把首轮对话提炼成 ≤16 字标题，覆盖首句截断的默认标题。失败静默。"""
    try:
        m = _init_model(os.environ.get("MODEL_NAME", ""))
        prompt = ("请根据以下对话生成一个不超过16个字的中文标题，"
                  "直接输出标题文字，不要引号、不要解释、不要句号。\n"
                  f"用户：{user_text[:200]}\n助手：{bot_text[:200]}")
        r = await m.ainvoke([HumanMessage(content=prompt)])
        title = r.content.strip().strip('"').strip("“”").strip("《》")[:24]
        if title:
            conversations.set_title(conv_id, title)
    except Exception:
        pass

def _extract_interrupt(payload) -> tuple[str, dict]:
    it = payload[0] if isinstance(payload, (list, tuple)) else payload
    value = getattr(it, "value", it)
    if isinstance(value, dict):
        reqs = value.get("action_requests") or []
        if reqs:
            return reqs[0].get("name", "unknown"), reqs[0].get("args", {})
    return "unknown", {"raw": str(value)[:300]}

async def _stream_run(conv_id: str, input_, user_id: str = "default", role: str = "user"):
    """一次执行的统一事件翻译（新消息或审批 resume 都走这里）。
    user_id 写进 config.configurable，记忆 StoreBackend namespace 据此隔离。
    role=admin 用纯模板编译；普通用户用「模板 + 自己的覆盖」合并编译（A/B 互不影响）。"""
    emp_id = employee_of(conv_id)
    await runtime.ensure_user_memory(user_id, emp_id)  # 用户级记忆懒初始化
    if role == "admin":
        agent, stage_meta = await runtime.get_agent(emp_id)
    else:
        asg = catalog.get_assignment(user_id, emp_id)
        overrides = asg["overrides"] if asg else {}
        agent, stage_meta = await runtime.get_agent(emp_id, user_id, overrides)
    for st in stage_meta:
        yield sse({"type": "stage", **st})

    # ---- 执行过程追踪（trace）：每次运行一条 run，事件经回调落 traces.db ----
    input_preview, kind = "", "resume"
    try:
        if isinstance(input_, dict) and input_.get("messages"):
            kind = "message"
            m0 = input_["messages"][0]
            input_preview = m0.get("content", "") if isinstance(m0, dict) else str(m0)
    except Exception:
        pass
    trace_run_id = traces.start_run(conv_id, emp_id, user_id,
                                    input_preview=input_preview, kind=kind)
    tracer = traces.TraceHandler(trace_run_id)

    config = {"configurable": {"thread_id": conv_id, "user_id": user_id},
              "callbacks": [tracer]}
    skill_stage_on = False
    bot_text = ""  # 累积本轮 assistant 文本，用于首条消息提炼标题

    try:
        async for event in agent.astream(input_, config=config,
                                         stream_mode=["updates", "messages"], version="v2"):
            # version="v2": event 是 dict {"type":..,"ns":..,"data":..}
            # 兼容 v1: event 是 (mode, chunk) 元组
            if isinstance(event, dict):
                mode, chunk = event["type"], event["data"]
            else:
                mode, chunk = event

            if mode == "messages":
                # v2: chunk["data"] = (token, metadata) 元组（doc: token, metadata = chunk["data"]）
                msg, _meta = chunk if isinstance(chunk, tuple) else (chunk, None)
                if isinstance(msg, AIMessageChunk) and isinstance(msg.content, str) and msg.content:
                    bot_text += msg.content
                    yield sse({"type": "token", "content": msg.content})
                continue

            # mode == "updates"
            for node, update in chunk.items():
                if node == "__interrupt__":
                    tool_name, tool_args = _extract_interrupt(update)
                    record = approvals.create(conv_id, emp_id, tool_name, tool_args)
                    yield sse({"type": "approval_required", "approval_id": record["approval_id"],
                               "tool": tool_name, "args": tool_args})
                    tracer.flush_pending()
                    traces.finish_run(trace_run_id, status="interrupted")
                    return
                if not isinstance(update, dict):
                    continue

                # 模型思考（reasoning_content / thinking）→ 透明展示
                rc = update.get("reasoning_content") or update.get("thinking")
                if rc and rc.strip():
                    yield sse({"type": "thinking", "content": rc})

                if update.get("todos"):
                    todos = [{"content": t.get("content", ""), "status": t.get("status", "")}
                             for t in update["todos"]]
                    yield sse({"type": "todos", "items": todos})

                for m in update.get("messages", []) or []:
                    if isinstance(m, ToolMessage):
                        name = m.name or "tool"
                        preview = (m.content if isinstance(m.content, str) else str(m.content))[:120]
                        yield sse({"type": "tool", "name": name, "args": {}, "status": "end", "preview": preview})
                    elif getattr(m, "tool_calls", None):
                        for tc in m.tool_calls:
                            name, args = tc.get("name", ""), tc.get("args", {})
                            yield sse({"type": "tool", "name": name, "args": args, "status": "start"})
                            if not skill_stage_on:
                                skill_stage_on = True
                                yield sse({"type": "stage", "stage": "skill", "status": "active",
                                           "detail_text": f"调用 {name}"})
                            if "SKILL.md" in json.dumps(args, ensure_ascii=False):
                                skill_name = re.search(r"skills/([^/]+)/SKILL\.md", json.dumps(args))
                                yield sse({"type": "stage", "stage": "skill", "status": "active",
                                           "detail_text": f"激活技能：{skill_name.group(1) if skill_name else ''}"})

        # 正常结束：流水线收尾（正常对话，不生成分析报告）
        tracer.flush_pending()
        traces.finish_run(trace_run_id, status="done")
        yield sse({"type": "stage", "stage": "report", "status": "done"})
        # 首条消息：后台提炼标题（不阻塞流关闭）
        meta = conversations.get(conv_id)
        if meta and (meta.get("message_count") or 0) <= 1 and bot_text.strip():
            user_text = ""
            try:
                msgs = input_.get("messages") if isinstance(input_, dict) else None
                if msgs:
                    user_text = msgs[0].get("content", "") if isinstance(msgs[0], dict) else str(msgs[0])
            except Exception:
                pass
            asyncio.create_task(_gen_title(conv_id, user_text, bot_text))
    except Exception as e:  # 模型 key 未配、网络异常等
        tracer.flush_pending()
        traces.finish_run(trace_run_id, status="error", error=f"{type(e).__name__}: {e}")
        yield sse({"type": "error", "message": f"{type(e).__name__}: {e}"})

# ---------------------------------------------------------------------------
# 认证
# ---------------------------------------------------------------------------

class LoginIn(BaseModel):
    username: str
    password: str


# 登录限流：内存滑动窗口，按 (client_ip, username) 记失败次数。
# 60 秒窗口内失败 >=5 次则锁定该组合 60 秒。单进程内存实现，重启即清零（自托管够用）。
_LOGIN_FAILS: dict = {}          # key -> [fail_ts, ...]
_LOGIN_WINDOW = 60.0
_LOGIN_MAX_FAILS = 5


def _login_throttled(key: str) -> bool:
    now = time.time()
    fails = [t for t in _LOGIN_FAILS.get(key, []) if now - t < _LOGIN_WINDOW]
    _LOGIN_FAILS[key] = fails
    return len(fails) >= _LOGIN_MAX_FAILS


def _login_record_fail(key: str):
    _LOGIN_FAILS.setdefault(key, []).append(time.time())


@app.post("/api/auth/login")
async def login(body: LoginIn, request: Request):
    ip = request.client.host if request.client else "?"
    key = f"{ip}|{body.username}"
    if _login_throttled(key):
        raise HTTPException(429, "尝试过于频繁，请 1 分钟后再试")
    u = catalog.get_user_by_username(body.username)
    if not u or not auth.verify_password(body.password, u["password_hash"]):
        _login_record_fail(key)
        log.warning("登录失败：用户名或密码错误 username=%s ip=%s", body.username, ip)
        raise HTTPException(401, "用户名或密码错误")
    if u.get("status") != "active":
        log.warning("登录被拒：账号已禁用 username=%s ip=%s", body.username, ip)
        raise HTTPException(403, "账号已禁用")
    _LOGIN_FAILS.pop(key, None)
    log.info("登录成功 username=%s role=%s ip=%s", u["username"], u.get("role"), ip)
    token = auth.create_token(u)
    return {"token": token,
            "must_change_password": bool(u.get("must_change_password")),
            "user": {"id": u["id"], "username": u["username"],
                     "role": u["role"], "tenant_id": u.get("tenant_id", "default")}}


class ChangePwdIn(BaseModel):
    old_password: str
    new_password: str


@app.post("/api/auth/change-password")
async def change_password(body: ChangePwdIn, user: dict = Depends(auth.get_current_user)):
    u = catalog.get_user_by_username(user["username"])
    if not u or not auth.verify_password(body.old_password, u["password_hash"]):
        raise HTTPException(401, "原密码错误")
    if len(body.new_password) < 8:
        raise HTTPException(400, "新密码至少 8 位")
    if body.new_password == body.old_password:
        raise HTTPException(400, "新密码不能与原密码相同")
    catalog.set_password(u["id"], auth.hash_password(body.new_password))
    return {"ok": True}

@app.get("/api/auth/me")
async def me(user: dict = Depends(auth.get_current_user)):
    return {"id": user["id"], "username": user["username"], "role": user["role"],
            "tenant_id": user.get("tenant_id", "default")}


# ---------------------------------------------------------------------------
# 对话 / 会话（登录用户，token 优先、回落 X-User-Id 兼容演示）
# ---------------------------------------------------------------------------

@app.get("/api/employees")
async def list_employees(user: dict = Depends(auth.get_current_user)):
    """员工注册表，供前端选择器。
    管理员返回全部员工；普通用户只返回已分配的（按 user_employee_assignments）。"""
    if user.get("role") == "admin":
        return runtime.discover_employees()
    return runtime.discover_assigned_employees(user["id"])


@app.get("/api/catalog")
async def public_catalog(user: dict = Depends(auth.get_current_user)):
    """登录用户可读的目录（技能/工具/知识库/SOP），供普通用户"我的调整"勾选用。
    不含连接器（含配置密钥），避免泄露。"""
    c = catalog.catalog()
    c.pop("connectors", None)
    return c


@app.get("/api/knowledge-bases/{kb_id}/entries")
async def public_kb_entries(kb_id: str, user: dict = Depends(auth.get_current_user)):
    """登录用户可读的知识库条目列表（只读，不含编辑接口）。"""
    return catalog.list_kb_entries(kb_id)

@app.post("/api/employees/{emp_id}/conversations")
async def new_conversation(emp_id: str, user: dict = Depends(auth.get_current_user_or_fallback)):
    """用某员工开新会话，返回 conversation_id 并登记 conv→emp 映射。
    普通用户必须先被分配该员工，否则 403。"""
    uid = user["id"]
    if user.get("role") != "admin" and emp_id not in catalog.assigned_employee_ids(uid):
        return {"error": "该数字员工未分配给你，请联系管理员"}
    conv_id = "c_" + __import__("time").strftime("%Y%m%d%H%M%S") + str(__import__("time").time()).split(".")[1]
    # 仅登记内存热映射（供 employee_of 在首条消息时路由到正确的员工），【不落库】。
    # 用户还没说话就该有条历史记录——空会话不应保存；真正写入发生在首条消息（send_message 里
    # conversations.exists 为假时 create）。这样刷新页面 / 点“新会话”不会往历史里塞空记录。
    _conversations[conv_id] = emp_id
    return {"conversation_id": conv_id, "employee_id": emp_id, "user_id": uid}

@app.get("/api/conversations")
async def list_conv(employee_id: str = None,
                    user: dict = Depends(auth.get_current_user_or_fallback),
                    page: int | None = None, page_size: int = 10, limit: int | None = None):
    """会话清单。带 page 时返回分页 {items,total,...}（历史管理页用）；
    否则返回列表（侧栏用，可加 limit 限制最近条数）。"""
    uid = user["id"]
    if page:
        return conversations.list_paged(employee_id, user_id=uid, page=page, page_size=page_size)
    return conversations.list_for(employee_id, user_id=uid, limit=limit)


@app.delete("/api/conversations/{conv_id}")
async def delete_conv(conv_id: str, user: dict = Depends(auth.get_current_user_or_fallback)):
    """软删会话：仅标记元数据为已删除，校验属主。
    checkpointer（demo.db）里的对话正文保留，便于日后恢复。"""
    meta = conversations.get(conv_id)
    if not meta:
        return {"error": "会话不存在"}
    uid = user["id"]
    if meta.get("user_id", "default") != uid:
        return {"error": "无权删除该会话"}
    conversations.delete(conv_id)
    return {"ok": True}

@app.get("/api/conversations/{conv_id}")
async def get_conv(conv_id: str, user: dict = Depends(auth.get_current_user_or_fallback)):
    """读取某会话的完整历史（从 checkpointer 还原消息并重构轮次）。
    校验属主：非该用户的会话拒绝访问。"""
    meta = conversations.get(conv_id)
    if not meta:
        return {"error": "会话不存在或已清理"}
    uid = user["id"]
    if meta.get("user_id", "default") != uid:
        return {"error": "无权访问该会话"}
    emp = meta["employee_id"]
    agent, _ = await runtime.get_agent(emp)
    states = [s async for s in agent.aget_state_history(
        {"configurable": {"thread_id": conv_id}}, limit=1)]
    msgs = states[0].values.get("messages", []) if states else []
    return {
        "employee_id": emp,
        "title": meta["title"],
        "message_count": meta["message_count"],
        "turns": reconstruct(msgs),
    }

@app.post("/api/conversations/{conv_id}/messages")
async def send_message(conv_id: str, body: MessageIn,
                       user: dict = Depends(auth.get_current_user_or_fallback)):
    uid = user["id"]
    emp = employee_of(conv_id)
    text = body.message.strip()
    # 首条消息：以首句定标题；后续：更新预览/计数
    if not conversations.exists(conv_id):
        conversations.create(conv_id, emp, title=text[:40], preview=text[:60],
                             count=1, user_id=uid)
    else:
        conversations.touch(conv_id, title=text[:40], preview=text[:60], bump=1)
    input_ = {"messages": [{"role": "user", "content": body.message}]}
    return StreamingResponse(_stream_run(conv_id, input_, user_id=uid, role=user.get("role", "user")),
                             media_type="text/event-stream")

@app.get("/api/conversations/{conv_id}/traces")
async def list_conv_traces(conv_id: str, user: dict = Depends(auth.get_current_user_or_fallback)):
    """某会话的全部执行 trace（一次消息/审批恢复 = 一条 run）。属主或管理员可看。"""
    meta = conversations.get(conv_id)
    if not meta:
        return {"error": "会话不存在"}
    if user.get("role") != "admin" and meta.get("user_id", "default") != user["id"]:
        return {"error": "无权查看该会话的执行记录"}
    return {"conv_id": conv_id, "title": meta.get("title", ""),
            "employee_id": meta.get("employee_id", ""), "runs": traces.list_runs(conv_id)}

@app.get("/api/traces/{run_id}")
async def get_trace_detail(run_id: str, user: dict = Depends(auth.get_current_user_or_fallback)):
    """单次运行的完整执行过程（LLM/工具事件时间线）。属主或管理员可看。"""
    run = traces.get_run(run_id)
    if not run:
        return {"error": "执行记录不存在"}
    if user.get("role") != "admin" and run.get("user_id") != user["id"]:
        return {"error": "无权查看该执行记录"}
    return run

@app.post("/api/approvals/{approval_id}/decision")
async def decide(approval_id: str, body: DecisionIn):
    record = approvals.decide(approval_id, body.decision)
    if not record:
        return {"error": "审批单不存在或已处理"}
    meta = conversations.get(record["conversation_id"])
    uid = meta.get("user_id", "default") if meta else "default"
    resume = Command(resume={"decisions": [{"type": body.decision}]})
    return StreamingResponse(_stream_run(record["conversation_id"], resume, user_id=uid),
                             media_type="text/event-stream")

# ---------------------------------------------------------------------------
# 管理后台：数字员工页面化配置（全部要求 admin 登录）
# ---------------------------------------------------------------------------
admin_router = APIRouter(prefix="/api/admin", dependencies=[Depends(auth.require_admin)])


@admin_router.get("/catalog")
async def admin_catalog():
    """返回可选目录：技能 / 工具 / 知识库 / SOP / 连接器。"""
    return catalog.catalog()


@admin_router.get("/defaults")
async def admin_defaults():
    """返回新建员工时的默认取值（如默认模型名，含 openai: 前缀）。"""
    return {"model": os.environ.get("MODEL_NAME", "openai:deepseek-v4-flash")}


@admin_router.get("/employees")
async def admin_list_employees():
    """全部员工（含选中项与展示名），供管理页列表与表单回显。"""
    return [catalog.get_full_employee(e["id"]) for e in catalog.list_employees_meta()]


@admin_router.get("/employees/{emp_id}")
async def admin_get_employee(emp_id: str):
    cfg = catalog.get_full_employee(emp_id)
    if not cfg:
        return {"error": "员工不存在"}
    return cfg


@admin_router.post("/employees")
async def admin_create_employee(body: dict):
    emp_id = catalog.create_employee(body)
    runtime.invalidate(emp_id)
    return {"id": emp_id}


@admin_router.put("/employees/{emp_id}")
async def admin_update_employee(emp_id: str, body: dict):
    ok = catalog.update_employee(emp_id, body)
    if not ok:
        return {"error": "员工不存在"}
    runtime.invalidate(emp_id)
    return {"id": emp_id}


@admin_router.delete("/employees/{emp_id}")
async def admin_delete_employee(emp_id: str):
    catalog.delete_employee(emp_id)
    runtime.invalidate(emp_id)
    return {"ok": True}


# ---- 技能上传 / 删除（zip 上传 → 解压到 skills-custom/ → 登记 catalog）----

SKILLS_CUSTOM_DIR = PROJECT_ROOT / "backend" / "skills-custom"


@admin_router.post("/skills/upload")
async def upload_skill(file: UploadFile = File(...)):
    """上传一个 skill 的 zip 包：解压到 skills-custom/<id>/，并登记进目录库。
    zip 内需含 SKILL.md（可在根或某子目录下）。skill_id 取自 SKILL.md frontmatter
    的 name 字段（安全化），同名 skill 会被覆盖更新。"""
    if not (file.filename or "").lower().endswith(".zip"):
        return {"error": "只支持 .zip 文件"}
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        return {"error": "zip 过大（>20MB）"}
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return {"error": "无效的 zip 文件"}

    # 找 SKILL.md（跳过 macOS 的 __MACOSX 垃圾）
    names = [n for n in zf.namelist() if not n.startswith("__MACOSX") and not n.endswith("/")]
    skill_md_name = next((n for n in names if n.endswith("/SKILL.md")), None) \
        or next((n for n in names if n == "SKILL.md"), None)
    if not skill_md_name:
        zf.close()
        return {"error": "zip 内未找到 SKILL.md"}

    skill_md = zf.read(skill_md_name).decode("utf-8", "replace")
    name = description = ""
    for line in skill_md.splitlines():
        if line.startswith("name:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("description:"):
            description = line.split(":", 1)[1].strip()
        elif line.strip() == "" and name:
            break

    # skill_id 安全化：仅小写字母/数字/连字符
    raw = name or Path(file.filename).stem
    skill_id = re.sub(r"[^a-z0-9-]+", "-", raw.lower()).strip("-")
    if not skill_id:
        skill_id = "custom-skill"

    # 解压目标：剥掉 zip 顶层目录，使 SKILL.md 落到 target/SKILL.md
    prefix = (skill_md_name.rsplit("/", 1)[0] + "/") if "/" in skill_md_name else ""
    target = SKILLS_CUSTOM_DIR / skill_id
    target.mkdir(parents=True, exist_ok=True)
    # 更新场景：先清空目标目录
    for child in target.iterdir():
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    base = str(target.resolve())
    for member in names:
        if prefix and not member.startswith(prefix):
            continue
        rel = member[len(prefix):]
        if not rel or rel.startswith("..") or Path(rel).is_absolute():
            continue  # 防 zip slip
        dest = target / rel
        if not str(dest.resolve()).startswith(base):
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(zf.read(member))
    zf.close()

    catalog.upsert_skill(skill_id, name or skill_id, description, f"skills-custom/{skill_id}")
    return {"id": skill_id, "name": name or skill_id, "description": description}


@admin_router.delete("/skills/{skill_id}")
async def delete_skill(skill_id: str):
    """软删一个技能：仅允许删 skills-custom/ 下的（内置技能不可删）。
    软删 catalog 记录、硬删员工关联并 invalidate；磁盘目录文件保留以便恢复。"""
    info = catalog.get_skill(skill_id)
    if not info:
        return {"error": "技能不存在"}
    dir_ = info["dir"] or ""
    if not dir_.startswith("skills-custom/"):
        return {"error": "内置技能不允许删除"}
    # 软删：保留磁盘目录（skills-custom/<id>/），仅解除关联并软删 DB 记录
    affected = catalog.employees_using_skill(skill_id)
    catalog.delete_skill(skill_id)
    for emp_id in affected:
        runtime.invalidate(emp_id)
    return {"ok": True, "invalidated": affected}


@admin_router.get("/skills/{skill_id}/content")
async def skill_content(skill_id: str):
    """读取某技能的 SKILL.md 原文，供技能管理页查看。"""
    info = catalog.get_skill(skill_id)
    if not info:
        return {"error": "技能不存在"}
    p = PROJECT_ROOT / "backend" / info["dir"] / "SKILL.md"
    if not p.exists():
        return {"error": "SKILL.md 不存在"}
    return {"content": p.read_text(encoding="utf-8"), "path": str(p)}


# ---- 资源中心：工具 / 知识库(+条目) / SOP / 连接器 的 CRUD ----
# （技能已有上面 upload/delete/content 接口）

@admin_router.put("/tools/{tool_id}")
async def edit_tool(tool_id: str, body: dict):
    ok = catalog.update_tool(tool_id, body.get("description", ""), body.get("needs_approval"))
    if not ok:
        return {"error": "工具不存在"}
    for e in catalog.employees_using_tool(tool_id):
        runtime.invalidate(e)
    return {"ok": True}


@admin_router.post("/knowledge-bases")
async def create_kb(body: dict):
    kid = body.get("id") or ("kb_" + time.strftime("%Y%m%d%H%M%S"))
    catalog.create_kb(kid, body.get("name", kid), body.get("description", ""))
    return {"id": kid}


@admin_router.put("/knowledge-bases/{kb_id}")
async def edit_kb(kb_id: str, body: dict):
    ok = catalog.update_kb(kb_id, body.get("name", ""), body.get("description", ""))
    return {"ok": ok}


@admin_router.delete("/knowledge-bases/{kb_id}")
async def del_kb(kb_id: str):
    affected = catalog.delete_kb(kb_id)
    for e in affected:
        runtime.invalidate(e)
    return {"ok": True, "invalidated": affected}


@admin_router.get("/knowledge-bases/{kb_id}/entries")
async def list_entries(kb_id: str):
    return catalog.list_kb_entries(kb_id)


@admin_router.post("/knowledge-bases/{kb_id}/entries")
async def add_entry(kb_id: str, body: dict):
    eid = body.get("id") or ("E" + time.strftime("%m%d%H%M%S"))
    catalog.create_kb_entry(kb_id, eid, body.get("title", ""),
                            body.get("keywords", []), body.get("content", ""))
    for e in catalog._unlink_view("kb", kb_id):
        runtime.invalidate(e)
    return {"id": eid}


@admin_router.put("/knowledge-bases/{kb_id}/entries/{eid}")
async def edit_entry(kb_id: str, eid: str, body: dict):
    ok = catalog.update_kb_entry(eid, body.get("title", ""),
                                 body.get("keywords", []), body.get("content", ""))
    for e in catalog._unlink_view("kb", kb_id):
        runtime.invalidate(e)
    return {"ok": ok}


@admin_router.delete("/knowledge-bases/{kb_id}/entries/{eid}")
async def del_entry(kb_id: str, eid: str):
    ok = catalog.delete_kb_entry(eid)
    for e in catalog._unlink_view("kb", kb_id):
        runtime.invalidate(e)
    return {"ok": ok}


@admin_router.post("/sops")
async def create_sop(body: dict):
    sid = body.get("id") or ("sop_" + time.strftime("%Y%m%d%H%M%S"))
    catalog.create_sop(sid, body.get("name", sid), body.get("description", ""), body.get("content", ""))
    return {"id": sid}


@admin_router.put("/sops/{sop_id}")
async def edit_sop(sop_id: str, body: dict):
    ok = catalog.update_sop(sop_id, body.get("name", ""), body.get("description", ""), body.get("content", ""))
    return {"ok": ok}


@admin_router.delete("/sops/{sop_id}")
async def del_sop(sop_id: str):
    affected = catalog.delete_sop(sop_id)
    for e in affected:
        runtime.invalidate(e)
    return {"ok": True, "invalidated": affected}


@admin_router.post("/connectors")
async def create_connector(body: dict):
    cid = body.get("id") or ("conn_" + time.strftime("%Y%m%d%H%M%S"))
    catalog.create_connector(cid, body.get("name", cid), body.get("description", ""), body.get("config", {}))
    return {"id": cid}


@admin_router.get("/connectors/{conn_id}")
async def get_connector(conn_id: str):
    c = catalog.get_connector(conn_id)
    if not c:
        return {"error": "连接器不存在"}
    return c


@admin_router.put("/connectors/{conn_id}")
async def edit_connector(conn_id: str, body: dict):
    ok = catalog.update_connector(conn_id, body.get("name", ""), body.get("description", ""), body.get("config", {}))
    for e in catalog._unlink_view("connector", conn_id):
        runtime.invalidate(e)
    return {"ok": ok}


@admin_router.delete("/connectors/{conn_id}")
async def del_connector(conn_id: str):
    affected = catalog.delete_connector(conn_id)
    for e in affected:
        runtime.invalidate(e)
    return {"ok": True, "invalidated": affected}


# ---- 用户管理（admin） ----

class UserCreateIn(BaseModel):
    username: str
    password: str
    role: str = "user"

class UserUpdateIn(BaseModel):
    role: str | None = None
    status: str | None = None

class PasswordIn(BaseModel):
    password: str

@admin_router.get("/users")
async def list_users_api():
    return catalog.list_users()

@admin_router.post("/users")
async def create_user_api(body: UserCreateIn):
    if catalog.get_user_by_username(body.username):
        return {"error": "用户名已存在"}
    if body.role not in ("admin", "user"):
        return {"error": "role 必须是 admin 或 user"}
    uid = catalog.create_user(body.username, auth.hash_password(body.password), role=body.role)
    return {"id": uid, "username": body.username, "role": body.role}

@admin_router.put("/users/{uid}")
async def update_user_api(uid: str, body: UserUpdateIn, admin: dict = Depends(auth.require_admin)):
    if uid == admin["id"] and body.status == "disabled":
        return {"error": "不能禁用当前登录的管理员"}
    ok = catalog.update_user(uid, role=body.role, status=body.status)
    return {"ok": ok}

@admin_router.put("/users/{uid}/password")
async def reset_password_api(uid: str, body: PasswordIn):
    ok = catalog.set_password(uid, auth.hash_password(body.password))
    return {"ok": ok}

@admin_router.delete("/users/{uid}")
async def delete_user_api(uid: str, admin: dict = Depends(auth.require_admin)):
    if uid == admin["id"]:
        return {"error": "不能删除当前登录的管理员"}
    # 保护：不允许删掉最后一个 admin
    admins = [u for u in catalog.list_users() if u["role"] == "admin" and u["status"] == "active"]
    target = catalog.get_user(uid)
    if target and target["role"] == "admin" and len(admins) <= 1:
        return {"error": "至少保留一个管理员"}
    return {"ok": catalog.delete_user(uid)}

# ---- 用户-员工分配（admin） ----

@admin_router.get("/users/{uid}/employees")
async def admin_list_user_employees(uid: str):
    """列出全部员工 + 该用户是否已分配 + 当前覆盖。"""
    if not catalog.get_user(uid):
        return {"error": "用户不存在"}
    assigns = {a["employee_id"]: a["overrides"] for a in catalog.list_assignments(uid)}
    emps = catalog.list_employees_meta()
    return {
        "user_id": uid,
        "employees": [{
            "employee_id": e["id"], "name": e["name"], "role": e["role"],
            "granted": e["id"] in assigns, "overrides": assigns.get(e["id"], {}),
        } for e in emps],
    }


@admin_router.post("/users/{uid}/employees")
async def admin_assign_employee(uid: str, body: dict,
                                admin: dict = Depends(auth.require_admin)):
    """分配一个员工给用户（可带预置 overrides）。"""
    if not catalog.get_user(uid):
        return {"error": "用户不存在"}
    emp_id = body.get("employee_id")
    if not catalog.get_employee_config(emp_id):
        return {"error": "员工不存在"}
    catalog.assign_employee(uid, emp_id, body.get("overrides"), granted_by=admin["id"])
    runtime.invalidate(emp_id)
    return {"ok": True, "employee_id": emp_id}


@admin_router.put("/users/{uid}/employees/{emp_id}")
async def admin_update_assignment(uid: str, emp_id: str, body: dict,
                                  admin: dict = Depends(auth.require_admin)):
    """更新某用户对该员工的覆盖（admin 预置/修正）。"""
    if not catalog.get_assignment(uid, emp_id):
        return {"error": "该用户未分配此员工"}
    catalog.set_assignment_overrides(uid, emp_id, body.get("overrides", {}))
    runtime.invalidate(emp_id)
    return {"ok": True}


@admin_router.delete("/users/{uid}/employees/{emp_id}")
async def admin_unassign_employee(uid: str, emp_id: str,
                                   admin: dict = Depends(auth.require_admin)):
    """取消分配。"""
    ok = catalog.unassign_employee(uid, emp_id)
    runtime.invalidate(emp_id)
    return {"ok": ok}


app.include_router(admin_router)


# ---------------------------------------------------------------------------
# 普通用户自助：查看/调整自己已分配员工的覆盖（仅作用自己）
# ---------------------------------------------------------------------------

@app.get("/api/me/employees")
async def my_employees(user: dict = Depends(auth.get_current_user)):
    """我分配到的员工 + 基础能力 + 我的覆盖 + 合并后的有效能力。"""
    out = []
    for a in catalog.list_assignments(user["id"]):
        eid = a["employee_id"]
        base = catalog.get_employee_config(eid) or {}
        eff = catalog.get_effective_config(user["id"], eid) or base
        out.append({
            "employee_id": eid, "name": base.get("name"), "role": base.get("role"),
            "overrides": a["overrides"],
            "base": {"skills": base.get("skills", []), "tools": base.get("tools", []),
                     "kbs": base.get("kbs", []), "sops": base.get("sops", []),
                     "connectors": base.get("connectors", [])},
            "effective": {"skills": eff.get("skills", []), "tools": eff.get("tools", []),
                          "kbs": eff.get("kbs", []), "sops": eff.get("sops", []),
                          "connectors": eff.get("connectors", [])},
        })
    return out


@app.get("/api/me/employees/{emp_id}")
async def my_employee_detail(emp_id: str, user: dict = Depends(auth.get_current_user)):
    if emp_id not in catalog.assigned_employee_ids(user["id"]):
        return {"error": "该数字员工未分配给你"}
    base = catalog.get_employee_config(emp_id) or {}
    asg = catalog.get_assignment(user["id"], emp_id) or {}
    eff = catalog.get_effective_config(user["id"], emp_id) or base
    return {
        "employee_id": emp_id, "name": base.get("name"),
        "overrides": asg.get("overrides", {}),
        "base": {"skills": base.get("skills", []), "tools": base.get("tools", []),
                 "kbs": base.get("kbs", []), "sops": base.get("sops", []),
                 "connectors": base.get("connectors", [])},
        "effective": {"skills": eff.get("skills", []), "tools": eff.get("tools", []),
                      "kbs": eff.get("kbs", []), "sops": eff.get("sops", []),
                      "connectors": eff.get("connectors", [])},
    }


@app.put("/api/me/employees/{emp_id}/overrides")
async def update_my_overrides(emp_id: str, body: dict,
                               user: dict = Depends(auth.get_current_user)):
    """更新我对这个已分配员工的覆盖（add/remove）。仅写自己的分配行，不改模板。
    overrides 形如 {"add":{"skills":[...],...}, "remove":{"skills":[...],...}}。"""
    if emp_id not in catalog.assigned_employee_ids(user["id"]):
        return {"error": "该数字员工未分配给你，无法调整"}
    ov = body.get("overrides", {})
    if not isinstance(ov, dict):
        return {"error": "overrides 必须是对象"}
    keys = ("skills", "tools", "kbs", "sops", "connectors")
    add = ov.get("add") if isinstance(ov.get("add"), dict) else {}
    remove = ov.get("remove") if isinstance(ov.get("remove"), dict) else {}
    clean = {
        "add": {k: (add.get(k, []) if isinstance(add.get(k), list) else []) for k in keys},
        "remove": {k: (remove.get(k, []) if isinstance(remove.get(k), list) else []) for k in keys},
    }
    catalog.set_assignment_overrides(user["id"], emp_id, clean)
    runtime.invalidate(emp_id)
    return {"ok": True, "overrides": clean}


@app.get("/api/debug/memory")
async def debug_memory(employee_id: str = "xiaosu",
                       user: dict = Depends(auth.require_admin)):
    """调试用：查看某员工虚拟文件系统里 /memories、/skills 的实体内容。仅管理员。"""
    return {"namespace": [employee_id], "items": await runtime.dump_store(employee_id)}

@app.get("/")
async def index():
    return FileResponse(PROJECT_ROOT / "frontend" / "index.html")


app.mount("/src", StaticFiles(directory=str(PROJECT_ROOT / "frontend" / "src")), name="src")
app.mount("/node_modules", StaticFiles(directory=str(PROJECT_ROOT / "frontend" / "node_modules")), name="node_modules")

# 数据分析师生成的可视化看板按用户隔离：workspace/data/{user_id}/xxx.html
# 访问走鉴权接口 /api/dashboards/{user_id}/{filename}，校验属主（非本人 403）
_DASH_DIR = ROOT / "workspace" / "data"
_DASH_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/api/dashboards/{user_id}/{filename:path}")
async def get_dashboard(user_id: str, filename: str,
                        user: dict = Depends(auth.get_current_user)):
    """按用户隔离的看板访问：只能看自己的。"""
    if user["id"] != user_id:
        raise _forbidden("无权访问该看板")
    user_dir = (_DASH_DIR / user_id).resolve()
    p = (user_dir / filename).resolve()
    # 防路径穿越
    try:
        p.relative_to(user_dir)
    except ValueError:
        raise _forbidden("非法路径")
    if not p.exists() or not p.is_file():
        raise _not_found("看板不存在")
    return FileResponse(p)


def _forbidden(msg):
    from fastapi import HTTPException
    return HTTPException(403, msg)


def _not_found(msg):
    from fastapi import HTTPException
    return HTTPException(404, msg)
