# services包初始化文件 

from .llm_service import LLMService
from .rag_service import RAGService
from .content_extractor import ContentExtractor
from .note_manager import NoteManager
from .google_docs_manager import GoogleDocsManager
from .obsidian_manager import ObsidianManager

# Mac微信Hook服务（仅macOS可用）
try:
    from .mac_wechat_service import MacWeChatService
    from .mac_wechat_hook import MacWeChatHook
except ImportError:
    # 非macOS系统可能无法导入
    MacWeChatService = None
    MacWeChatHook = None

__all__ = [
    'LLMService',
    'RAGService',
    'ContentExtractor',
    'NoteManager',
    'GoogleDocsManager',
    'ObsidianManager',
    'MacWeChatService',
    'MacWeChatHook',
] 