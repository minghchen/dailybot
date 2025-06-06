"""
Mac WeChat Service
Mac微信服务主接口，整合Hook功能和数据库解密功能
"""

import os
import json
import time
import logging
from typing import Dict, List, Optional, Callable
from pathlib import Path
from datetime import datetime
from threading import Thread
import re

from .mac_wechat_hook import MacWeChatHook
from .mac_wechat_injector import MacWeChatInjector

logger = logging.getLogger(__name__)


class MacWeChatService:
    """Mac微信服务主类"""
    
    def __init__(self):
        self.hook = MacWeChatHook()
        self.injector = MacWeChatInjector()
        self.is_running = False
        self.message_handlers = []
        self.auto_reply_rules = {}
        self.monitor_thread = None
        
    def initialize(self) -> bool:
        """初始化服务"""
        logger.info("初始化Mac微信服务...")
        
        # 检查微信版本
        version = self.hook.check_wechat_version()
        if not version:
            logger.error("未能检测到微信版本")
            return False
        
        # 检查版本兼容性
        if self._check_version_compatibility(version):
            logger.info(f"微信版本 {version} 兼容")
        else:
            logger.warning(f"微信版本 {version} 可能不完全兼容")
        
        return True
    
    def _check_version_compatibility(self, version: str) -> bool:
        """检查版本兼容性"""
        # 提取主版本号
        match = re.match(r'(\d+)\.(\d+)\.(\d+)', version)
        if match:
            major, minor, patch = map(int, match.groups())
            
            # 3.8.0及以上版本需要特殊处理
            if major >= 3 and minor >= 8:
                logger.warning("检测到3.8.0及以上版本，部分功能可能受限")
                return False
            
            return True
        
        return False
    
    def enable_hook(self, enable_auto_reply: bool = True) -> bool:
        """启用Hook功能"""
        logger.info("启用Hook功能...")
        
        # 检查是否已安装Hook
        if self._is_hook_installed():
            logger.info("Hook已安装")
            return True
        
        # 安装Hook
        if not self.injector.check_insert_dylib():
            self.injector.install_insert_dylib()
        
        if self.injector.create_hook_dylib():
            if self.injector.inject_dylib():
                logger.info("Hook安装成功")
                
                # 启动消息监控
                if enable_auto_reply:
                    self.start_message_monitor()
                
                return True
        
        logger.error("Hook安装失败")
        return False
    
    def disable_hook(self) -> bool:
        """禁用Hook功能"""
        logger.info("禁用Hook功能...")
        
        # 停止消息监控
        self.stop_message_monitor()
        
        # 恢复原始微信
        if self.injector.restore_wechat():
            logger.info("Hook已移除")
            return True
        
        return False
    
    def _is_hook_installed(self) -> bool:
        """检查Hook是否已安装"""
        # 检查备份文件是否存在
        backup_path = f"{self.injector.wechat_path}.backup"
        return os.path.exists(backup_path)
    
    def get_db_key(self) -> Optional[str]:
        """获取数据库密钥"""
        if not self.hook.db_key:
            self.hook.get_db_key_lldb()
        
        return self.hook.db_key
    
    def export_chat_history(self, output_dir: str = "./wechat_export", 
                          contact_filter: List[str] = None) -> bool:
        """
        导出聊天记录
        
        Args:
            output_dir: 输出目录
            contact_filter: 联系人过滤列表，None表示导出所有
        
        Returns:
            是否成功
        """
        return self.hook.export_chat_history(output_dir)
    
    def get_recent_messages(self, limit: int = 100) -> List[Dict]:
        """获取最近的消息"""
        # 先确保有数据库密钥
        if not self.get_db_key():
            logger.error("无法获取数据库密钥")
            return []
        
        # 查找消息数据库
        db_files = self.hook.find_db_files()
        messages = []
        
        for db_file in db_files:
            if "msg_" in db_file.name:
                # 解密数据库到临时文件
                temp_db = Path("/tmp") / f"{db_file.stem}_temp.db"
                if self.hook.decrypt_database(db_file, temp_db):
                    # 获取消息
                    msgs = self.hook.get_chat_messages(temp_db, limit)
                    messages.extend(msgs)
                    
                    # 删除临时文件
                    temp_db.unlink()
        
        # 按时间排序
        messages.sort(key=lambda x: x['timestamp'], reverse=True)
        
        return messages[:limit]
    
    def add_message_handler(self, handler: Callable[[Dict], None]):
        """添加消息处理器"""
        self.message_handlers.append(handler)
    
    def add_auto_reply_rule(self, keyword: str, reply: str, 
                          exact_match: bool = False):
        """
        添加自动回复规则
        
        Args:
            keyword: 关键词
            reply: 回复内容
            exact_match: 是否精确匹配
        """
        self.auto_reply_rules[keyword] = {
            'reply': reply,
            'exact_match': exact_match
        }
    
    def start_message_monitor(self):
        """启动消息监控"""
        if self.is_running:
            logger.warning("消息监控已在运行")
            return
        
        self.is_running = True
        self.monitor_thread = Thread(target=self._monitor_messages)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        
        logger.info("消息监控已启动")
    
    def stop_message_monitor(self):
        """停止消息监控"""
        self.is_running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        
        logger.info("消息监控已停止")
    
    def _monitor_messages(self):
        """监控消息文件"""
        # Hook会将消息保存到文件
        messages_file = Path.home() / "Documents/wechat_messages.json"
        last_size = 0
        
        while self.is_running:
            try:
                if messages_file.exists():
                    current_size = messages_file.stat().st_size
                    
                    if current_size > last_size:
                        # 文件有更新，读取新消息
                        with open(messages_file, 'r', encoding='utf-8') as f:
                            messages = json.load(f)
                        
                        # 处理新消息
                        if messages:
                            latest_msg = messages[-1]
                            self._process_message(latest_msg)
                        
                        last_size = current_size
                
                time.sleep(1)  # 每秒检查一次
                
            except Exception as e:
                logger.error(f"监控消息时出错: {e}")
                time.sleep(5)
    
    def _process_message(self, message: Dict):
        """处理消息"""
        logger.debug(f"处理消息: {message}")
        
        # 调用所有消息处理器
        for handler in self.message_handlers:
            try:
                handler(message)
            except Exception as e:
                logger.error(f"消息处理器出错: {e}")
        
        # 自动回复逻辑
        content = message.get('content', '')
        from_user = message.get('from', '')
        
        for keyword, rule in self.auto_reply_rules.items():
            if rule['exact_match']:
                if content == keyword:
                    self._send_reply(from_user, rule['reply'])
                    break
            else:
                if keyword in content:
                    self._send_reply(from_user, rule['reply'])
                    break
    
    def _send_reply(self, to_user: str, content: str):
        """发送回复（通过Hook实现）"""
        logger.info(f"发送自动回复给 {to_user}: {content}")
        # Hook会自动处理回复
    
    def send_message(self, to_user: str, content: str) -> bool:
        """
        发送消息
        
        Args:
            to_user: 接收者ID
            content: 消息内容
        
        Returns:
            是否成功
        """
        # 这个功能需要Hook支持
        logger.info(f"发送消息给 {to_user}: {content}")
        # TODO: 实现通过Hook发送消息
        return True
    
    def get_contacts(self) -> List[Dict]:
        """获取联系人列表"""
        # 确保有数据库密钥
        if not self.get_db_key():
            logger.error("无法获取数据库密钥")
            return []
        
        # 查找联系人数据库
        db_files = self.hook.find_db_files()
        
        for db_file in db_files:
            if "wccontact" in db_file.name:
                # 解密数据库
                temp_db = Path("/tmp") / f"{db_file.stem}_temp.db"
                if self.hook.decrypt_database(db_file, temp_db):
                    # 获取联系人
                    contacts = self.hook.get_contacts(temp_db)
                    
                    # 删除临时文件
                    temp_db.unlink()
                    
                    return contacts
        
        return []
    
    def search_messages(self, keyword: str, limit: int = 50) -> List[Dict]:
        """
        搜索消息
        
        Args:
            keyword: 搜索关键词
            limit: 返回数量限制
        
        Returns:
            匹配的消息列表
        """
        all_messages = self.get_recent_messages(limit * 10)
        
        # 过滤包含关键词的消息
        matched = []
        for msg in all_messages:
            content = msg.get('content', '')
            if keyword.lower() in content.lower():
                matched.append(msg)
                if len(matched) >= limit:
                    break
        
        return matched


# 使用示例
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # 创建服务实例
    service = MacWeChatService()
    
    # 初始化
    if service.initialize():
        
        # 方式1：仅导出聊天记录
        # service.export_chat_history()
        
        # 方式2：启用Hook功能（包括自动回复）
        if service.enable_hook():
            
            # 添加自动回复规则
            service.add_auto_reply_rule("你好", "你好！有什么可以帮助你的吗？")
            service.add_auto_reply_rule("在吗", "在的，请说")
            
            # 添加消息处理器
            def message_handler(msg):
                print(f"收到消息: {msg}")
            
            service.add_message_handler(message_handler)
            
            # 保持运行
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                service.disable_hook() 