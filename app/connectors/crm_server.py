"""Connector 层：CRM 连接器（FastMCP stdio server，mock 数据）。"""
from fastmcp import FastMCP

mcp = FastMCP("crm")

ORDERS = {
    "O12345": {"order_id": "O12345", "product": "X1 智能音箱", "amount": 399.0,
               "status": "已签收", "sign_date": "2026-07-21", "customer": "张总"},
    "O12346": {"order_id": "O12346", "product": "S2 智能台灯", "amount": 199.0,
               "status": "已签收", "sign_date": "2026-07-14", "customer": "李经理"},
    "O12347": {"order_id": "O12347", "product": "X1 智能音箱", "amount": 399.0,
               "status": "运输中", "sign_date": None, "customer": "张总"},
}

CUSTOMERS = {
    "张总": {"name": "张总", "level": "VIP", "orders": ["O12345", "O12347"]},
    "李经理": {"name": "李经理", "level": "普通", "orders": ["O12346"]},
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
