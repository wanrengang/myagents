"""审批中心（demo 内存版）：中断工单创建、查询、决策。

生产版应落库并加超时自动 reject，见平台技术方案 §6。
"""
import itertools
import time

_seq = itertools.count(1)
_approvals: dict[str, dict] = {}


def create(conversation_id: str, employee_id: str, tool_name: str, tool_args: dict,
           inner_thread: str | None = None) -> dict:
    """创建审批单。

    inner_thread 非空时，表示这是 workflow 内层图审批（Point2：refund StateGraph
    的 await_approval 节点 interrupt 产生）。decision 端点据此走双路径：
    有 inner_thread → 先 resume_refund 恢复内层图，再 resume 外层 agent；
    无 inner_thread → 老路径（外层 interrupt_on 的轻量确认，如 create_ticket）。
    """
    approval_id = f"ap_{next(_seq):04d}"
    record = {
        "approval_id": approval_id,
        "conversation_id": conversation_id,
        "employee_id": employee_id,
        "tool": tool_name,
        "args": tool_args,
        "inner_thread": inner_thread,
        "status": "pending",
        "created_at": time.strftime("%H:%M:%S"),
    }
    _approvals[approval_id] = record
    return record


def decide(approval_id: str, decision: str) -> dict | None:
    record = _approvals.get(approval_id)
    if record and record["status"] == "pending" and decision in ("approve", "reject"):
        record["status"] = decision
        return record
    return None
