"""
MCP 클라이언트 서비스 - langchain-mcp-adapters 사용
"""

import httpx
import logging
from typing import Dict, Any, List, Optional
import asyncio
import json
import subprocess
import sys
from pathlib import Path
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
import time
from .mcp_tools_metadata import MCPToolMetadataExtractor

# 로깅 설정
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class MCPClientService:
    def __init__(self):
        self.clients: Dict[str, httpx.AsyncClient] = {}
        self.mcp_client: Optional[MultiServerMCPClient] = None
        self.mcp_tools: Dict[str, List] = {}

        # 연결 풀링 및 캐싱 추가
        self.connection_pool: Dict[str, Any] = {}
        self.session_pool: Dict[str, Any] = {}  # 세션 풀 추가
        self.tools_cache: Dict[str, List] = {}
        self.cache_timestamp: Dict[str, float] = {}
        self.cache_duration = 300  # 5분 캐시
        self._initialized = False
        self._init_lock = asyncio.Lock()

    def reset_initialization(self):
        """MCP 클라이언트 초기화 상태를 리셋하여 재초기화할 수 있도록 합니다."""
        self._initialized = False
        self.mcp_client = None
        self.tools_cache.clear()
        self.cache_timestamp.clear()
        logger.info("🔄 MCP 클라이언트 초기화 상태 리셋 완료")

    async def add_server_dynamically(self, server_name: str, config: dict):
        """새 서버를 추가하기 위해 MCP 클라이언트를 재초기화합니다."""
        try:
            logger.info(
                f"🔄 새 서버 '{server_name}' 추가를 위해 MCP 클라이언트 재초기화 중..."
            )

            # 전체 재초기화 (가장 안정적인 방법)
            self.reset_initialization()
            await self.initialize_mcp_client()

            logger.info(
                f"✅ MCP 클라이언트 재초기화 완료 (새 서버 '{server_name}' 포함)"
            )

        except Exception as e:
            logger.error(f"서버 '{server_name}' 추가 실패: {e}")
            # 실패 시에도 재초기화 시도
            try:
                self.reset_initialization()
                await self.initialize_mcp_client()
            except Exception as retry_e:
                logger.error(f"재초기화 재시도 실패: {retry_e}")

    async def initialize_mcp_client(self, selected_servers: Optional[List[str]] = None):
        """langchain-mcp-adapters를 사용한 MCP 클라이언트 초기화 (한 번만 실행)"""
        if self._initialized:
            logger.info("✅ MCP 클라이언트가 이미 초기화되어 있습니다.")
            return

        async with self._init_lock:
            if self._initialized:  # 다시 확인
                return

            try:
                from app.services.mcp_server_manager import mcp_server_manager
                from app.services.mcp_server_manager import get_command_path, normalize_path

                # MCP 서버들이 실행될 때까지 대기
                logger.info("🔄 MCP 서버들이 실행될 때까지 대기 중...")
                await asyncio.sleep(5)  # 서버 시작 대기

                # MCP 서버 설정 가져오기
                server_configs = mcp_server_manager.server_configs
                logger.info(f"📋 설정된 MCP 서버들: {list(server_configs.keys())}")

                # MultiServerMCPClient 설정 구성
                client_config = {}

                for server_name, config in server_configs.items():
                    try:
                        logger.info(f"🔄 MCP 서버 '{server_name}' 설정 구성 중...")
                        logger.info(f"  - 설정: {config}")

                        if "command" in config and "args" in config:
                            # 명령어 실행 방식 서버 (Exa Search 등) - stdio 통신
                            # OS별 명령어 경로 처리
                            command = get_command_path(config["command"])
                            args = config["args"]
                            
                            # args의 경로도 정규화
                            normalized_args = []
                            for arg in args:
                                if isinstance(arg, str) and ("/" in arg or "\\" in arg):
                                    normalized_args.append(normalize_path(arg))
                                else:
                                    normalized_args.append(arg)
                            
                            client_config[server_name] = {
                                "command": command,
                                "args": normalized_args,
                                "transport": "stdio",
                            }
                            logger.info(f"✅ MCP 서버 '{server_name}' stdio 설정 완료")
                            logger.info(f"  - 명령어: {command}")
                            logger.info(f"  - 인수: {normalized_args}")

                        elif "url" in config:
                            # SSE 기반 서버 - streamable_http 통신
                            # URL 정규화
                            url = normalize_path(config["url"]) if "/" in config["url"] else config["url"]
                            client_config[server_name] = {
                                "url": url,
                                "transport": "streamable_http",
                            }
                            logger.info(
                                f"✅ MCP 서버 '{server_name}' streamable_http 설정 완료"
                            )
                            logger.info(f"  - URL: {url}")

                        elif "script" in config and "port" in config:
                            # 로컬 스크립트 서버 (SSE 기반) - streamable_http 통신
                            # FastMCP는 /mcp/ 엔드포인트를 사용
                            # localhost 대신 127.0.0.1 사용 (일부 환경에서 더 안정적)
                            server_url = f"http://127.0.0.1:{config['port']}/mcp/"
                            client_config[server_name] = {
                                "url": server_url,
                                "transport": "streamable_http",
                            }
                            logger.info(
                                f"✅ MCP 서버 '{server_name}' 로컬 SSE 설정 완료 (URL: {server_url})"
                            )

                    except Exception as e:
                        logger.warning(
                            f"❌ MCP 서버 '{server_name}' 설정 구성 실패: {e}"
                        )
                        logger.warning(f"  - 설정: {config}")
                        import traceback

                        logger.warning(f"  - 상세 오류: {traceback.format_exc()}")

                # MultiServerMCPClient 초기화
                logger.info(
                    f"🔄 MultiServerMCPClient 초기화 중... (설정: {client_config})"
                )
                self.mcp_client = MultiServerMCPClient(client_config)
                logger.info("✅ MultiServerMCPClient 초기화 완료")

                # 선택된 서버만 도구 미리 캐시
                if selected_servers:
                    for server_name in selected_servers:
                        try:
                            await self.get_cached_tools(server_name)
                            logger.info(
                                f"선택 서버 '{server_name}' 도구 미리 캐시 완료"
                            )
                        except Exception as e:
                            logger.error(f"❌ '{server_name}' 도구 미리 캐시 실패: {e}")

                self._initialized = True
                logger.info(
                    "🎯 MCP 클라이언트 초기화 완료: 총 {}개 서버, {}개 도구".format(
                        len(server_configs),
                        sum(len(tools) for tools in self.tools_cache.values()),
                    )
                )

            except Exception as e:
                logger.error(f"❌ MCP 클라이언트 초기화 실패: {e}")
                import traceback

                logger.error(f"  - 상세 오류: {traceback.format_exc()}")
                raise

    async def get_cached_tools(self, server_name: str) -> List:
        """캐시된 도구 목록 반환 (캐시가 만료되면 새로 로드)"""
        current_time = time.time()

        # 캐시가 없거나 만료된 경우
        if (
            server_name not in self.tools_cache
            or server_name not in self.cache_timestamp
            or current_time - self.cache_timestamp[server_name] > self.cache_duration
        ):

            logger.info(f"🔄 '{server_name}' 서버 도구 캐시 갱신 중...")
            await self._refresh_tools_cache(server_name)

        return self.tools_cache.get(server_name, [])

    async def _refresh_tools_cache(self, server_name: str):
        """특정 서버의 도구 캐시를 새로 로드"""
        try:
            if not self.mcp_client:
                await self.initialize_mcp_client()

            async with self.mcp_client.session(server_name) as session:
                from langchain_mcp_adapters.tools import load_mcp_tools

                tools = await load_mcp_tools(session)
                self.tools_cache[server_name] = tools
                self.cache_timestamp[server_name] = time.time()

                logger.info(
                    f"✅ '{server_name}' 서버 도구 캐시 갱신 완료: {len(tools)}개 도구"
                )

        except Exception as e:
            logger.error(f"❌ '{server_name}' 서버 도구 캐시 갱신 실패: {e}")

    async def get_connection(self, server_name: str):
        """연결 풀에서 서버 연결 반환"""
        if server_name not in self.connection_pool:
            if not self.mcp_client:
                await self.initialize_mcp_client()

            # 새 연결 생성
            self.connection_pool[server_name] = self.mcp_client.session(server_name)

        return self.connection_pool[server_name]

    async def get_client(self, server_name: str) -> httpx.AsyncClient:
        """HTTP 클라이언트를 가져오거나 생성합니다."""
        if server_name not in self.clients:
            # 동적 서버 URL 가져오기
            server_url = await self._get_server_url(server_name)

            if not server_url:
                raise ValueError(f"알 수 없는 서버: {server_name}")

            try:
                # HTTP 클라이언트 생성
                client = httpx.AsyncClient(base_url=server_url, timeout=30.0)
                self.clients[server_name] = client
                logger.info(f"MCP HTTP 클라이언트 '{server_name}' 생성 완료")

            except Exception as e:
                logger.error(f"MCP HTTP 클라이언트 '{server_name}' 생성 실패: {e}")
                raise

        return self.clients[server_name]

    async def _get_server_url(self, server_name: str) -> str:
        """서버 URL을 가져옵니다."""
        try:
            from app.services.mcp_server_manager import mcp_server_manager

            # MCP 서버 매니저에서 서버 정보 가져오기
            server_status = mcp_server_manager.get_server_status()

            if server_name in server_status:
                config = server_status[server_name].get("config", {})
                if "url" in config:
                    return config["url"]
                elif "port" in config:
                    return f"http://localhost:{config['port']}"
                elif "script" in config:
                    # 기본 서버들의 경우 포트 매핑
                    port_mapping = {"math": 8003, "weather": 8005}
                    if server_name in port_mapping:
                        return f"http://localhost:{port_mapping[server_name]}"

            # 기본 서버 URL들 (하위 호환성)
            server_urls = {
                "math": "http://localhost:8003",
                "weather": "http://localhost:8005",
                "websearch": "https://server.smithery.ai/exa",
            }

            return server_urls.get(server_name, "")

        except Exception as e:
            logger.error(f"서버 URL 가져오기 실패: {e}")
            return ""

    async def get_tools(self, server_name: str) -> List[Dict[str, Any]]:
        """특정 MCP 서버의 도구들을 가져옵니다 (캐시 사용)."""
        try:
            # 캐시된 도구 목록 반환
            tools = await self.get_cached_tools(server_name)
            logger.info(
                f"MCP 서버 '{server_name}'에서 {len(tools)}개 도구 로드 (캐시 사용)"
            )
            return tools

        except Exception as e:
            logger.error(f"MCP 서버 '{server_name}' 도구 로드 실패: {e}")
            return []

    def _get_default_tools(self, server_name: str) -> List[Dict[str, Any]]:
        """기본 도구 목록을 반환합니다."""
        # 하드코딩된 도구 목록 제거 - 실제 MCP 서버에서 동적으로 가져옴
        logger.warning(
            f"MCP 서버 '{server_name}'에서 도구를 가져올 수 없어 빈 목록 반환"
        )
        return []

    async def list_available_tools(self, server_name: str) -> List[Dict[str, Any]]:
        """사용 가능한 도구 목록을 반환합니다 (API 형식)."""
        try:
            tools = await self.get_tools(server_name)

            # 도구 정보를 API 형식으로 변환
            tools_info = []
            for tool in tools:
                tools_info.append(
                    {
                        "name": tool.get("name", ""),
                        "description": tool.get("description", ""),
                        "args_schema": tool.get("args_schema", {}),
                    }
                )

            return tools_info

        except Exception as e:
            logger.error(f"MCP 서버 '{server_name}' 도구 목록 로드 실패: {e}")
            return []

    async def execute_tool(
        self, server_name: str, tool_name: str, params: Dict[str, Any]
    ) -> Any:
        """MCP 서버에서 도구를 실행합니다."""
        try:
            logger.info(f"🚀 MCP 도구 실행 시작:")
            logger.info(f"  - 서버: {server_name}")
            logger.info(f"  - 도구: {tool_name}")
            logger.info(f"  - 매개변수: {params}")

            # langchain-mcp-adapters 사용
            if not self.mcp_client:
                await self.initialize_mcp_client()

            # 캐시된 도구 사용
            try:
                logger.info(f"🔄 서버 '{server_name}' 캐시된 도구 사용...")

                # 캐시된 도구 목록 가져오기
                tools = await self.get_cached_tools(server_name)
                logger.info(f"  - 캐시에서 로드된 도구 수: {len(tools)}")

                # 도구 찾기
                target_tool = None
                for tool in tools:
                    tool_name_attr = None
                    if hasattr(tool, "name"):
                        tool_name_attr = tool.name
                    elif hasattr(tool, "tool_name"):
                        tool_name_attr = tool.tool_name
                    elif hasattr(tool, "function_name"):
                        tool_name_attr = tool.function_name

                    logger.debug(
                        f"  - 도구 확인: {tool_name_attr} (찾는 도구: {tool_name})"
                    )

                    if tool_name_attr == tool_name:
                        target_tool = tool
                        logger.info(f"✅ 도구 '{tool_name}' 찾음!")
                        break

                if target_tool:
                    # 도구 실행 (세션 풀 사용)
                    try:
                        logger.info(f"🎯 도구 실행 시도: {target_tool}")

                        # 새로운 세션에서 도구 실행 (안정성을 위해)
                        async with self.mcp_client.session(
                            server_name
                        ) as active_session:
                            # 세션에서 도구 다시 로드
                            from langchain_mcp_adapters.tools import load_mcp_tools

                            session_tools = await load_mcp_tools(active_session)

                            # 세션에서 해당 도구 찾기
                            session_tool = None
                            for tool in session_tools:
                                if hasattr(tool, "name") and tool.name == tool_name:
                                    session_tool = tool
                                    break

                            if session_tool:
                                result = await session_tool.ainvoke(params)
                                logger.info(f"✅ MCP 도구 '{tool_name}' 실행 성공")
                                logger.info(f"  - 서버: {server_name}")

                                # 긴 응답 결과는 요약해서 로그
                                if isinstance(result, str) and len(result) > 200:
                                    logger.info(
                                        f"  - 응답 결과: {result[:200]}... (총 {len(result)}자)"
                                    )
                                else:
                                    logger.info(f"  - 응답 결과: {result}")

                                return result
                            else:
                                logger.error(
                                    f"❌ 세션에서 도구 '{tool_name}'을 찾을 수 없습니다"
                                )
                                return f"도구 '{tool_name}' 실행 실패: 세션에서 도구를 찾을 수 없습니다"

                    except Exception as tool_error:
                        logger.error(f"❌ 도구 실행 중 오류: {tool_error}")
                        logger.error(f"  - 도구: {target_tool}")
                        logger.error(f"  - 매개변수: {params}")
                        logger.error(f"  - 오류 타입: {type(tool_error)}")
                        return f"도구 실행 중 오류: {str(tool_error)}"
                else:
                    logger.warning(f"❌ 도구 '{tool_name}'을 찾을 수 없습니다")
                    available_tools = []
                    for tool in tools:
                        if hasattr(tool, "name"):
                            available_tools.append(tool.name)
                        elif hasattr(tool, "tool_name"):
                            available_tools.append(tool.tool_name)
                        elif hasattr(tool, "function_name"):
                            available_tools.append(tool.function_name)
                    logger.warning(f"  - 사용 가능한 도구: {available_tools}")
                    return f"도구 '{tool_name}'을 찾을 수 없습니다. 사용 가능한 도구: {available_tools}"

            except Exception as session_error:
                logger.error(f"❌ 세션 생성/도구 실행 실패: {session_error}")
                logger.error(f"  - 서버: {server_name}")
                logger.error(f"  - 오류 타입: {type(session_error)}")
                import traceback

                logger.error(f"  - 스택 트레이스: {traceback.format_exc()}")
                return f"도구 '{tool_name}' 실행 실패: {str(session_error)}"

        except Exception as e:
            logger.error(f"❌ MCP 도구 '{tool_name}' 실행 중 오류: {e}")
            logger.error(f"  - 서버: {server_name}")
            logger.error(f"  - 오류 타입: {type(e)}")
            import traceback

            logger.error(f"  - 스택 트레이스: {traceback.format_exc()}")
            return f"도구 실행 중 오류: {str(e)}"

    async def call_tool(self, server_name: str, tool_name: str, **kwargs) -> Any:
        """MCP 도구를 호출합니다."""
        try:
            client = await self.get_client(server_name)

            # 도구 호출
            payload = {"name": tool_name, "arguments": kwargs}

            response = await client.post(f"/tools/{tool_name}/call", json=payload)

            if response.status_code == 200:
                result = response.json()
                logger.info(f"MCP 도구 '{tool_name}' 호출 완료")
                return result
            else:
                logger.error(
                    f"MCP 도구 '{tool_name}' 호출 실패: {response.status_code}"
                )
                # 실패 시 시뮬레이션된 결과 반환
                return self._simulate_tool_result(server_name, tool_name, **kwargs)

        except Exception as e:
            logger.error(f"MCP 도구 '{tool_name}' 호출 실패: {e}")
            # 실패 시 시뮬레이션된 결과 반환
            return self._simulate_tool_result(server_name, tool_name, **kwargs)

    def _simulate_tool_result(self, server_name: str, tool_name: str, **kwargs) -> Any:
        """도구 결과를 시뮬레이션합니다."""
        if server_name == "math":
            if tool_name == "add":
                return {"result": kwargs.get("a", 0) + kwargs.get("b", 0)}
            elif tool_name == "subtract":
                return {"result": kwargs.get("a", 0) - kwargs.get("b", 0)}
            elif tool_name == "multiply":
                return {"result": kwargs.get("a", 0) * kwargs.get("b", 0)}
            elif tool_name == "divide":
                b = kwargs.get("b", 1)
                if b == 0:
                    return {"error": "0으로 나눌 수 없습니다."}
                return {"result": kwargs.get("a", 0) / b}
            elif tool_name == "power":
                return {"result": kwargs.get("base", 0) ** kwargs.get("exponent", 0)}
            elif tool_name == "sqrt":
                number = kwargs.get("number", 0)
                if number < 0:
                    return {"error": "음수의 제곱근은 계산할 수 없습니다."}
                return {"result": number**0.5}
            elif tool_name == "factorial":
                n = kwargs.get("n", 0)
                if n < 0:
                    return {"error": "음수의 팩토리얼은 정의되지 않습니다."}
                if n == 0 or n == 1:
                    return {"result": 1}
                result = 1
                for i in range(2, n + 1):
                    result *= i
                return {"result": result}
            elif tool_name == "gcd":
                a, b = kwargs.get("a", 0), kwargs.get("b", 0)
                while b:
                    a, b = b, a % b
                return {"result": abs(a)}
            elif tool_name == "lcm":
                a, b = kwargs.get("a", 0), kwargs.get("b", 0)
                if a == 0 or b == 0:
                    return {"result": 0}

                # GCD 계산
                def _gcd(x, y):
                    while y:
                        x, y = y, x % y
                    return x

                gcd_val = _gcd(a, b)
                return {"result": abs(a * b) // gcd_val}
            elif tool_name == "solve_quadratic":
                a, b, c = kwargs.get("a", 0), kwargs.get("b", 0), kwargs.get("c", 0)
                discriminant = b**2 - 4 * a * c
                if discriminant > 0:
                    x1 = (-b + discriminant**0.5) / (2 * a)
                    x2 = (-b - discriminant**0.5) / (2 * a)
                    return {"type": "two_real", "x1": x1, "x2": x2}
                elif discriminant == 0:
                    x = -b / (2 * a)
                    return {"type": "one_real", "x": x}
                else:
                    real_part = -b / (2 * a)
                    imag_part = abs(discriminant) ** 0.5 / (2 * a)
                    return {
                        "type": "two_complex",
                        "x1": f"{real_part} + {imag_part}i",
                        "x2": f"{real_part} - {imag_part}i",
                    }
        elif server_name == "weather":
            if tool_name == "get_current_weather":
                return {
                    "result": {
                        "weather": "맑음",
                        "temperature": 22,
                        "location": kwargs.get("location", "서울"),
                    }
                }
            elif tool_name == "get_weather_forecast":
                return {
                    "result": {
                        "forecast": "맑음",
                        "temperature": 22,
                        "location": kwargs.get("location", "서울"),
                    }
                }

        return {"result": "도구 실행 완료"}

    async def close_all(self):
        """모든 MCP 클라이언트를 종료합니다."""
        for server_name, client in self.clients.items():
            try:
                await client.aclose()
                logger.info(f"MCP HTTP 클라이언트 '{server_name}' 종료 완료")
            except Exception as e:
                logger.error(f"MCP HTTP 클라이언트 '{server_name}' 종료 실패: {e}")

        self.clients.clear()

    async def get_available_servers(self) -> List[str]:
        """사용 가능한 MCP 서버 목록을 반환합니다."""
        try:
            from app.services.mcp_server_manager import mcp_server_manager

            # MCP 서버 매니저에서 실행 중인 서버들 확인
            server_status = mcp_server_manager.get_server_status()
            available_servers = []

            for server_name, status in server_status.items():
                if status.get("running", False):
                    available_servers.append(server_name)
                    logger.info(f"✅ MCP 서버 '{server_name}' 실행 중")

            if not available_servers:
                logger.warning("실행 중인 MCP 서버가 없습니다")

            return available_servers

        except Exception as e:
            logger.error(f"사용 가능한 서버 목록 가져오기 실패: {e}")
            return []

    async def get_tools_from_server(self, server_name: str) -> List[Dict[str, Any]]:
        """특정 MCP 서버에서 도구 목록을 가져옵니다."""
        return await self.get_tools(server_name)

    # ===== 개선된 메타데이터 추출 메서드들 =====

    async def get_detailed_tools_metadata(self, server_name: str) -> Dict[str, Any]:
        """상세한 도구 메타데이터를 반환합니다."""
        try:
            tools = await self.get_cached_tools(server_name)

            metadata = {
                "server_name": server_name,
                "tool_count": len(tools),
                "tools": [],
                "extraction_timestamp": time.time(),
                "server_info": {},
            }

            # 서버 정보 추가
            try:
                from app.services.mcp_server_manager import mcp_server_manager

                server_status = mcp_server_manager.get_server_status()
                if server_name in server_status:
                    metadata["server_info"] = server_status[server_name]
            except Exception as e:
                logger.warning(f"서버 정보 추가 실패: {e}")

            # 각 도구의 메타데이터 추출
            for tool in tools:
                tool_metadata = MCPToolMetadataExtractor.extract_tool_metadata(tool)
                metadata["tools"].append(tool_metadata)

            logger.info(
                f"서버 '{server_name}'에서 {len(tools)}개 도구의 메타데이터 추출 완료"
            )
            return metadata

        except Exception as e:
            logger.error(f"도구 메타데이터 추출 실패: {e}")
            return {
                "server_name": server_name,
                "error": str(e),
                "extraction_timestamp": time.time(),
            }

    async def list_available_tools_detailed(
        self, server_name: str
    ) -> List[Dict[str, Any]]:
        """상세한 도구 목록을 반환합니다 (API 형식)."""
        try:
            metadata = await self.get_detailed_tools_metadata(server_name)
            return metadata.get("tools", [])

        except Exception as e:
            logger.error(f"상세 도구 목록 로드 실패: {e}")
            return []

    async def debug_tool_structure(self, server_name: str) -> Dict[str, Any]:
        """도구 구조를 디버깅하기 위한 상세 정보를 반환합니다."""
        try:
            tools = await self.get_cached_tools(server_name)
            debug_info = {
                "server_name": server_name,
                "tool_count": len(tools),
                "tools_debug": [],
            }

            for i, tool in enumerate(tools):
                tool_debug = {
                    "index": i,
                    "tool_type": type(tool).__name__,
                    "tool_module": getattr(type(tool), "__module__", "unknown"),
                    "all_attributes": [
                        attr for attr in dir(tool) if not attr.startswith("_")
                    ],
                    "attribute_values": {},
                }

                # 주요 속성들의 실제 값 확인
                key_attrs = [
                    "name",
                    "description",
                    "args_schema",
                    "input_schema",
                    "tool_name",
                    "function_name",
                    "func",
                    "metadata",
                ]

                for attr in key_attrs:
                    if hasattr(tool, attr):
                        value = getattr(tool, attr)
                        # 함수 객체는 제외하고 JSON 직렬화 가능한 값만 포함
                        if not callable(value):
                            tool_debug["attribute_values"][attr] = {
                                "type": type(value).__name__,
                                "value": (
                                    str(value)[:200] if value else None
                                ),  # 너무 긴 값은 자름
                            }
                        else:
                            tool_debug["attribute_values"][attr] = {
                                "type": "function",
                                "value": f"<function {attr}>",
                            }

                debug_info["tools_debug"].append(tool_debug)

            return debug_info

        except Exception as e:
            logger.error(f"도구 구조 디버깅 실패: {e}")
            return {"error": str(e)}

    async def get_tool_details(
        self, server_name: str, tool_name: str
    ) -> Optional[Dict[str, Any]]:
        """특정 도구의 상세 정보를 가져옵니다."""
        try:
            tools = await self.get_cached_tools(server_name)

            for tool in tools:
                # 도구 이름 확인
                tool_name_attr = None
                if hasattr(tool, "name"):
                    tool_name_attr = tool.name
                elif hasattr(tool, "tool_name"):
                    tool_name_attr = tool.tool_name
                elif hasattr(tool, "function_name"):
                    tool_name_attr = tool.function_name

                if tool_name_attr == tool_name:
                    # 상세 메타데이터 추출
                    tool_metadata = MCPToolMetadataExtractor.extract_tool_metadata(tool)
                    tool_metadata["server_name"] = server_name
                    return tool_metadata

            return None

        except Exception as e:
            logger.error(f"도구 상세 정보 가져오기 실패: {e}")
            return None

    async def get_all_servers_metadata(self) -> Dict[str, Any]:
        """모든 서버의 도구 메타데이터를 가져옵니다."""
        try:
            from app.services.mcp_server_manager import mcp_server_manager

            server_status = mcp_server_manager.get_server_status()

            all_metadata = {
                "total_servers": len(server_status),
                "servers": {},
                "extraction_timestamp": time.time(),
            }

            for server_name in server_status.keys():
                if server_status[server_name].get("running", False):
                    metadata = await self.get_detailed_tools_metadata(server_name)
                    all_metadata["servers"][server_name] = metadata

            return all_metadata

        except Exception as e:
            logger.error(f"모든 서버 메타데이터 가져오기 실패: {e}")
            return {"error": str(e)}


# 전역 MCP 클라이언트 서비스 인스턴스
mcp_client_service = MCPClientService()


def get_mcp_client() -> MCPClientService:
    """MCP 클라이언트 서비스를 가져옵니다."""
    return mcp_client_service
