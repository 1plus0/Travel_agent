import json
from datetime import datetime, timezone
from typing import Any, Optional

def tool_return(
    ok: bool,
    data: Any = None,
    error: Optional[str] = None,
    source: str = "unknown"
) -> str:
    """
    统一工具返回协议（强烈推荐）：
    - ok: 是否成功
    - data: 成功数据
    - error: 错误信息
    - source: 数据来源
    - retrieved_at: UTC 时间
    """
    payload = {
        "ok": ok,
        "data": data,
        "error": error,
        "source": source,
        "retrieved_at": datetime.now(timezone.utc).isoformat()
    }
    return json.dumps(payload, ensure_ascii=False)
