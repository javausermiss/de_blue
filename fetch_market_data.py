import sys
import json
import time
import requests
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Windows 下 stdout 默认为 GBK，统一为 UTF-8
# 避免中文错误信息在终端中乱码
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ============================================================
# 配置
# ============================================================

# 注意：/api/qt/stock/get 端点会直接重置连接
# （服务端按路径选择性断开，curl 与 requests 均复现），
# 已改用 ulist.np/get 列表行情接口，字段语义不同，见下方映射。
EASTMONEY_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,image/avif,image/webp,"
        "*/*;q=0.8"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://quote.eastmoney.com/"
}

OUTPUT_DIR = Path("data/market")

# 复用同一会话：先访问行情页面拿到 Cookie，
# 后续 API 请求携带完整会话上下文，更像真实浏览器。
SESSION = requests.Session()


def warm_up_session(symbol: str) -> None:
    """访问东财行情页面预热会话，让 Cookie 就位。

    预热失败不阻断主流程——它只是提高通过率，
    不是抓取的必要条件。
    """

    prefix = "sh" if symbol.startswith("6") else "sz"

    try:

        SESSION.get(
            f"https://quote.eastmoney.com/{prefix}{symbol}.html",
            headers=HEADERS,
            timeout=10
        )

    except Exception:
        pass


def fetch_with_retry(fetch_func, symbol, attempts=2, delay=2.0):
    """对不稳定的数据源做轻量重试。

    东方财富 push2 接口存在间歇性连接重置，
    两次尝试之间等待 delay 秒，第二次仍失败才放弃。
    """

    last_error = None

    for attempt in range(1, attempts + 1):

        try:

            return fetch_func(symbol)

        except Exception as e:

            last_error = e

            if attempt < attempts:
                time.sleep(delay)

    raise last_error


# ============================================================
# 股票代码
# ============================================================

def get_eastmoney_secid(symbol: str) -> str:

    symbol = symbol.strip()

    if symbol.startswith("6"):
        return f"1.{symbol}"

    if symbol.startswith(("0", "3")):
        return f"0.{symbol}"

    raise ValueError(
        f"暂不支持的A股代码: {symbol}"
    )


# ============================================================
# 东方财富
# ============================================================

