"""
LLM 客户端

支持 GLM API 和原生 Function Calling。
"""

import json
import os
from typing import Any, Dict, List, Optional, Generator

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from codemate_agent.schema import LLMResponse, Message, ToolCall, TokenUsage


class GLMClient:
    """
    GLM API 客户端

    支持通过 OpenAI 兼容的 API 格式调用智谱 AI。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "glm-4.7",
        base_url: str = "https://open.bigmodel.cn/api/coding/paas/v4/",
        temperature: float = 0.7,
    ):
        """
        初始化 GLM 客户端

        Args:
            api_key: GLM API Key
            model: 模型名称
            base_url: API Base URL
            temperature: 温度参数
        """
        self.api_key = api_key or os.getenv("GLM_API_KEY")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature

        if not self.api_key:
            raise ValueError("GLM API Key 未设置，请设置 GLM_API_KEY 环境变量")

        # 延迟导入 zhipuai
        try:
            from zhipuai import ZhipuAI
            self.client = ZhipuAI(api_key=self.api_key, base_url=self.base_url)
        except ImportError:
            raise ImportError("请安装 zhipuai 库: pip install zhipuai")

    def complete(
        self,
        messages: List[Message],
        tools: Optional[List[Dict]] = None,
        max_tokens: int = 8192,  # 🆕 提高到 8K，支持更长的输出
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
            raise RuntimeError(f"GLM API 调用失败: {e}") from e

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
            raise RuntimeError(f"GLM API 流式调用失败: {e}") from e

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
        for msg in messages:
            api_msg = {"role": msg.role, "content": msg.content}
            if msg.tool_calls:
                api_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": json.dumps(tc.function.arguments)
                        }
                    }
                    for tc in msg.tool_calls
                ]
            if msg.tool_call_id:
                api_msg["tool_call_id"] = msg.tool_call_id
            if msg.name:
                api_msg["name"] = msg.name
            api_messages.append(api_msg)
        return api_messages

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
            finish_reason=choice.finish_reason,
            usage=usage
        )

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
