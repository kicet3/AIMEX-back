"""
MCP Math Server - FastMCP 사용
"""

import logging
import re
from typing import Dict, Any
from mcp.server.fastmcp import FastMCP

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastMCP 서버 생성
mcp = FastMCP("Math")


def _extract_numbers_from_params(params: Dict[str, Any], message: str = "") -> tuple:
    """매개변수에서 숫자를 추출합니다."""
    a_value = None
    b_value = None

    # VLLM이 추출한 매개변수 처리
    if "numbers" in params and "value" in params:
        try:
            a_value = float(params["numbers"])
            b_value = float(params["value"])
        except (ValueError, TypeError):
            pass

    # 직접 숫자 매개변수 처리
    elif "a" in params and "b" in params:
        try:
            a_value = float(params["a"])
            b_value = float(params["b"])
        except (ValueError, TypeError):
            pass

    # 메시지에서 숫자 추출
    if a_value is None or b_value is None:
        numbers = re.findall(r"\d+", message)
        if len(numbers) >= 2:
            try:
                a_value = float(numbers[0])
                b_value = float(numbers[1])
            except (ValueError, TypeError):
                pass

    return a_value, b_value


@mcp.tool()
async def add(a: float = None, b: float = None) -> str:
    """두 숫자를 더합니다."""
    if a is None:
        a = 0
    if b is None:
        b = 0
    result = a + b
    return f"{a} + {b} = {result}"


@mcp.tool()
async def subtract(a: float = None, b: float = None) -> str:
    """두 숫자를 뺍니다."""
    if a is None:
        a = 0
    if b is None:
        b = 0
    result = a - b
    return f"{a} - {b} = {result}"


@mcp.tool()
async def multiply(a: float = None, b: float = None) -> str:
    """두 숫자를 곱합니다."""
    if a is None:
        a = 0
    if b is None:
        b = 0
    result = a * b
    return f"{a} * {b} = {result}"


@mcp.tool()
async def divide(a: float = None, b: float = None) -> str:
    """두 숫자를 나눕니다."""
    if a is None:
        a = 0
    if b is None:
        b = 1
    if b == 0:
        return "0으로 나눌 수 없습니다."
    result = a / b
    return f"{a} / {b} = {result}"


@mcp.tool()
async def power(base: float = None, exponent: float = None) -> str:
    """숫자의 거듭제곱을 계산합니다."""
    if base is None:
        base = 1
    if exponent is None:
        exponent = 1
    result = base**exponent
    return f"{base}^{exponent} = {result}"


@mcp.tool()
async def sqrt(number: float = None) -> str:
    """숫자의 제곱근을 계산합니다."""
    if number is None:
        number = 0
    if number < 0:
        return "음수의 제곱근은 계산할 수 없습니다."
    result = number**0.5
    return f"√{number} = {result}"


@mcp.tool()
async def factorial(n: int = None) -> str:
    """숫자의 팩토리얼을 계산합니다."""
    if n is None:
        n = 0
    if n < 0:
        return "음수의 팩토리얼은 정의되지 않습니다."
    if n == 0 or n == 1:
        return "1"
    result = 1
    for i in range(2, n + 1):
        result *= i
    return f"{n}! = {result}"


@mcp.tool()
async def gcd(a: int = None, b: int = None) -> str:
    """두 숫자의 최대공약수를 계산합니다."""
    if a is None:
        a = 0
    if b is None:
        b = 0
    orig_a, orig_b = a, b
    while b:
        a, b = b, a % b
    result = abs(a)
    return f"gcd({orig_a}, {orig_b}) = {result}"


@mcp.tool()
async def lcm(a: int = None, b: int = None) -> str:
    """두 숫자의 최소공배수를 계산합니다."""
    if a is None:
        a = 0
    if b is None:
        b = 0
    if a == 0 or b == 0:
        return "0"

    def _gcd(x: int, y: int) -> int:
        while y:
            x, y = y, x % y
        return x

    gcd_val = _gcd(a, b)
    result = abs(a * b) // gcd_val
    return f"lcm({a}, {b}) = {result}"


@mcp.tool()
async def solve_quadratic(a: float = None, b: float = None, c: float = None) -> str:
    """이차방정식 ax² + bx + c = 0을 풉니다."""
    if a is None:
        a = 1
    if b is None:
        b = 0
    if c is None:
        c = 0
    discriminant = b**2 - 4 * a * c
    if discriminant > 0:
        x1 = (-b + discriminant**0.5) / (2 * a)
        x2 = (-b - discriminant**0.5) / (2 * a)
        return f"{a}x² + {b}x + {c} = 0의 해: x = {x1:.4f}, x = {x2:.4f}"
    elif discriminant == 0:
        x = -b / (2 * a)
        return f"{a}x² + {b}x + {c} = 0의 해: x = {x:.4f} (중근)"
    else:
        real_part = -b / (2 * a)
        imag_part = abs(discriminant) ** 0.5 / (2 * a)
        return f"{a}x² + {b}x + {c} = 0의 해: x = {real_part:.4f} ± {imag_part:.4f}i (허근)"


if __name__ == "__main__":
    import os
    import uvicorn

    # 환경변수 설정
    port = int(os.environ.get("MCP_PORT", 8001))
    host = os.environ.get("MCP_HOST", "127.0.0.1")  # IPv4만 사용

    print(f"Math Server를 포트 {port}에서 시작합니다...")
    print(f"MCP_PORT: {port}")
    print(f"MCP_HOST: {host}")

    # FastMCP 서버를 uvicorn으로 실행 (IPv4만 사용)
    uvicorn.run(mcp.streamable_http_app, host=host, port=port)
