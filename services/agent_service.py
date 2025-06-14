#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
智能代理服务
负责分析内容，并决定是否需要通过工具（如搜索）来丰富内容，然后再进行总结。
"""

import asyncio
import json
from typing import Dict, Any, Union, Optional, TYPE_CHECKING
from loguru import logger
from pydantic import Field, BaseModel
from duckduckgo_search import DDGS
from duckduckgo_search.exceptions import RatelimitException, DuckDuckGoSearchException

from services.llm_service import LLMService

# 仅在类型检查时导入，以避免循环导入
if TYPE_CHECKING:
    from services.content_extractor import ContentExtractor


# === Pydantic 模型定义 ===

class StructuredNote(BaseModel):
    """结构化的笔记内容模型"""
    explanation_blog: str = Field(..., description="用于生成gist的、易于理解的博客风格长文解释，作为思维链的显式输出。")
    date: str = Field(..., description="核心论文或官方报道的发布年月 (格式 YYYY.MM)。如果内容与特定作品无关，则使用链接内容的年月。")
    title: str = Field(..., description="核心论文、项目或官方报道的**完整、准确的标题**。如果内容与特定核心作品无关，则使用链接内容的标题。")
    link_title: str = Field(..., description="原始链接的网页标题。")
    gist: str = Field(..., description="对文章核心价值的深度、精炼、易懂的中文笔记。目标是用2-4句话点明核心贡献/观点，并包含关键数据。")

class SearchAndSummarize(BaseModel):
    """
    当文章内容明显引用了某个核心的、可搜索的实体（如论文、GitHub项目、特定事件）时，
    使用此工具。这个工具会先搜索该实体，获取更直接的信息，然后再进行总结。
    """
    query: str = Field(..., description="根据文章内容提取出的、最核心的搜索关键词。例如 'SELF-REFLECT: Learning to Refine Text-to-Image Generation' 或 'Llama 3'。")

class DirectSummarize(BaseModel):
    """
    当文章内容本身就是信息的主要来源，信息完整，或者没有明确的可搜索实体时，使用此工具直接对现有内容进行总结。
    """
    reason: str = Field(..., description="为什么选择直接总结的简要原因。例如'文章本身是观点性博客'或'内容是完整的新闻报道'。")

class IrrelevantContent(BaseModel):
    """
    当内容与AI研究或AI资讯无关，或内容无实质信息（如单纯的会议链接、推广活动）时使用此工具。
    这将中止后续的处理流程。
    """
    reason: str = Field(..., description="判断内容不相关或无实质信息的简要原因。例如'内容是腾讯会议链接'或'内容是营销广告'。")


class AgentService:
    """智能代理服务类"""

    def __init__(self, config: Dict[str, Any], llm_service: LLMService, content_extractor: 'ContentExtractor'):
        """
        初始化Agent服务

        Args:
            config: 全局配置对象
            llm_service: LLM服务实例
            content_extractor: 内容提取器实例，用于获取搜索结果页面的内容
        """
        self.config = config
        self.llm_service = llm_service
        self.content_extractor = content_extractor
        logger.info("智能代理服务初始化成功。")

    async def process_content_to_note(self, original_content: str, conversation_context: str) -> Optional[StructuredNote]:
        """
        处理原始内容，通过决策、丰富、总结的完整流程，生成结构化笔记。

        Args:
            original_content: 从链接中提取的原始内容。
            conversation_context: 围绕该链接的对话上下文。

        Returns:
            一个结构化的笔记Pydantic模型，或在内容被判断为不相关时返回None。
        """
        # 1. 决策并可能地丰富内容
        content_for_summary = await self._decide_and_enrich(original_content)

        if content_for_summary is None:
            logger.info("内容被判断为不相关或无价值，处理流程终止。")
            return None
        
        # 2. 使用最终内容生成结构化笔记
        structured_note = await self.generate_structured_note(
            article_content=content_for_summary,
            conversation_context=conversation_context
        )
        return structured_note

    async def _decide_and_enrich(self, original_content: str) -> Optional[str]:
        """
        分析原始内容，决定是直接总结还是先搜索再总结，并返回最终用于总结的文本。
        如果内容不相关，则返回None。
        （原 decide_and_enrich 方法，现在是私有方法）
        """
        if not self.config.get("agent", {}).get("enabled", True):
             logger.info("智能代理未启用，直接返回原始内容。")
             return original_content

        logger.info("智能代理开始分析内容，决策中...")
        
        content_for_decision = original_content[:self.config.get("agent", {}).get("max_decision_content", 4000)]

        prompt = f"""
