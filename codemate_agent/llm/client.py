"""
LLM 客户端

支持多种 LLM API 提供商：MiniMax、OpenAI、Anthropic 等。
支持原生 Function Calling。
"""

import json
import os
import re
from typing import Any, Dict, List, Optional, Generator

import requests
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from codemate_agent.schema import LLMResponse, Message, ToolCall, TokenUsage


class LLMClient:
    """
    通用 LLM API 客户端

    支持通过 OpenAI 兼容的 API 格式调用多种 LLM 提供商。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "mini-max-chat",
        base_url: str = "https://api.minimaxi.com/anthropic/v1",
        temperature: float = 0.7,
        provider: str = "minimax",
    ):
        """
        初始化 LLM 客户端

        Args:
            api_key: API Key
            model: 模型名称
            base_url: API Base URL
            temperature: 温度参数
            provider: API 提供商 (minimax, openai, anthropic)
        """
        self.api_key = api_key or os.getenv("API_KEY")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.provider = provider

        if not self.api_key:
            raise ValueError("API Key 未设置，请设置 API_KEY 环境变量")

        # 根据提供商设置请求头
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        # MiniMax 使用不同的认证方式
        if provider == "minimax":
            self.headers["Authorization"] = self.api_key  # MiniMax 直接使用 API Key
            # 使用 OpenAI 兼容客户端
            try:
                from openai import OpenAI
                self.client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url,
                    max_retries=0,  # 禁用自动重试，使用自定义重试逻辑
                )
            except ImportError:
                raise ImportError("请安装 openai 库: pip install openai")
        else:
            # 其他提供商使用 zhipuai 或 OpenAI
            try:
                from openai import OpenAI
                self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            except ImportError:
                try:
                    from zhipuai import ZhipuAI
                    self.client = ZhipuAI(api_key=self.api_key, base_url=self.base_url)
                except ImportError:
                    raise ImportError("请安装 openai 或 zhipuai 库")

    def complete(
        self,
        messages: List[Message],
        tools: Optional[List[Dict]] = None,
        max_tokens: int = 4096,  # 降低默认 max_tokens 兼容性
    ) -> LLMResponse:
        """
        完成对话（支持原生 Function Calling）

        Args:
            messages: 消息列表
            tools: 工具列表（OpenAI 格式）
            max_tokens: 最大生成 token 数（默认 8192）

        Returns:
            LLMResponse: 响应结果
        """
        # 转换消息格式
        api_messages = self._convert_messages(messages)

        # 构建请求参数
        params = {
            "model": self.model,
            "messages": api_messages,
            "temperature": self.temperature,
            "max_tokens": max_tokens,
        }

        # 添加工具
        if tools:
            params["tools"] = tools

        try:
            response = self._call_with_retry(params)

            # 解析响应
            return self._parse_response(response)

        except Exception as e:
            # 如果是 function calling 不支持的错误，尝试不带 tools 重试
            error_str = str(e)
            if tools and ("invalid chat setting" in error_str or "bad_request_error" in error_str):
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Function calling 不被支持 ({self.model})，尝试不带 tools 重试...")

                # 移除 tools 参数重试
                params_without_tools = params.copy()
                del params_without_tools["tools"]
                params_without_tools["messages"] = self._sanitize_messages_for_text_only(api_messages)
                try:
                    response = self._call_with_retry(params_without_tools)
                    return self._parse_response(response)
                except Exception as retry_err:
                    retry_error_str = str(retry_err)
                    if "invalid chat setting" in retry_error_str or "bad_request_error" in retry_error_str:
                        logger.warning(f"模型参数不兼容 ({self.model})，尝试最小参数重试...")
                        minimal_params = {
                            "model": self.model,
                            "messages": self._sanitize_messages_for_text_only(api_messages),
                        }
                        try:
                            response = self._call_with_retry(minimal_params)
                            return self._parse_response(response)
                        except Exception as minimal_err:
                            minimal_error_str = str(minimal_err)
                            if "invalid chat setting" in minimal_error_str or "bad_request_error" in minimal_error_str:
                                logger.warning(f"最小参数仍不兼容 ({self.model})，尝试单轮纯文本重试...")
                                plain_params = {
                                    "model": self.model,
                                    "messages": [{
                                        "role": "user",
                                        "content": self._messages_to_single_prompt(api_messages),
                                    }],
                                }
                                response = self._call_with_retry(plain_params)
                                return self._parse_response(response)
                            raise
                    raise

            raise RuntimeError(f"LLM API 调用失败: {e}") from e

    def complete_stream(
        self,
        messages: List[Message],
        tools: Optional[List[Dict]] = None,
        max_tokens: int = 8192,  # 🆕 提高到 8K
    ) -> Generator[str, None, None]:
        """
        流式完成对话

        Args:
            messages: 消息列表
            tools: 工具列表
            max_tokens: 最大生成 token 数（默认 8192）

        Yields:
            str: 生成的内容片段
        """
        api_messages = self._convert_messages(messages)

        params = {
            "model": self.model,
            "messages": api_messages,
            "temperature": self.temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        if tools:
            params["tools"] = tools

        try:
            stream = self.client.chat.completions.create(**params)

            for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            raise RuntimeError(f"LLM API 流式调用失败: {e}") from e

    def _call_with_retry(self, params: Dict) -> Any:
        """
        带重试机制的 API 调用

        使用指数退避策略，最多重试 3 次。

        Args:
            params: API 请求参数

        Returns:
            API 响应

        Raises:
            RuntimeError: 重试失败后抛出异常
        """
        import logging

        # 可重试的异常类型
        RETRYABLE_ERRORS = (
            ConnectionError,
            TimeoutError,
            OSError,
        )

        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type(RETRYABLE_ERRORS),
            reraise=True,
        )
        def _do_call() -> Any:
            return self.client.chat.completions.create(**params)

        try:
            return _do_call()
        except Exception as e:
            # 记录重试失败
            logging.getLogger(__name__).warning(f"API 调用重试失败: {e}")
            raise

    def _convert_messages(self, messages: List[Message]) -> List[Dict]:
        """转换消息格式为 API 格式"""
        api_messages = []
        seen_system = False
        preserve_tool_call_ids = set()
        if self.provider == "minimax":
            preserve_tool_call_ids = self._collect_recent_tool_call_ids(messages, keep_rounds=2)

        for msg in messages:
            role = msg.role
            content = msg.content

            # MiniMax-M2 仅允许一个 system 消息；后续 system 需降级为 user
            if self.provider == "minimax" and role == "system":
                if not seen_system:
                    seen_system = True
                else:
                    role = "user"
                    content = f"[System note]\n{content}"

            # MiniMax 对历史 tool_call 协议校验严格，历史对话统一降级为纯文本
            if self.provider == "minimax" and role == "tool":
                if msg.tool_call_id not in preserve_tool_call_ids:
                    role = "assistant"
                    tool_name = msg.name or "tool"
                    content = f"[{tool_name} output]\n{content}"

            api_msg = {"role": role, "content": content}
            if msg.tool_calls:
                selected_calls = msg.tool_calls
                if self.provider == "minimax":
                    selected_calls = [tc for tc in msg.tool_calls if tc.id in preserve_tool_call_ids]
                    if not selected_calls and role == "assistant" and not content.strip():
                        api_msg["content"] = "[Tool call context omitted for compatibility]"

                if selected_calls:
                    api_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": json.dumps(tc.function.arguments)
                        }
                    }
                    for tc in selected_calls
                    ]
            if msg.tool_call_id and (self.provider != "minimax" or msg.tool_call_id in preserve_tool_call_ids):
                api_msg["tool_call_id"] = msg.tool_call_id
            if msg.name and (self.provider != "minimax" or msg.tool_call_id in preserve_tool_call_ids):
                api_msg["name"] = msg.name
            api_messages.append(api_msg)
        return api_messages

    def _collect_recent_tool_call_ids(self, messages: List[Message], keep_rounds: int = 2) -> set[str]:
        """收集最近 N 轮工具调用 ID，用于在 MiniMax 下保留结构化工具历史。"""
        ids: set[str] = set()
        rounds = 0
        for msg in reversed(messages):
            if msg.role == "assistant" and msg.tool_calls:
                ids.update(tc.id for tc in msg.tool_calls if tc.id)
                rounds += 1
                if rounds >= keep_rounds:
                    break
        return ids

    def _sanitize_messages_for_text_only(self, api_messages: List[Dict]) -> List[Dict]:
        """将含工具语义的消息降级为纯文本对话，兼容不支持 function calling 的模型。"""
        sanitized: List[Dict] = []
        for msg in api_messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)

            if role == "tool":
                tool_name = msg.get("name") or "tool"
                role = "assistant"
                content = f"[{tool_name} output]\n{content}"
            elif role not in {"system", "user", "assistant"}:
                role = "user"

            sanitized.append({"role": role, "content": content})
        return sanitized

    def _messages_to_single_prompt(self, api_messages: List[Dict]) -> str:
        """将多轮消息压成单轮 user 文本，作为最保守兼容兜底。"""
        parts: List[str] = []
        for msg in self._sanitize_messages_for_text_only(api_messages):
            role = msg.get("role", "user").upper()
            content = msg.get("content", "")
            parts.append(f"{role}:\n{content}")
        return "\n\n".join(parts)

    def _parse_response(self, response) -> LLMResponse:
        """解析 API 响应"""
        choice = response.choices[0]
        message = choice.message

        # 解析内容
        content = message.content or ""

        # 解析工具调用
        tool_calls = None
        if hasattr(message, 'tool_calls') and message.tool_calls:
            tool_calls = []
            for tc in message.tool_calls:
                # 解析 arguments（可能是字符串、字典或异常格式）
                args = tc.function.arguments

                # 处理字符串格式
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}

                # 处理异常格式：如果 arguments 是列表，尝试恢复
                # GLM API 有时会返回列表格式的 arguments
                if isinstance(args, list):
                    args = self._parse_list_arguments(tc.function.name, args)

                # 确保是字典
                if not isinstance(args, dict):
                    args = {}

                tool_calls.append(ToolCall(
                    id=tc.id,
                    type=tc.type,
                    function={
                        "name": tc.function.name,
                        "arguments": args
                    }
                ))
        elif self.provider == "minimax" and isinstance(content, str) and "<invoke" in content:
            content, tool_calls = self._parse_minimax_tool_calls_from_content(content)

        # 解析 token 使用
        usage = None
        if hasattr(response, 'usage') and response.usage:
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
            )

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason="tool_calls" if tool_calls else choice.finish_reason,
            usage=usage
        )

    def _parse_minimax_tool_calls_from_content(self, content: str) -> tuple[str, Optional[List[ToolCall]]]:
        """
        解析 MiniMax 文本中的 <minimax:tool_call><invoke ...> 协议。
        """
        invoke_pattern = re.compile(
            r'<invoke\s+name="([^"]+)">\s*(.*?)\s*</invoke>',
            re.DOTALL | re.IGNORECASE,
        )
        param_pattern = re.compile(
            r'<parameter\s+name="([^"]+)">\s*(.*?)\s*</parameter>',
            re.DOTALL | re.IGNORECASE,
        )

        tool_calls: List[ToolCall] = []
        for idx, match in enumerate(invoke_pattern.finditer(content), start=1):
            tool_name = match.group(1).strip()
            body = match.group(2)
            args: Dict[str, Any] = {}

            for p in param_pattern.finditer(body):
                key = p.group(1).strip()
                value_raw = p.group(2).strip()
                value: Any = value_raw
                if (value_raw.startswith("{") and value_raw.endswith("}")) or (
                    value_raw.startswith("[") and value_raw.endswith("]")
                ):
                    try:
                        value = json.loads(value_raw)
                    except json.JSONDecodeError:
                        value = value_raw
                args[key] = value

            if tool_name:
                tool_calls.append(
                    ToolCall(
                        id=f"minimax_call_{idx}",
                        type="function",
                        function={"name": tool_name, "arguments": args},
                    )
                )

        # 清理协议片段，保留纯文本说明
        cleaned = re.sub(r"<minimax:tool_call>.*?</minimax:tool_call>", "", content, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL | re.IGNORECASE).strip()

        return cleaned, tool_calls or None

    def _parse_list_arguments(self, tool_name: str, args_list: list) -> dict:
        """
        解析列表格式的 arguments

        当 GLM API 返回列表格式的 arguments 时，尝试从中恢复有效的参数。

        Args:
            tool_name: 工具名称
            args_list: 列表格式的参数

        Returns:
            恢复后的参数字典
        """
        import logging
        logger = logging.getLogger(__name__)

        # 尝试从列表中提取字典元素并合并
        recovered = {}
        valid_dicts = []

        for item in args_list:
            if isinstance(item, dict):
                valid_dicts.append(item)
            elif isinstance(item, str) and len(item) < 100:
                # 可能是键名
                recovered[item] = None

        # 合并所有字典
        for d in valid_dicts:
            recovered.update(d)

        # 如果成功恢复了参数，返回
        if recovered:
            logger.info(f"从列表格式恢复了 {tool_name} 的参数: {list(recovered.keys())}")
            return recovered

        # 如果列表看起来像代码片段，返回空字典让工具失败
        # 这样 LLM 会重新生成
        sample = str(args_list[:3])[:200]
        logger.warning(
            f"GLM API 返回了无法恢复的列表格式 arguments [{tool_name}]: {sample}... "
            f"将返回空字典，让工具调用失败以触发 LLM 重新生成"
        )
        return {}


# 兼容旧代码
class ChatResponse:
    """兼容旧版本的响应类"""
    def __init__(self, content: str, finish_reason: str, usage: dict):
        self.content = content
        self.finish_reason = finish_reason
        self.usage = usage
