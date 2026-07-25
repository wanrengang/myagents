"""审批中心（demo 内存版）：中断工单创建、查询、决策。

生产版应落库并加超时自动 reject，见平台技术方案 §6。
"""
import itertools
import time

_seq = itertools.count(1)
_approvals: dict[str, dict] = {}


def create(conversation_id: str, employee_id: str, tool_name: str, tool_args: dict) -> dict:
    approval_id = f"ap_{next(_seq):04d}"
    record = {
        "approval_id": approval_id,
        "conversation_id": conversation_id,
        "employee_id": employee_id,
        "tool": tool_name,
        "args": tool_args,
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
