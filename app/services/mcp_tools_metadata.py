"""
개선된 MCP 도구 메타데이터 추출 함수들
"""

import logging
from typing import Dict, Any, List, Optional
import json
import inspect
import time
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class MCPToolMetadataExtractor:
    """MCP 도구 메타데이터 추출기"""

    @staticmethod
    def extract_tool_metadata(tool) -> Dict[str, Any]:
        """개별 도구에서 메타데이터를 추출합니다."""
        metadata = {
            "name": "unknown",
            "description": "",
            "args_schema": {},
            "tool_type": type(tool).__name__,
            "input_schema": {},
            "annotations": {},
            "examples": [],
            "return_type": "any",
        }

        try:
            # 1. 기본 속성들 추출
            metadata["name"] = MCPToolMetadataExtractor._extract_name(tool)
            metadata["description"] = MCPToolMetadataExtractor._extract_description(
                tool
            )
            metadata["args_schema"] = MCPToolMetadataExtractor._extract_args_schema(
                tool
            )
            metadata["input_schema"] = MCPToolMetadataExtractor._extract_input_schema(
                tool
            )
            metadata["annotations"] = MCPToolMetadataExtractor._extract_annotations(
                tool
            )
            metadata["examples"] = MCPToolMetadataExtractor._extract_examples(tool)
            metadata["return_type"] = MCPToolMetadataExtractor._extract_return_type(
                tool
            )

            # 2. 추가 메타데이터
            metadata.update(MCPToolMetadataExtractor._extract_additional_metadata(tool))

        except Exception as e:
            logger.warning(f"도구 메타데이터 추출 중 오류: {e}")
            metadata["extraction_error"] = str(e)

        return metadata

    @staticmethod
    def _extract_name(tool) -> str:
        """도구 이름 추출"""
        # 가능한 이름 속성들을 순서대로 시도
        name_attrs = ["name", "tool_name", "function_name", "_name", "__name__"]

        for attr in name_attrs:
            if hasattr(tool, attr):
                name = getattr(tool, attr)
                if name and isinstance(name, str):
                    return name

        # 클래스 이름에서 추출
        class_name = type(tool).__name__
        if class_name != "BaseTool":
            return class_name.lower().replace("tool", "")

        return "unknown_tool"

    @staticmethod
    def _extract_description(tool) -> str:
        """도구 설명 추출"""
        # 가능한 설명 속성들
        desc_attrs = ["description", "desc", "__doc__", "help", "summary"]

        for attr in desc_attrs:
            if hasattr(tool, attr):
                desc = getattr(tool, attr)
                if desc and isinstance(desc, str):
                    return desc.strip()

        # 함수의 docstring 확인
        if hasattr(tool, "func") and hasattr(tool.func, "__doc__"):
            doc = tool.func.__doc__
            if doc:
                return doc.strip()

        return ""

    @staticmethod
    def _extract_args_schema(tool) -> Dict[str, Any]:
        """도구 인수 스키마 추출"""
        schema = {}

        try:
            # 1. args_schema 속성 확인
            if hasattr(tool, "args_schema"):
                schema_obj = getattr(tool, "args_schema")
                if schema_obj:
                    if hasattr(schema_obj, "schema"):
                        # Pydantic 모델인 경우
                        return schema_obj.schema()
                    elif isinstance(schema_obj, dict):
                        return schema_obj

            # 2. args 속성 확인
            if hasattr(tool, "args"):
                args = getattr(tool, "args")
                if isinstance(args, dict):
                    return args

            # 3. 함수 시그니처에서 추출
            if hasattr(tool, "func"):
                sig = inspect.signature(tool.func)
                properties = {}
                required = []

                for param_name, param in sig.parameters.items():
                    if param_name in ["self", "cls"]:
                        continue

                    param_info = {"type": "string"}  # 기본값

                    # 타입 힌트 확인
                    if param.annotation != inspect.Parameter.empty:
                        param_info["type"] = (
                            MCPToolMetadataExtractor._python_type_to_json_type(
                                param.annotation
                            )
                        )

                    # 기본값 확인
                    if param.default == inspect.Parameter.empty:
                        required.append(param_name)
                    else:
                        param_info["default"] = param.default

                    properties[param_name] = param_info

                schema = {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                }

        except Exception as e:
            logger.warning(f"args_schema 추출 실패: {e}")

        return schema

    @staticmethod
    def _extract_input_schema(tool) -> Dict[str, Any]:
        """입력 스키마 추출 (MCP 표준 형식)"""
        try:
            # 1. input_schema 속성 직접 확인
            if hasattr(tool, "input_schema"):
                schema = getattr(tool, "input_schema")
                if isinstance(schema, dict):
                    return schema

            # 2. args_schema를 input_schema로 변환
            args_schema = MCPToolMetadataExtractor._extract_args_schema(tool)
            if args_schema:
                return args_schema

        except Exception as e:
            logger.warning(f"input_schema 추출 실패: {e}")

        return {}

    @staticmethod
    def _extract_annotations(tool) -> Dict[str, Any]:
        """도구 어노테이션 추출"""
        annotations = {}

        try:
            # MCP 표준 어노테이션들
            annotation_attrs = [
                "readOnlyHint",
                "read_only_hint",
                "read_only",
                "destructiveHint",
                "destructive_hint",
                "destructive",
                "idempotentHint",
                "idempotent_hint",
                "idempotent",
                "openWorldHint",
                "open_world_hint",
                "open_world",
            ]

            for attr in annotation_attrs:
                if hasattr(tool, attr):
                    value = getattr(tool, attr)
                    if isinstance(value, bool):
                        # 표준 형식으로 변환
                        standard_key = attr.replace("_hint", "Hint").replace("_", "")
                        if not standard_key.endswith("Hint"):
                            standard_key += "Hint"
                        annotations[standard_key] = value

            # 추가 메타데이터
            if hasattr(tool, "metadata"):
                metadata = getattr(tool, "metadata")
                if isinstance(metadata, dict):
                    annotations.update(metadata)

        except Exception as e:
            logger.warning(f"annotations 추출 실패: {e}")

        return annotations

    @staticmethod
    def _extract_examples(tool) -> List[Dict[str, Any]]:
        """도구 사용 예제 추출"""
        examples = []

        try:
            # examples 속성 확인
            if hasattr(tool, "examples"):
                examples_attr = getattr(tool, "examples")
                if isinstance(examples_attr, list):
                    return examples_attr
                elif isinstance(examples_attr, dict):
                    return [examples_attr]

            # example 속성 확인 (단수형)
            if hasattr(tool, "example"):
                example = getattr(tool, "example")
                if example:
                    return [example]

        except Exception as e:
            logger.warning(f"examples 추출 실패: {e}")

        return examples

    @staticmethod
    def _extract_return_type(tool) -> str:
        """반환 타입 추출"""
        try:
            # 함수 시그니처에서 반환 타입 확인
            if hasattr(tool, "func") and tool.func is not None and callable(tool.func):
                try:
                    sig = inspect.signature(tool.func)
                    if sig.return_annotation != inspect.Signature.empty:
                        return MCPToolMetadataExtractor._python_type_to_json_type(
                            sig.return_annotation
                        )
                except (ValueError, TypeError, AttributeError) as e:
                    logger.debug(f"함수 시그니처 분석 실패: {e}")

            # return_type 속성 확인
            if hasattr(tool, "return_type"):
                return_type = getattr(tool, "return_type")
                if isinstance(return_type, str):
                    return return_type

        except Exception as e:
            logger.debug(f"return_type 추출 실패: {e}")

        return "any"

    @staticmethod
    def _extract_additional_metadata(tool) -> Dict[str, Any]:
        """추가 메타데이터 추출"""
        additional = {}

        try:
            # 도구 클래스 정보
            additional["tool_class"] = type(tool).__name__
            additional["tool_module"] = getattr(type(tool), "__module__", "unknown")

            # 사용 가능한 모든 속성 목록 (디버깅용) - 함수 객체 제외
            all_attrs = []
            for attr in dir(tool):
                if not attr.startswith("_"):
                    try:
                        value = getattr(tool, attr)
                        # 함수 객체는 제외 (JSON 직렬화 문제 방지)
                        if not callable(value):
                            all_attrs.append(attr)
                    except Exception:
                        continue
            additional["available_attributes"] = all_attrs

            # 특별한 속성들 - 함수 객체 제외
            special_attrs = [
                "version",
                "author",
                "category",
                "tags",
                "requires",
                "optional",
            ]
            for attr in special_attrs:
                if hasattr(tool, attr):
                    value = getattr(tool, attr)
                    # 함수 객체가 아닌 경우만 추가
                    if not callable(value):
                        additional[attr] = value

        except Exception as e:
            logger.warning(f"추가 메타데이터 추출 실패: {e}")

        return additional

    @staticmethod
    def _python_type_to_json_type(python_type) -> str:
        """Python 타입을 JSON 스키마 타입으로 변환"""
        type_mapping = {
            str: "string",
            int: "integer",
            float: "number",
            bool: "boolean",
            list: "array",
            dict: "object",
            type(None): "null",
        }

        # 기본 타입 확인
        if python_type in type_mapping:
            return type_mapping[python_type]

        # 타입 이름으로 확인
        type_name = getattr(python_type, "__name__", str(python_type)).lower()

        if "str" in type_name or "string" in type_name:
            return "string"
        elif "int" in type_name or "integer" in type_name:
            return "integer"
        elif "float" in type_name or "number" in type_name:
            return "number"
        elif "bool" in type_name or "boolean" in type_name:
            return "boolean"
        elif "list" in type_name or "array" in type_name:
            return "array"
        elif "dict" in type_name or "object" in type_name:
            return "object"

        return "string"  # 기본값
