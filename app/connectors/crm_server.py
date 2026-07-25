"""Connector 层：CRM 连接器（FastMCP stdio server，mock 数据）。"""
from fastmcp import FastMCP

mcp = FastMCP("crm")

ORDERS = {
    "O12345": {"order_id": "O12345", "product": "X1 智能音箱", "amount": 399.0,
               "status": "已签收", "sign_date": "2026-07-22", "customer": "张总", "phone": "138****5678"},
    "O12346": {"order_id": "O12346", "product": "S2 智能台灯", "amount": 199.0,
               "status": "已签收", "sign_date": "2026-07-15", "customer": "李经理", "phone": "139****9012"},
    "O12347": {"order_id": "O12347", "product": "X1 智能音箱", "amount": 399.0,
               "status": "运输中", "sign_date": None, "customer": "张总", "phone": "138****5678"},
    "O12348": {"order_id": "O12348", "product": "W5 智能手表（硅胶版）", "amount": 599.0,
               "status": "已签收", "sign_date": "2026-07-24", "customer": "王老师", "phone": "136****2345"},
    "O12349": {"order_id": "O12349", "product": "H7 降噪耳机", "amount": 499.0,
               "status": "已签收", "sign_date": "2026-07-20", "customer": "陈工", "phone": "158****6789"},
    "O12350": {"order_id": "O12350", "product": "P3 智能投影仪", "amount": 2599.0,
               "status": "运输中", "sign_date": None, "customer": "李经理", "phone": "139****9012"},
    "O12351": {"order_id": "O12351", "product": "S2 Pro 双灯头台灯", "amount": 299.0,
               "status": "已签收", "sign_date": "2026-07-05", "customer": "赵女士", "phone": "137****3456"},
    "O12352": {"order_id": "O12352", "product": "X1 智能音箱（白色）", "amount": 399.0,
               "status": "已签收", "sign_date": "2026-05-26", "customer": "周同学", "phone": "150****7890"},
    "O12353": {"order_id": "O12353", "product": "H7 Pro 降噪耳机", "amount": 699.0,
               "status": "已签收", "sign_date": "2026-07-23", "customer": "王老师", "phone": "136****2345"},
    "O12354": {"order_id": "O12354", "product": "W5 Pro eSIM 手表", "amount": 899.0,
               "status": "已签收", "sign_date": "2026-07-11", "customer": "陈工", "phone": "158****6789"},
}

CUSTOMERS = {
    "张总": {"name": "张总", "level": "VIP", "orders": ["O12345", "O12347"], "total_spent": 798.0, "since": "2025-03"},
    "李经理": {"name": "李经理", "level": "VIP", "orders": ["O12346", "O12350"], "total_spent": 2798.0, "since": "2025-06"},
    "王老师": {"name": "王老师", "level": "金卡", "orders": ["O12348", "O12353"], "total_spent": 1298.0, "since": "2025-09"},
    "陈工": {"name": "陈工", "level": "普通", "orders": ["O12349", "O12354"], "total_spent": 1398.0, "since": "2026-01"},
    "赵女士": {"name": "赵女士", "level": "普通", "orders": ["O12351"], "total_spent": 299.0, "since": "2026-07"},
    "周同学": {"name": "周同学", "level": "金卡", "orders": ["O12352"], "total_spent": 399.0, "since": "2025-11"},
}


@mcp.tool
def order_query(order_id: str) -> dict:
    """按订单号查询订单详情（商品、金额、状态、签收日期）。"""
    return ORDERS.get(order_id, {"error": f"订单 {order_id} 不存在"})


@mcp.tool
def customer_profile(customer_name: str) -> dict:
    """按客户姓名查询客户档案（等级、历史订单）。"""
    return CUSTOMERS.get(customer_name, {"error": f"客户 {customer_name} 不存在"})


if __name__ == "__main__":
    mcp.run()  # stdio transport