def fetch_eastmoney(symbol: str) -> dict:

    secid = get_eastmoney_secid(symbol)

    # ulist.np/get 的字段编号与 stock/get 不同：
    #   f2=最新价 f3=涨跌幅 f4=涨跌额 f5=成交量 f6=成交额
    #   f8=换手率 f9=市盈率(动态) f12=代码 f14=名称
    #   f15=最高 f16=最低 f17=今开 f18=昨收
    #   f20=总市值 f21=流通市值 f23=市净率 f124=行情时间(Unix秒)
    # 除 f5/f6/f20/f21 外，其余数值字段均需 ÷100。
    params = {
        "secids": secid,
        "fields": (
            "f2,f3,f4,f5,f6,f8,f9,"
            "f12,f14,f15,f16,f17,f18,"
            "f20,f21,f23,f124"
        ),
        "ut": "fa5fd1943c7b386f172d6893dbbd1d0c"
    }

    response = SESSION.get(
        EASTMONEY_URL,
        params=params,
        headers=HEADERS,
        timeout=10
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("data"):
        raise RuntimeError(
            f"东方财富没有返回数据: {symbol}"
        )

    diff = result["data"].get("diff")

    if not diff:
        raise RuntimeError(
            f"东方财富行情列表为空: {symbol}"
        )

    quote = diff[0]

    def scaled(field):

        value = quote.get(field)

        if value is None or value == "-":
            return None

        return float(value) / 100

    def number(field):

        value = quote.get(field)

        if value is None or value == "-":
            return None

        return float(value)

    market_timestamp = None

    if quote.get("f124"):

        raw_time = quote["f124"]

        try:

            market_timestamp = datetime.fromtimestamp(
                float(raw_time),
                tz=timezone(timedelta(hours=8))
            ).strftime(
                "%Y-%m-%d %H:%M:%S"
            )

        except (ValueError, OSError):
            pass

    return {
        "symbol": str(quote.get("f12")),
        "name": quote.get("f14"),

        "price": scaled("f2"),
        "open": scaled("f17"),
        "high": scaled("f15"),
        "low": scaled("f16"),
        "pre_close": scaled("f18"),

        "volume": number("f5"),
        "amount": number("f6"),

        "market_cap": number("f20"),
        "float_market_cap": number("f21"),

        "pe": scaled("f9"),
        "pb": scaled("f23"),

        "turnover_rate": scaled("f8"),
        "change": scaled("f4"),
        "change_pct": scaled("f3"),

        "market_timestamp": market_timestamp,

        "source": "Eastmoney"
    }


# ============================================================
# 腾讯行情
# ============================================================

def get_tencent_symbol(symbol: str) -> str:

    symbol = symbol.strip()

    if symbol.startswith("6"):
        return f"sh{symbol}"

    if symbol.startswith(("0", "3")):
        return f"sz{symbol}"

    raise ValueError(
        f"暂不支持的A股代码: {symbol}"
    )


def fetch_tencent(symbol: str) -> dict:

    tencent_symbol = get_tencent_symbol(symbol)

    url = (
        "https://qt.gtimg.cn/q="
        + tencent_symbol
    )

    response = SESSION.get(
        url,
        headers=HEADERS,
        timeout=10
    )

    response.raise_for_status()

    text = response.text

    if "~" not in text:
        raise RuntimeError(
            f"腾讯行情没有返回有效数据: {symbol}"
        )

    # 腾讯返回类似：
    #
    # v_sz300115="51~长盈精密~300115~34.92~..."

    start = text.find('"')
    end = text.rfind('"')

    if start == -1 or end == -1:
        raise RuntimeError(
            "无法解析腾讯行情数据"
        )

    content = text[start + 1:end]

    fields = content.split("~")

    if len(fields) < 10:
        raise RuntimeError(
            f"腾讯行情字段数量异常: {len(fields)}"
        )

    name = fields[1]
    code = fields[2]

    price = float(fields[3])
    pre_close = float(fields[4])

    change = price - pre_close

    change_pct = (
        change / pre_close * 100
        if pre_close != 0
        else None
    )

    return {
        "symbol": code,
        "name": name,
        "price": price,
        "pre_close": pre_close,
        "change": change,
        "change_pct": change_pct,
        "source": "Tencent"
    }


# ============================================================
# 新浪行情（第三数据源）
# ============================================================

SINA_URL = "https://hq.sinajs.cn/list="

SINA_HEADERS = {
    "User-Agent": HEADERS["User-Agent"],
    "Referer": "https://finance.sina.com.cn"
}


def get_sina_symbol(symbol: str) -> str:

    symbol = symbol.strip()

    if symbol.startswith("6"):
        return f"sh{symbol}"

    if symbol.startswith(("0", "3")):
        return f"sz{symbol}"

    raise ValueError(
        f"暂不支持的A股代码: {symbol}"
    )


def fetch_sina(symbol: str) -> dict:

    sina_symbol = get_sina_symbol(symbol)

    response = SESSION.get(
        SINA_URL + sina_symbol,
        headers=SINA_HEADERS,
        timeout=10
    )

    response.raise_for_status()

    # 新浪返回 GBK 编码
    text = response.content.decode("gbk")

    # 返回类似：
    #
    # var hq_str_sz300115="长盈精密,28.000,28.180,27.800,...";

    start = text.find('"')
    end = text.rfind('"')

    if start == -1 or end == start + 1:
        raise RuntimeError(
            f"新浪行情没有返回有效数据: {symbol}"
        )

    # 新浪 A 股字段：
    #   0名称 1今开 2昨收 3现价 4最高 5最低
    #   8成交量(股) 9成交额(元) 30日期 31时间
    fields = text[start + 1:end].split(",")

    if len(fields) < 10:
        raise RuntimeError(
            f"新浪行情字段数量异常: {len(fields)}"
        )

    def to_float(value):

        try:
            return float(value)

        except (TypeError, ValueError):
            return None

    price = to_float(fields[3])
    pre_close = to_float(fields[2])

    market_timestamp = None

    if len(fields) >= 32:

        date_str = fields[30].strip()
        time_str = fields[31].strip()

        if date_str and time_str:
            market_timestamp = f"{date_str} {time_str}"

    return {
        "symbol": sina_symbol[2:],
        "name": fields[0],
        "price": price,
        "open": to_float(fields[1]),
        "high": to_float(fields[4]),
        "low": to_float(fields[5]),
        "pre_close": pre_close,
        "volume": to_float(fields[8]),
        "amount": to_float(fields[9]),
        "change": (
            round(price - pre_close, 4)
            if price is not None and pre_close
            else None
        ),
        "change_pct": (
            round((price - pre_close) / pre_close * 100, 4)
            if price is not None and pre_close
            else None
        ),
        "market_timestamp": market_timestamp,
        "source": "Sina"
    }


# ============================================================
# 数据一致性基础检查
# ============================================================

def basic_check(eastmoney, tencent, symbol):

    errors = []

    if eastmoney["symbol"] != symbol:
        errors.append(
            "东方财富股票代码不一致"
        )

    if tencent["symbol"] != symbol:
        errors.append(
            "腾讯股票代码不一致"
        )

    if (
        eastmoney.get("name")
        and tencent.get("name")
        and eastmoney["name"] != tencent["name"]
    ):
        errors.append(
            f"股票名称不一致: "
            f"{eastmoney['name']} / "
            f"{tencent['name']}"
        )

    return errors


# ============================================================
# 保存数据
# ============================================================

def get_output_path(symbol, date_str):
    """输出文件名带日期：{symbol}_{date}.json"""

    return OUTPUT_DIR / f"{symbol}_{date_str}.json"


def save_data(symbol, data, date_str):

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    file_path = get_output_path(symbol, date_str)

    with file_path.open(
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    return file_path


# ============================================================
# 主流程
# ============================================================

def main():

    valid_args = (
        2 <= len(sys.argv) <= 3
        and (
            len(sys.argv) == 2
            or sys.argv[2] == "--force"
        )
    )

    if not valid_args:

        print(
            "用法: "
            "python fetch_market_data.py 300115 [--force]"
        )

        sys.exit(1)

    symbol = sys.argv[1]

    force = (
        len(sys.argv) == 3
        and sys.argv[2] == "--force"
    )

    today = datetime.now().strftime("%Y-%m-%d")

    file_path = get_output_path(symbol, today)

    # --------------------------------------------------------
    # 当天缓存：同日已抓取过则直接复用，不再发起请求
    # --------------------------------------------------------

    if file_path.exists() and not force:

        try:

            cached = json.loads(
                file_path.read_text(encoding="utf-8")
            )

        except Exception:

            cached = None

        if cached:

            print(
                json.dumps(
                    {
                        "symbol": symbol,
                        "file": str(file_path),
                        "cached": True,
                        "price": cached.get("price"),
                        "trading_date": cached.get(
                            "trading_date"
                        ),
                        "primary_source": cached.get(
                            "primary_source"
                        )
                    },
                    ensure_ascii=False,
                    indent=2
                )
            )

            sys.exit(0)

    retrieved_at = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    # --------------------------------------------------------
    # 会话预热（携带 Cookie 再请求 API）
    # --------------------------------------------------------

    warm_up_session(symbol)

    result = {
        "symbol": symbol,
        "retrieved_at": retrieved_at,
        "sources": {},
        "fetch_status": {},
        "errors": []
    }

    # --------------------------------------------------------
    # 东方财富
    # --------------------------------------------------------

    try:

        eastmoney = fetch_with_retry(
            fetch_eastmoney,
            symbol
        )

        result["sources"]["eastmoney"] = eastmoney

        result["fetch_status"]["eastmoney"] = True

    except Exception as e:

        result["fetch_status"]["eastmoney"] = False

        result["errors"].append(
            f"东方财富: {str(e)}"
        )

        eastmoney = None

    # --------------------------------------------------------
    # 腾讯
    # --------------------------------------------------------

    try:

        tencent = fetch_tencent(symbol)

        result["sources"]["source_b"] = tencent

        result["fetch_status"]["source_b"] = True

    except Exception as e:

        result["fetch_status"]["source_b"] = False

        result["errors"].append(
            f"腾讯行情: {str(e)}"
        )

        tencent = None

    # --------------------------------------------------------
    # 新浪（第三数据源）
    # --------------------------------------------------------

    try:

        sina = fetch_sina(symbol)

        result["sources"]["source_c"] = sina

        result["fetch_status"]["source_c"] = True

    except Exception as e:

        result["fetch_status"]["source_c"] = False

        result["errors"].append(
            f"新浪行情: {str(e)}"
        )

        sina = None

    # --------------------------------------------------------
    # 统一主数据
    # --------------------------------------------------------

    # 主数据按字段完整度回退：
    # 东方财富（含估值与市值）→ 新浪（完整 OHLC）
    # → 腾讯（仅基础价格字段）
    main_source = eastmoney or sina or tencent

    if main_source:

        result["primary_source"] = main_source.get(
            "source"
        )

        result.update({
            "name": main_source.get("name"),
            "price": main_source.get("price"),
            "open": main_source.get("open"),
            "high": main_source.get("high"),
            "low": main_source.get("low"),
            "pre_close": main_source.get("pre_close"),
            "volume": main_source.get("volume"),
            "amount": main_source.get("amount"),
            "market_cap": main_source.get("market_cap"),
            "float_market_cap": main_source.get(
                "float_market_cap"
            ),
            "pe": main_source.get("pe"),
            "pb": main_source.get("pb"),
            "turnover_rate": main_source.get(
                "turnover_rate"
            ),
            "change": main_source.get("change"),
            "change_pct": main_source.get(
                "change_pct"
            ),
            "market_timestamp": main_source.get(
                "market_timestamp"
            )
        })

    # --------------------------------------------------------
    # 基础一致性检查
    # --------------------------------------------------------

    available = [
        source
        for source in (eastmoney, tencent, sina)
        if source
    ]

    for other in available[1:]:

        consistency_errors = basic_check(
            available[0],
            other,
            symbol
        )

        result["errors"].extend(
            consistency_errors
        )

    # --------------------------------------------------------
    # 交易日期
    # --------------------------------------------------------

    market_timestamp = result.get("market_timestamp")

    if not market_timestamp and sina:
        market_timestamp = sina.get("market_timestamp")

    if market_timestamp:

        result["trading_date"] = market_timestamp[:10]

    else:

        result["trading_date"] = None

    # --------------------------------------------------------
    # 保存
    # --------------------------------------------------------

    file_path = save_data(
        symbol,
        result,
        today
    )

    # --------------------------------------------------------
    # 输出
    # --------------------------------------------------------

    print(
        json.dumps(
            {
                "symbol": symbol,
                "file": str(file_path),
                "cached": False,
                "eastmoney": (
                    "OK"
                    if result["fetch_status"]
                    .get("eastmoney")
                    else "FAILED"
                ),
                "tencent": (
                    "OK"
                    if result["fetch_status"]
                    .get("source_b")
                    else "FAILED"
                ),
                "sina": (
                    "OK"
                    if result["fetch_status"]
                    .get("source_c")
                    else "FAILED"
                ),
                "errors": result["errors"]
            },
            ensure_ascii=False,
            indent=2
        )
    )

    # 主数据缺失（三个源全部失败）才返回错误码；
    # 单源失败体现在 errors 与 fetch_status 中，
    # 由备用源回退保障数据可用
    if not result.get("price"):

        sys.exit(2)


if __name__ == "__main__":
    main()
