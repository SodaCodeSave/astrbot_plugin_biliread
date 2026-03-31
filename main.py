import re
import aiohttp
from typing import Optional, Dict, Any

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool
from astrbot.core.astr_agent_context import AstrAgentContext
from bilibili_api import video, Credential

from pydantic import Field
from pydantic.dataclasses import dataclass

# BVID 格式预编译正则：BV开头，后续为字母或数字，通常长度为12位
BVID_PATTERN = re.compile(r"^BV[a-zA-Z0-9]+$")


@dataclass(config=dict(arbitrary_types_allowed=True))
class BilibiliTool(FunctionTool[AstrAgentContext]):
    name: str = "bilibili_read"
    description: str = "获取一个哔哩哔哩视频的概要。如果视频没有字幕则返回提示信息。"
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "bvid": {
                    "type": "string",
                    "description": "想要获取的哔哩哔哩视频的BVID，BVID以BV开头，是视频的唯一标识符",
                },
            },
            "required": ["bvid"],
        }
    )

    # 配置参数
    sessdata: str = ""
    bili_jct: str = ""
    ct: Context = Field(default=None)
    llm_provider_id: str = ""
    # 新增：字幕最大长度限制，防止上下文溢出
    max_subtitle_length: int = 4000

    def _check_config(self) -> Optional[str]:
        """防御性检查：确保核心依赖已注入"""
        if not self.ct:
            return "插件内部错误：上下文未注入"
        if not self.llm_provider_id:
            return "插件配置错误：未配置 llm_provider_id"
        return None

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> str:
        # 1. 防御性检查
        config_err = self._check_config()
        if config_err:
            return config_err

        bvid = kwargs.get("bvid", "").strip()

        # 2. 输入格式校验
        if not bvid or not BVID_PATTERN.match(bvid):
            return f"参数错误：'{bvid}' 不是合法的 BVID 格式（需以 BV 开头且仅包含字母数字）。"

        # 3. 初始化凭证
        credential = Credential(sessdata=self.sessdata, bili_jct=self.bili_jct)
        v = video.Video(bvid, credential=credential)

        try:
            # 4. 获取视频基础信息
            # 这一步可能抛出网络异常或视频不存在的 API 异常
            info = await v.get_info()
            title = info.get("title", "未知标题")

            # 5. 获取 CID
            cid = await v.get_cid(0)

            # 6. 获取字幕元数据
            subtitle_info = await v.get_subtitle(cid)

            # 业务逻辑检查：是否有字幕数据
            if not subtitle_info or not subtitle_info.get("subtitles"):
                return f"视频《{title}》暂无可用字幕，无法生成总结。"

            # 优先寻找中文字幕 (zh-CN, zh-Hans)
            target_subtitle = None
            for sub in subtitle_info["subtitles"]:
                if sub.get("lan", "").startswith("zh"):
                    target_subtitle = sub
                    break

            # 兜底：取第一个
            if not target_subtitle:
                target_subtitle = subtitle_info["subtitles"][0]

            subtitle_url = target_subtitle.get("subtitle_url", "")
            if not subtitle_url:
                return "错误：字幕元数据中缺失 URL。"

            # 7. 下载字幕内容
            if not subtitle_url.startswith("http"):
                subtitle_url = "https:" + subtitle_url

            # 日志脱敏：去除 URL 参数，防止泄露签名
            log_url = subtitle_url.split("?")[0]
            logger.info(f"正在获取视频《{title}》字幕: {log_url}")

            subtitle_text = ""
            timeout = aiohttp.ClientTimeout(total=15)

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(subtitle_url) as resp:
                    if resp.status != 200:
                        return f"下载字幕文件失败，HTTP 状态码: {resp.status}"

                    # 使用 aiohttp 直接解析 json，避免手动 import json
                    subtitle_json = await resp.json()

            # 8. 解析与截断
            body = subtitle_json.get("body", [])
            raw_text = "\n".join([item.get("content", "") for item in body])

            # 长度控制：防止 LLM 上下文溢出
            if len(raw_text) > self.max_subtitle_length:
                logger.info(f"字幕过长 ({len(raw_text)}字符)，已执行截断。")
                raw_text = (
                    raw_text[: self.max_subtitle_length] + "\n...(后续内容已省略)"
                )

            subtitle_text = raw_text

            if not subtitle_text:
                return f"视频《{title}》字幕内容解析为空。"

            # 9. 调用 LLM
            prompt = (
                f"视频标题：《{title}》\n"
                f"字幕内容：\n{subtitle_text}\n\n"
                f"请根据上述字幕内容总结视频的核心观点，保留关键信息。"
            )

            ai_resp = await self.ct.llm_generate(
                chat_provider_id=self.llm_provider_id,
                prompt=prompt,
            )

            return ai_resp

        except aiohttp.ClientError as e:
            logger.error(f"网络请求异常: {e}")
            return "网络请求异常，请稍后重试。"
        except KeyError as e:
            logger.error(f"数据解析异常，结构可能发生变更: {e}")
            return "解析字幕数据时发生错误，可能是 API 结构变更。"
        except Exception as e:
            # 捕获 bilibili_api 抛出的其他异常或未知异常
            # 建议在日志中打印完整堆栈
            logger.exception(f"处理 BVID {bvid} 时发生未知错误")
            return f"处理视频时发生内部错误: {str(e)}"


@register(
    "astrbot_plugin_biliread",
    "SodaCode",
    "让你的AstrBot看懂视频，而不是像机器人一样输出视频大纲",
    "1.1.0",
)
class BiliRead(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)

        # 1. 安全的配置读取
        # 兼容 config 是字典或 Pydantic 对象的情况
        if isinstance(config, dict):
            plugin_config = config
        elif hasattr(config, "model_dump"):
            # Pydantic v2
            plugin_config = config.model_dump()
        elif hasattr(config, "dict"):
            # Pydantic v1
            plugin_config = config.dict()
        else:
            logger.warning(f"不支持的配置类型: {type(config)}，使用默认空配置。")
            plugin_config = {}

        # 2. 提取配置项
        bilibili_cookie = plugin_config.get("bilibili_cookie", {})

        # 明确语义：不再使用有歧义的 'id'，统一读取 'bili_jct'
        # 如果用户配置了 'id'，代码逻辑上也可以尝试兼容读取，但优先使用正确键名
        sessdata = bilibili_cookie.get("sessdata", "")
        bili_jct = bilibili_cookie.get("bili_jct", bilibili_cookie.get("id", ""))
        llm_provider_id = plugin_config.get("llm_provider_id", "")
        max_len = plugin_config.get("max_subtitle_length", 4000)

        # 3. 配置完整性校验日志
        if not sessdata:
            logger.warning(
                "BiliRead: SESSDATA 未配置，可能导致无法获取高质量字幕或鉴权失败。"
            )
        if not bili_jct:
            logger.warning("BiliRead: bili_jct 未配置。")
        if not llm_provider_id:
            logger.error("BiliRead: llm_provider_id 未配置，LLM 功能将不可用。")

        # 4. 注册工具
        tool = BilibiliTool(
            sessdata=sessdata,
            bili_jct=bili_jct,
            ct=self.context,
            llm_provider_id=llm_provider_id,
            max_subtitle_length=max_len,
        )
        self.context.add_llm_tools(tool)

    async def initialize(self):
        pass

    @filter.command("biliread")
    async def biliread(self, event: AstrMessageEvent):
        yield event.plain_result(
            "BiliRead 插件已就绪。请直接发送 BVID 或让 AI 调用工具。"
        )

    async def terminate(self):
        pass