你是一个智能分析师。你的任务是阅读下面的文章内容，并决定如何最好地处理它。你有三个选择：

1.  **搜索并总结 (SearchAndSummarize)**: 如果文章内容主要是对另一个核心资源的介绍、评论或摘要（例如一篇论文、一个GitHub项目、一个特定的开源模型），你应该使用这个工具。你需要从文章中提取出那个核心资源的最准确的名称作为搜索词。
2.  **直接总结 (DirectSummarize)**: 如果文章本身就是信息的主要来源（例如一篇完整的博客文章、一篇新闻报道、一篇观点性文章），并且内容与AI研究或AI技术资讯相关，你应该使用这个工具。
3.  **内容不相关 (IrrelevantContent)**: 如果文章内容与AI研究或AI技术资讯**完全无关**，或者没有信息含量（例如只是一个会议链接、一封营销邮件、一个广告页面），你应该使用这个工具。

请根据下面的文章内容，选择最合适的工具。

[文章内容]
{content_for_decision}
"""
        try:
            decision = await self.llm_service.aclient.chat.completions.create(
                model=self.llm_service.chat_model,
                response_model=Union[SearchAndSummarize, DirectSummarize, IrrelevantContent],
                messages=[
                    {"role": "user", "content": prompt},
                ],
                max_retries=1,
            )
            
            if isinstance(decision, SearchAndSummarize):
                logger.info(f"代理决策: [搜索并总结]，查询: '{decision.query}'")
                return await self._search_and_get_content(decision.query, original_content)
            
            elif isinstance(decision, DirectSummarize):
                logger.info(f"代理决策: [直接总结]，原因: '{decision.reason}'")
                return original_content

            elif isinstance(decision, IrrelevantContent):
                logger.info(f"代理决策: [内容不相关]，原因: '{decision.reason}'。终止处理。")
                return None

        except Exception as e:
            logger.error(f"代理决策过程出错: {e}，将回退到直接总结。", exc_info=True)
            return original_content
            
        return original_content

    async def _search_and_get_content(self, query: str, original_content: str) -> str:
        """
        执行搜索，获取新内容，并与原始内容合并。
        由于新版duckduckgo-search是同步的，我们使用asyncio.to_thread在非阻塞的线程中运行它。
        """
        logger.info(f"正在执行非阻塞的同步搜索: {query}")
        
        # 兼容应用全局代理配置
        proxy_config = self.config.get("proxy", {})
        proxy = proxy_config.get("https") or proxy_config.get("socks5")
        
        if proxy:
            logger.info(f"检测到并使用全局代理进行搜索: {proxy}")
        
        try:
            # 定义将在独立线程中运行的同步函数
            def sync_search():
                # 使用with语句确保资源被正确管理
                with DDGS(proxy=proxy, timeout=20) as ddgs:
                    # 新版库的text方法直接返回一个列表
                    return ddgs.text(query, max_results=3)

            # 使用asyncio.to_thread运行同步代码，避免阻塞事件循环
            results = await asyncio.to_thread(sync_search)

            if not results:
                logger.warning(f"未能找到关于 '{query}' 的任何搜索结果。")
                return original_content
            
            top_result = results[0]
            search_url = top_result['href']
            logger.info(f"找到最佳搜索结果链接: {search_url}")

            new_content_info = await self.content_extractor._fetch_content_with_reader(search_url)

            if new_content_info and new_content_info.get('content'):
                logger.info("成功从搜索结果中提取到新内容。")
                enriched_content = f"""
