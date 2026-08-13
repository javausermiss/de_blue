import sys
import json
from datetime import datetime
from pathlib import Path

# Windows 下 stdout 默认为 GBK，统一为 UTF-8
# 避免中文输出在终端中乱码
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# =========================
# 配置
# =========================

# 两个数据源价格允许的最大相对误差
# 例如 0.01 = 1%
PRICE_TOLERANCE = 0.01


# =========================
# 基础工具
# =========================

def load_json(file_path: str) -> dict:
    """读取 JSON 文件。"""

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(
            f"数据文件不存在: {file_path}"
        )

    with path.open(
        "r",
        encoding="utf-8"
    ) as f:

        return json.load(f)


def is_number(value):
    """判断是否为有效数字。"""

    return (
        value is not None
        and isinstance(value, (int, float))
    )


def relative_difference(value_a, value_b):
    """
    计算两个数的相对差异。

    返回：
        0.01 = 1%
    """

    if not is_number(value_a):
        return None

    if not is_number(value_b):
        return None

    if value_b == 0:
        return None

    return abs(value_a - value_b) / abs(value_b)


# =========================
# 检查：价格
# =========================

def check_price(data: dict):

    price = data.get("price")

    if not is_number(price):
        return False, "最新价格不存在或无效"

    if price <= 0:
        return False, "最新价格小于等于0"

    return True, None


# =========================
# 检查：行情时间
# =========================

def check_timestamp(data: dict):

    timestamp = data.get("market_timestamp")

    if not timestamp:
        return False, "行情时间不存在"

    try:

        datetime.strptime(
            timestamp,
            "%Y-%m-%d %H:%M:%S"
        )

        return True, None

    except ValueError:

        return False, (
            f"行情时间格式错误: {timestamp}"
        )


# =========================
# 检查：股票代码
# =========================

def check_symbol(data: dict, expected_symbol: str):

    symbol = str(data.get("symbol", ""))

    if symbol != expected_symbol:
        return False, (
            f"股票代码不一致: "
            f"expected={expected_symbol}, "
            f"actual={symbol}"
        )

    return True, None


# =========================
# 检查：数据源
# =========================

def check_sources(data: dict):

    sources = data.get("sources")

    if not isinstance(sources, dict):
        return False, "sources 不存在或格式错误"

    available = [
        key
        for key in ("eastmoney", "source_b", "source_c")
        if key in sources
    ]

    if not available:
        return False, "缺少行情数据源"

    return True, None


# =========================
# 检查：两个数据源价格
# =========================

def check_price_consistency(data: dict):

    sources = data.get("sources", {})

    available = [
        source
        for source in (
            sources.get("eastmoney"),
            sources.get("source_b"),
            sources.get("source_c")
        )
        if source
    ]

    if len(available) < 2:
        return False, "可用数据源不足两个，无法交叉验证"

    base_price = available[0].get("price")

    if not is_number(base_price):
        return False, "第一数据源价格不存在"

    for other in available[1:]:

        other_price = other.get("price")

        if not is_number(other_price):
            continue

        difference = relative_difference(
            base_price,
            other_price
        )

        if difference is None:
            continue

        if difference > PRICE_TOLERANCE:

            return False, (
                f"数据源价格差异过大: "
                f"{difference:.2%}"
            )

    return True, None


# =========================
# 检查：交易日期
# =========================

def check_trading_date(data: dict):

    trading_date = data.get("trading_date")

    if not trading_date:
        return False, "交易日期不存在"

    try:

        datetime.strptime(
            trading_date,
            "%Y-%m-%d"
        )

    except ValueError:

        return False, (
            f"交易日期格式错误: {trading_date}"
        )

    return True, None


# =========================
# 执行全部检查
# =========================

def validate(data: dict, expected_symbol: str):

    checks = {}
    errors = []
    warnings = []

    # 1. 价格
    passed, error = check_price(data)

    checks["price_exists"] = passed

    if error:
        errors.append(error)

    # 2. 行情时间
    passed, error = check_timestamp(data)

    checks["timestamp_valid"] = passed

    if error:
        errors.append(error)

    # 3. 股票代码
    passed, error = check_symbol(
        data,
        expected_symbol
    )

    checks["symbol_consistent"] = passed

    if error:
        errors.append(error)

    # 4. 数据源
    passed, error = check_sources(data)

    checks["sources_available"] = passed

    if error:
        errors.append(error)

    # 5. 交易日期
    passed, error = check_trading_date(data)

    checks["trading_date_valid"] = passed

    if error:
        errors.append(error)

    # 6. 数据源价格一致性（对全部可用源两两比较）
    passed, error = check_price_consistency(data)

    checks["price_consistent"] = passed

    if error:
        errors.append(error)

    # 东方财富失败时的降级提示
    if "eastmoney" not in data.get("sources", {}):

        warnings.append(
            "东方财富失败，主数据已回退备用源"
            "（估值与市值字段可能缺失）"
        )

    # =========================
    # 最终结果
    # =========================

    verified = all(checks.values())

    if verified:

        status = "VERIFIED"

    else:

        status = "FAILED"

    return {
        "symbol": expected_symbol,

        "verified": verified,

        "status": status,

        "checks": checks,

        "errors": errors,

        "warnings": warnings,

        "validated_at": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    }


# =========================
# 主程序
# =========================

def main():

    if len(sys.argv) != 3:

        print(
            "用法:"
        )

        print(
            "python validate_market_data.py "
            "<SYMBOL> <JSON_FILE>"
        )

        print()

        print(
            "例如:"
        )

        print(
            "python validate_market_data.py "
            "300115 data/market/300115.json"
        )

        sys.exit(1)

    symbol = sys.argv[1]

    json_file = sys.argv[2]

    try:

        data = load_json(json_file)

        result = validate(
            data,
            symbol
        )

        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2
            )
        )

        # verified=false 时返回错误码
        if not result["verified"]:

            sys.exit(2)

    except Exception as e:

        print(
            json.dumps(
                {
                    "symbol": symbol,
                    "verified": False,
                    "status": "ERROR",
                    "errors": [
                        str(e)
                    ]
                },
                ensure_ascii=False,
                indent=2
            )
        )

        sys.exit(1)


if __name__ == "__main__":
    main()