"""Tool 层：知识库检索与工单登记（demo 用关键词匹配，生产替换为向量检索）。"""
import re
import time
from langchain.tools import tool

FAQ = [
    {"id": "FAQ-001", "title": "X1 智能音箱续航", "keywords": ["x1", "续航", "电池", "多久"],
     "content": "X1 智能音箱内置 5000mAh 电池，中等音量下连续播放约 12 小时，待机约 72 小时。"},
    {"id": "FAQ-002", "title": "X1 智能音箱售价", "keywords": ["x1", "价格", "多少钱", "售价"],
     "content": "X1 智能音箱官方售价 399 元，大促期间通常 349 元。"},
    {"id": "FAQ-003", "title": "整机保修政策", "keywords": ["保修", "质保", "售后政策", "维修"],
     "content": "全系产品整机保修 1 年，主要部件保修 2 年；保修期内非人为损坏免费维修。"},
    {"id": "FAQ-004", "title": "七天无理由退货", "keywords": ["退货", "七天", "无理由", "退款政策"],
     "content": "签收后 7 天内支持无理由退货（需包装配件完好），退款原路返回，3-5 个工作日到账。"},
    {"id": "FAQ-005", "title": "S2 台灯色温调节", "keywords": ["s2", "台灯", "色温", "亮度"],
     "content": "S2 智能台灯支持 2700K-6500K 无级色温调节，亮度 1%-100% 可调，支持 App 定时。"},
    {"id": "FAQ-006", "title": "售后人工渠道", "keywords": ["人工", "客服电话", "联系方式", "转人工"],
     "content": "人工客服热线 400-800-1234（9:00-21:00），也可在 App「我的-售后服务」提交在线工单。"},
]


@tool
def kb_search(query: str) -> str:
    """检索产品知识库。输入产品名/主题关键词，返回匹配的 FAQ 条目（含条目号，回答时需标注依据）。"""
    q = query.lower()
    hits = []
    for item in FAQ:
        score = sum(1 for k in item["keywords"] if k in q)
        if score:
            hits.append((score, item))
    hits.sort(key=lambda x: -x[0])
    if not hits:
        return "未检索到相关条目。请换关键词重试；若仍无结果，告知用户需要核实并建议转人工。"
    return "\n\n".join(
        f"[{it['id']}] {it['title']}\n{it['content']}" for _, it in hits[:3]
    )


@tool
def create_ticket(category: str, urgency: str, summary: str) -> str:
    """登记客服工单。urgency 取 urgent/high/normal。返回工单号与预计响应时间。"""
    assert urgency in ("urgent", "high", "normal"), "urgency 必须是 urgent/high/normal"
    ticket_id = "T" + time.strftime("%m%d%H%M%S")
    sla = {"urgent": "2 小时", "high": "24 小时", "normal": "48 小时"}[urgency]
    return f"工单已登记：{ticket_id}（类别：{category}，紧急度：{urgency}）。预计响应时间：{sla}。"