[原始介绍性内容]
{original_content}

---

[补充搜索到的核心内容]
来源URL: {search_url}
标题: {new_content_info.get('title')}
内容:
{new_content_info.get('content')[:10000]}
"""
                return enriched_content
            else:
                logger.warning("从搜索结果链接中提取内容失败，将使用原始内容。")
                return original_content

        except RatelimitException:
            # 捕获特定的速率限制异常，给出明确提示
            logger.error(f"搜索时遭遇速率限制。请考虑在配置中添加代理或检查代理是否可用。将回退到直接总结。")
            return original_content
        except DuckDuckGoSearchException as e:
            # 捕获其他来自库的搜索异常
            logger.error(f"DuckDuckGo搜索时发生错误: {e}", exc_info=True)
            return original_content
        except Exception as e:
            # 捕获其他通用异常
            logger.error(f"搜索或提取新内容时发生未知错误: {e}", exc_info=True)
            return original_content
    
    async def generate_structured_note(self, article_content: str, conversation_context: str) -> StructuredNote:
        """
        使用LLM和Instructor生成结构化的笔记内容。
        此方法采用"显式思维链"模式：引导LLM先输出一篇完整的博客解读，然后再基于此解读提炼笔记，并将两者一并输出。
        """
        # === Stage 1: Define the ideal output structure using a few-shot example ===
        example_blog = """想象一下，你要指挥一个机器人点击手机屏幕上的"购物车"图标。在过去，它会像报经纬度一样输出图标的精确坐标（比如 x=0.345, y=0.721），然后再把这串数字告诉机器人。这种方式不仅死板（按钮那么大一块，为啥非要点最中心？），而且极度脆弱——但凡手机屏幕尺寸变了，或者UI布局稍微调整一下，之前测的坐标就全作废了，机器人瞬间就"瞎了"。这就是传统GUI Agent的痛点：它们不"理解"界面，只"记忆"坐标。

微软的研究团队决定彻底改变这个现状，他们推出的GUI-Actor，就是要让AI Agent像我们人类一样，用"眼睛"去"看懂"界面，然后直接伸手去点。它的核心思想，就是一场"无坐标革命"。

为了实现这个目标，GUI-Actor引入了几项关键技术：
1.  **<ACTOR>令牌：给AI一根"虚拟手指"**。在给AI的指令里，不再包含坐标，而是插入一个特殊的`<ACTOR>`标记，比如指令变成："点击 <ACTOR> 购物车图标"。这个令牌就像一根虚拟的激光笔，通过注意力机制，AI会自动将它指向屏幕上与"购物车图标"语义最相关的视觉区域。
2.  **多区块监督：从"瞄准一个点"到"覆盖一个面"**。传统方法只认一个正确的坐标点，稍微偏移一点就算失败。而GUI-Actor则把目标（比如按钮）所覆盖的所有图像区块（一个区块大约28x28像素）都视为正确答案。这让模型在训练时更加鲁棒，也更符合人类"点个大概就行"的直觉。
3.  **轻量验证器：AI的"二次确认"机制**。模型会基于注意力分数，选出好几个最可能的目标候选区域，然后一个极小的验证器会快速对这些候选区域进行打分，选出最优的那个。这就像我们点外卖前，会先扫一眼菜单，再最终确认点哪个菜一样。

