"""
Mac WeChat Hook Service
用于从Mac微信获取聊天记录和实现自动回复功能
参考了 WeChatTweak-macOS 和其他开源项目
"""

import re
import os
import sys
import json
import sqlite3
import subprocess
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import hashlib
import struct

# 设置日志
logger = logging.getLogger(__name__)


class MacWeChatHook:
    """Mac微信Hook服务，用于获取聊天记录和实现自动回复"""
    
    def __init__(self):
        self.wechat_path = "/Applications/WeChat.app"
        self.db_base_path = Path.home() / "Library/Containers/com.tencent.xinWeChat/Data"
        self.db_key = None
        self.wechat_version = None
        self.is_hooked = False
        
    def check_wechat_version(self) -> str:
        """检查微信版本"""
        try:
            info_plist = f"{self.wechat_path}/Contents/Info.plist"
            result = subprocess.run(
                ["defaults", "read", info_plist, "CFBundleShortVersionString"],
                capture_output=True, text=True
            )
            self.wechat_version = result.stdout.strip()
            logger.info(f"检测到微信版本: {self.wechat_version}")
            return self.wechat_version
        except Exception as e:
            logger.error(f"获取微信版本失败: {e}")
            return None
    
    def get_db_key_lldb(self) -> Optional[str]:
        """使用LLDB获取数据库密钥"""
        logger.info("尝试使用LLDB获取数据库密钥...")
        
        # 创建LLDB脚本
        lldb_script = """
import lldb
import re

def get_db_key(debugger, command, result, internal_dict):
    target = debugger.GetSelectedTarget()
    process = target.GetProcess()
    
    # 设置断点
    breakpoint = target.BreakpointCreateByName('sqlite3_key')
    if not breakpoint.IsValid():
        print("Failed to set breakpoint")
        return
    
    # 继续执行
    process.Continue()
    
    # 等待断点触发
    thread = process.GetSelectedThread()
    frame = thread.GetSelectedFrame()
    
    # 读取密钥
    rsi = frame.FindRegister("rsi")
    if rsi:
        error = lldb.SBError()
        key_data = process.ReadMemory(rsi.GetValueAsUnsigned(), 32, error)
        if error.Success():
            key_hex = ''.join(f'{b:02x}' for b in key_data)
            print(f"DB_KEY: {key_hex}")
    
def __lldb_init_module(debugger, internal_dict):
    debugger.HandleCommand('command script add -f get_db_key.get_db_key get_db_key')
"""
        
        # 保存脚本
        script_path = "/tmp/wechat_lldb_script.py"
        with open(script_path, 'w') as f:
            f.write(lldb_script)
        
        try:
            # 获取微信进程ID
            result = subprocess.run(
                ["pgrep", "WeChat"],
                capture_output=True, text=True
            )
            pid = result.stdout.strip()
            
            if not pid:
                logger.error("未找到微信进程")
                return None
            
            # 使用LLDB附加进程
            lldb_commands = f"""
attach {pid}
command script import {script_path}
get_db_key
detach
quit
"""
            
            process = subprocess.Popen(
                ["lldb"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            output, error = process.communicate(input=lldb_commands)
            
            # 解析输出获取密钥
            match = re.search(r'DB_KEY: ([0-9a-fA-F]{64})', output)
            if match:
                self.db_key = match.group(1)
                logger.info("成功获取数据库密钥")
                return self.db_key
            
        except Exception as e:
            logger.error(f"LLDB获取密钥失败: {e}")
        
        return None
    
    def find_db_files(self) -> List[Path]:
        """查找微信数据库文件"""
        db_files = []
        
        try:
            # 查找聊天记录数据库
            msg_db_pattern = "*/Message/msg_*.db"
            for db_path in self.db_base_path.rglob(msg_db_pattern):
                db_files.append(db_path)
            
            # 查找联系人数据库
            contact_db = self.db_base_path / "Library/Application Support/com.tencent.xinWeChat"
            for db_path in contact_db.rglob("*/Contact/wccontact_new2.db"):
                db_files.append(db_path)
            
            # 查找收藏数据库
            for db_path in self.db_base_path.rglob("*/Favorites/favorites.db"):
                db_files.append(db_path)
                
            logger.info(f"找到 {len(db_files)} 个数据库文件")
            return db_files
            
        except Exception as e:
            logger.error(f"查找数据库文件失败: {e}")
            return []
    
    def decrypt_database(self, db_path: Path, output_path: Path = None) -> bool:
        """解密数据库文件"""
        if not self.db_key:
            logger.error("未获取到数据库密钥")
            return False
        
        try:
            # 使用sqlcipher解密
            if output_path is None:
                output_path = db_path.with_suffix('.decrypted.db')
            
            # 构建sqlcipher命令
            commands = f"""
PRAGMA key = "x'{self.db_key}'";
PRAGMA cipher_page_size = 4096;
PRAGMA kdf_iter = 64000;
PRAGMA cipher_hmac_algorithm = HMAC_SHA256;
PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA256;
ATTACH DATABASE '{output_path}' AS plaintext KEY '';
SELECT sqlcipher_export('plaintext');
DETACH DATABASE plaintext;
"""
            
            # 执行解密
            process = subprocess.Popen(
                ["sqlcipher", str(db_path)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            output, error = process.communicate(input=commands)
            
            if output_path.exists():
                logger.info(f"数据库解密成功: {output_path}")
                return True
            else:
                logger.error(f"数据库解密失败: {error}")
                return False
                
        except Exception as e:
            logger.error(f"解密数据库时出错: {e}")
            return False
    
    def get_chat_messages(self, db_path: Path, limit: int = 100) -> List[Dict]:
        """从解密的数据库获取聊天记录"""
        messages = []
        
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            
            # 查询消息表结构
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Chat_%'")
            tables = cursor.fetchall()
            
            for table in tables:
                table_name = table[0]
                
                # 获取聊天记录
                query = f"""
                SELECT 
                    msgCreateTime,
                    msgContent,
                    msgStatus,
                    msgImgStatus,
                    messageType,
                    msgSource
                FROM {table_name}
                ORDER BY msgCreateTime DESC
                LIMIT ?
                """
                
                cursor.execute(query, (limit,))
                rows = cursor.fetchall()
                
                for row in rows:
                    message = {
                        'timestamp': datetime.fromtimestamp(row[0]).isoformat(),
                        'content': row[1],
                        'status': row[2],
                        'type': row[4],
                        'source': row[5],
                        'table': table_name
                    }
                    messages.append(message)
            
            conn.close()
            logger.info(f"获取了 {len(messages)} 条消息")
            return messages
            
        except Exception as e:
            logger.error(f"获取聊天记录失败: {e}")
            return []
    
    def get_contacts(self, db_path: Path) -> List[Dict]:
        """获取联系人信息"""
        contacts = []
        
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            
            # 查询联系人
            query = """
            SELECT 
                userName,
                nickName,
                remarkName,
                mobile,
                email,
                type
            FROM WCContact
            WHERE type IN (1, 3)  -- 1: 好友, 3: 群聊
            """
            
            cursor.execute(query)
            rows = cursor.fetchall()
            
            for row in rows:
                contact = {
                    'username': row[0],
                    'nickname': row[1],
                    'remark': row[2],
                    'mobile': row[3],
                    'email': row[4],
                    'type': 'friend' if row[5] == 1 else 'group'
                }
                contacts.append(contact)
            
            conn.close()
            logger.info(f"获取了 {len(contacts)} 个联系人")
            return contacts
            
        except Exception as e:
            logger.error(f"获取联系人失败: {e}")
            return []
    
    def export_chat_history(self, output_dir: str = "./wechat_export"):
        """导出聊天记录"""
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)
        
        # 获取数据库密钥
        if not self.db_key:
            self.get_db_key_lldb()
        
        if not self.db_key:
            logger.error("无法获取数据库密钥，导出失败")
            return False
        
        # 查找并解密数据库
        db_files = self.find_db_files()
        
        for db_file in db_files:
            logger.info(f"处理数据库: {db_file}")
            
            # 解密数据库
            decrypted_db = output_path / f"{db_file.stem}_decrypted.db"
            if self.decrypt_database(db_file, decrypted_db):
                
                # 根据数据库类型导出数据
                if "msg_" in db_file.name:
                    # 导出聊天记录
                    messages = self.get_chat_messages(decrypted_db)
                    output_file = output_path / f"{db_file.stem}_messages.json"
                    with open(output_file, 'w', encoding='utf-8') as f:
                        json.dump(messages, f, ensure_ascii=False, indent=2)
                    logger.info(f"导出聊天记录到: {output_file}")
                    
                elif "wccontact" in db_file.name:
                    # 导出联系人
                    contacts = self.get_contacts(decrypted_db)
                    output_file = output_path / "contacts.json"
                    with open(output_file, 'w', encoding='utf-8') as f:
                        json.dump(contacts, f, ensure_ascii=False, indent=2)
                    logger.info(f"导出联系人到: {output_file}")
        
        return True


# 测试代码
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    hook = MacWeChatHook()
    hook.check_wechat_version()
    hook.export_chat_history() 