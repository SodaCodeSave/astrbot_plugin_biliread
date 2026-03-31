from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api import AstrBotConfig

from pydantic import Field
from pydantic.dataclasses import dataclass

from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool
from astrbot.core.astr_agent_context import AstrAgentContext

import json
import aiohttp
from bilibili_api import video, Credential

# 定义需要忽略的导入错误（如果是本地开发环境检查）
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)


@dataclass(config=dict(arbitrary_types_allowed=True))
class BilibiliTool(FunctionTool[AstrAgentContext]):
    name: str = "bilibili_read"
    description: str = "获取一个哔哩哔哩视频的概要，如果视频没有字幕则返回提示信息。"
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

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> str:
        bvid = kwargs.get("bvid")

        if not bvid:
            return "错误：未提供 BVID 参数。"

        try:
            # 1. 初始化凭证和视频对象
            # 注意：即使是公开视频，建议也传入 Credential，否则可能遭遇风控限制
            credential = Credential(sessdata=self.sessdata, bili_jct=self.bili_jct)
            v = video.Video(bvid, credential=credential)

            # 2. 获取视频基础信息
            info = await v.get_info()
            title = info.get("title", "未知标题")

            # 3. 获取 CID
            cid = await v.get_cid(0)

            # 4. 获取字幕列表
            subtitle_info = await v.get_subtitle(cid)

            # 优化：检测是否存在字幕
            if (
                not subtitle_info
                or "subtitles" not in subtitle_info
                or not subtitle_info["subtitles"]
            ):
                return f"视频《{title}》暂无字幕，无法生成总结。请尝试其他视频。"

            # 优化：优先寻找中文字幕，如果没有则取第一个
            target_subtitle = None
            for sub in subtitle_info["subtitles"]:
                if sub.get("lan", "").startswith("zh"):  # 匹配 zh-CN, zh-Hans 等
                    target_subtitle = sub
                    break

            if not target_subtitle:
                target_subtitle = subtitle_info["subtitles"][0]

            subtitle_url = target_subtitle["subtitle_url"]
            logger.info(f"正在获取视频《{title}》的字幕: {subtitle_url}")

            # 5. 获取字幕内容
            if not subtitle_url.startswith("http"):
                subtitle_url = "https:" + subtitle_url

            subtitle_text = ""
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(subtitle_url) as resp:
                    if resp.status == 200:
                        subtitle_json = await resp.json()
                        # 解析字幕
                        # 格式通常为 {"body": [{"content": "...", "from": ...}, ...]}
                        body = subtitle_json.get("body", [])
                        subtitle_text = "\n".join(
                            [item.get("content", "") for item in body]
                        )
                    else:
                        return f"获取字幕文件失败，状态码: {resp.status}"

            if not subtitle_text:
                return f"视频《{title}》字幕内容为空。"

            # 6. 调用 LLM 进行总结
            # 如果字幕过长，建议在此处进行截断，防止超出 Context 限制
            # 这里的 prompt 可以根据需要调整
            prompt = (
                f"这是视频《{title}》的字幕内容。"
                f"请你扮演一个视频总结助手，根据字幕内容总结视频的核心观点。"
                f"要求语言简练，保留关键信息，不要只是罗列时间轴：\n\n{subtitle_text}"
            )

            # 检查 llm_provider_id 是否配置
            if not self.llm_provider_id:
                return "插件配置错误：未配置 llm_provider_id，无法调用大模型。"

            ai_resp = await self.ct.llm_generate(
                chat_provider_id=self.llm_provider_id,
                prompt=prompt,
            )

            return ai_resp

        except Exception as e:
            logger.error(f"BilibiliTool 处理出错: {e}")
            return f"处理视频时发生错误: {str(e)}。请检查BVID是否正确或Cookie是否过期。"


@register(
    "astrbot_plugin_biliread",
    "SodaCode",
    "让你的AstrBot看懂视频，而不是像机器人一样输出视频大纲",
    "1.0.1",
)
class BiliRead(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

        # 安全获取配置
        # 建议在 metadata.yaml 中将配置项命名为 sessdata 和 bili_jct 以便直接映射
        # 如果配置结构是 bilibili_cookie: { sessdata: ..., id: ... }，则如下处理：
        plugin_config = config or {}
        bilibili_cookie = plugin_config.get("bilibili_cookie", {})

        sessdata = bilibili_cookie.get("sessdata", "")
        # 注意：这里假设用户配置中键名为 id，建议改为 bili_jct 更直观
        bili_jct = bilibili_cookie.get("id", "") or bilibili_cookie.get("bili_jct", "")

        llm_provider_id = plugin_config.get("llm_provider_id", "")

        logger.info(f"BiliRead 插件加载 - LLM Provider: {llm_provider_id}")

        if not sessdata:
            logger.warning(
                "BiliRead: 未检测到 SESSDATA，获取高清字幕或限制级视频可能会失败。"
            )

        # 实例化并注册工具
        tool = BilibiliTool(
            sessdata=sessdata,
            bili_jct=bili_jct,
            ct=self.context,
            llm_provider_id=llm_provider_id,
        )
        self.context.add_llm_tools(tool)

    async def initialize(self):
        pass

    @filter.command("biliread")
    async def biliread(self, event: AstrMessageEvent):
        # 这里可以增加一个简单的测试指令
        yield event.plain_result(
            "BiliRead 插件已就绪。请直接发送 BVID 或让 AI 调用工具。"
        )

    async def terminate(self):
        pass