这套"组合拳"的效果是惊人的。在行业公认的高难度专业软件测试基准ScreenSpot-Pro上，GUI-Actor仅用一个7B参数的小模型，就拿下了44.6分，而之前的业界顶尖模型UI-TARS，用了足足72B的参数，也才得到38.1分。这意味着GUI-Actor用不到十分之一的参数量，却实现了17%的性能超越。更重要的是，它在不同分辨率和布局下的表现也稳定得多，并且训练时所需的数据量也远少于传统方法。"""
        
        example_gist = """GUI-Actor通过一种"区域定位"新范式，颠覆了传统UI Agent预测(x,y)坐标的模式。其核心机制是：通过注意力模型，将指令文本中的<ACTOR>特殊标记（可理解为"虚拟手指"）与屏幕上的目标视觉区块直接关联，从而让模型"看懂"并直接锁定目标区域。正因为是选择区域而非单个点，该方法从根本上解决了模型对分辨率、UI布局变化的敏感性问题。在ScreenSpot-Pro高难度基准测试上，其实验结果惊人：一个7B的小模型得分(44.6)竟远超72B的前冠军模型(38.1)。"""

        # === Stage 2: Define the prompt with clear instructions, removing the hardcoded example ===
        prompt = f"""
# Role: 你是一位资深的技术研究分析师，同时也是一位出色的技术博主。

# Goal: 你的任务是分两步，先将技术文章解读为一篇易懂的博客，然后基于这篇博客提炼出一份精华笔记，并一起输出。

# Final Output (严格按此JSON结构输出):
你必须生成一个包含以下所有字段的JSON对象：

1.  `explanation_blog`: 一篇逻辑清晰、引人入胜的博客文章(1000字以内)。
    -   **写作要求**: 像顶级技术博主一样，娓娓道来文章的动机和价值，清晰地用大白话解释技术点，并用最亮眼的数据支撑。
    -   **绝对不要**在博客结尾写关于"未来意义"或"价值"的总结性空话。在陈述完核心思想和数据后就停止。
2.  `title`, `date`, `link_title`, `gist`:
    -   `title`: 识别文章中讨论的**核心实体**（论文、项目等）。此字段必须是该核心实体的**官方、完整标题**。如果文章本身就是核心内容（即它不是在介绍另一个东西），则此字段应为文章自身的标题。
    -   `date`: 此字段必须是**核心实体**的发布日期（格式 YYYY.MM）。如果找不到或不适用，则使用文章的发布年月。
    -   `link_title`: 原始链接的网页标题。
    -   `gist`:
        -   **来源**: 基于你上面刚刚写好的 `explanation_blog` 进行提炼。
        -   **必须解释核心机制 (How)**: 不能只说"提出新范式"，要用一句话讲清楚这个范式是怎么运作的。例如，不是说"无坐标交互"，而是要说明它是"通过注意力机制将指令中的特定标记关联到屏幕图像区块"来实现的。
        -   **连接机制与优势 (Why)**: 清晰地说明这个核心机制如何带来了关键优势。例如，"因为是区域定位而非点定位，所以对分辨率变化更鲁棒"。
        -   **数据必须带上下文**: 提及关键数据时，必须说明是在哪个测试集/基准上取得的。
        -   **可读性**: 语言要精炼，但必须保留博客中的通俗易懂性（如关键比喻或细节），让非该领域的人也能快速理解。
        -   **格式要求**: 最终形成一个2-4句话的、逻辑连贯的中文段落(300字以内)。

[blog示例]
{example_blog}
[gist示例]
{example_gist}

---
[对话上下文]
{conversation_context}
---
[文章内容]
{article_content[:15000]}
---

请开始创作，并生成包含 `explanation_blog` 和其他笔记字段的完整JSON对象。
"""
        try:
            note = await self.llm_service.aclient.chat.completions.create(
                model=self.llm_service.chat_model,

                response_model=StructuredNote,
                messages=[
                    # 为模型提供一个高质量的输入输出范例
                    {"role": "user", "content": "请为我分析这篇关于GUI-Actor的文章..."},
                    # 这是本次实际需要处理的任务
                    {"role": "user", "content": prompt},
                ],
                max_retries=2,
            )
            logger.info("LLM基于显式思维链和Few-shot示例，成功生成了博客和结构化笔记。")
            return note
        except Exception as e:
            logger.error(f"使用Instructor和显式思维链生成结构化笔记失败: {e}", exc_info=True)
            raise 