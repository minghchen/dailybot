"""
Mac WeChat Hook Service
负责与微信本地数据进行交互，包括数据库的解密和读取。
"""

import re
import os
import sqlite3
import subprocess
import logging
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
import shutil

logger = logging.getLogger(__name__)

# 定义SQLCipher的PRAGMA配置
SQLCIPHER_PRAGMA = """
PRAGMA page_size = 4096;
PRAGMA kdf_iter = 64000;
PRAGMA cipher_hmac_algorithm = HMAC_SHA1;
PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA1;
"""

class MacWeChatHook:
    """
    Mac微信数据访问服务。
    通过读取和解密本地数据库文件来获取信息。
    """

    def __init__(self):
        self.wechat_path = "/Applications/WeChat.app"
        self.db_base_path = Path.home() / "Library/Containers/com.tencent.xinWeChat/Data/Library/Application Support/com.tencent.xinWeChat"
        self.db_key = self._get_db_key_from_env()
        self.wechat_version = self._get_wechat_version()
        self.decrypted_db_path = None

    def _get_db_key_from_env(self) -> Optional[str]:
        """从环境变量获取数据库密钥"""
        key = os.getenv("WECHAT_DB_KEY")
        if not key:
            logger.error("环境变量 WECHAT_DB_KEY 未设置。")
            raise ValueError(
                "无法获取数据库密钥。请设置 'WECHAT_DB_KEY' 环境变量。"
                "获取方法请参考相关文档。"
            )
        if len(key) != 64 or not re.match(r"^[0-9a-fA-F]{64}$", key):
            logger.error("WECHAT_DB_KEY 格式不正确，应为64位十六进制字符。")
            raise ValueError("WECHAT_DB_KEY 格式错误。")

        logger.info("成功从环境变量加载数据库密钥。")
        return key

    def _get_wechat_version(self) -> Optional[str]:
        """获取微信客户端版本"""
        try:
            info_plist = Path(self.wechat_path) / "Contents/Info.plist"
            if not info_plist.exists():
                logger.warning("未找到微信Info.plist文件，无法检测版本。")
                return None
            result = subprocess.run(
                ["defaults", "read", str(info_plist), "CFBundleShortVersionString"],
                capture_output=True, text=True, check=True
            )
            version = result.stdout.strip()
            logger.info(f"检测到微信版本: {version}")
            return version
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.error(f"获取微信版本失败: {e}")
            return None

    def find_main_db_path(self, db_name: str) -> Optional[Path]:
        """
        根据用户hash和数据库名称查找主数据库文件路径。
        此函数会处理两种目录结构，并智能选择包含数据的用户目录：
        1. .../com.tencent.xinWeChat/<32位哈希>/
        2. .../com.tencent.xinWeChat/<版本号>/<32位哈希>/
        例如: find_main_db_path("msg_2.db")
        """
        search_path = None
        
        def find_valid_user_dir(path: Path) -> Optional[Path]:
            """在指定路径下查找有效的用户哈希目录"""
            hash_dirs = [d for d in path.iterdir() if d.is_dir() and len(d.name) == 32]
            for h_dir in hash_dirs:
                # 检查是否存在Message或Contact文件夹，作为有效目录的标志
                if (h_dir / "Message").exists() or (h_dir / "Contact").exists():
                    logger.info(f"在 {path} 中找到有效的用户哈希目录: {h_dir.name}")
                    return h_dir
            return None

        # 首先，尝试直接在基础路径下查找 (旧版微信结构)
        search_path = find_valid_user_dir(self.db_base_path)

        # 如果直接找不到，则遍历子目录 (新版微信结构)
        if not search_path:
            logger.info(f"在 {self.db_base_path} 下未直接找到有效哈希目录，将搜索子目录...")
            for subdir in self.db_base_path.iterdir():
                if subdir.is_dir():
                    search_path = find_valid_user_dir(subdir)
                    if search_path:
                        break  # 找到后即停止

        if not search_path:
            logger.error("在任何路径下都未找到有效的用户数据目录 (包含Message/Contact子文件夹的32位哈希目录)。")
            return None

        # 使用找到的有效用户数据路径
        user_data_path = search_path
        
        # 查找匹配的数据库文件
        potential_paths = [
            user_data_path / "Message" / db_name,
            user_data_path / "Contact" / db_name,
        ]

        for db_path in potential_paths:
            if db_path.exists():
                logger.info(f"找到数据库文件: {db_path}")
                return db_path
        
        # 找不到特定db是正常情况，例如不是每个用户都有msg_4.db
        # logger.warning(f"在 {user_data_path} 中未找到数据库 {db_name} (这可能是正常的)。")
        return None

    def decrypt_database(self, db_path: Path, force_decrypt: bool = False) -> Optional[Path]:
        """
        使用sqlcipher解密数据库文件。
        如果已存在解密后的副本且源文件未更新，则直接返回路径。
        """
        if not self.db_key:
            return None
        
        decrypted_db_dir = Path.home() / ".dailybot/decrypted_db"
        decrypted_db_dir.mkdir(parents=True, exist_ok=True)
        decrypted_path = decrypted_db_dir / f"{db_path.name}.decrypted"

        # 检查是否需要重新解密
        if not force_decrypt and decrypted_path.exists():
            original_mtime = db_path.stat().st_mtime
            decrypted_mtime = decrypted_path.stat().st_mtime
            if decrypted_mtime > original_mtime:
                logger.info(f"使用已存在的解密数据库: {decrypted_path}")
                return decrypted_path

        logger.info(f"正在解密数据库 {db_path} 到 {decrypted_path}...")
        
        try:
            # 使用sqlcipher命令行工具进行解密
            # 需要用户系统预先安装sqlcipher
            if not shutil.which("sqlcipher"):
                logger.error("系统未安装 'sqlcipher'。请使用 'brew install sqlcipher' 安装。")
                raise FileNotFoundError("sqlcipher not found")

            # 先复制一份，避免直接操作加密数据库
            temp_encrypted_path = decrypted_db_dir / f"{db_path.name}.temp_encrypted"
            shutil.copy2(db_path, temp_encrypted_path)

            command = f"""
PRAGMA key = "x'{self.db_key}'";
{SQLCIPHER_PRAGMA}
ATTACH DATABASE '{decrypted_path}' AS plaintext KEY '';
SELECT sqlcipher_export('plaintext');
DETACH DATABASE plaintext;
"""
            process = subprocess.run(
                ["sqlcipher", str(temp_encrypted_path)],
                input=command,
                capture_output=True, text=True
            )
            
            # 清理临时加密文件
            temp_encrypted_path.unlink()

            if process.returncode != 0 or "Error" in process.stderr:
                logger.error(f"数据库解密失败: {process.stderr}")
                if decrypted_path.exists():
                    decrypted_path.unlink() # 删除不完整的解密文件
                return None

            if not decrypted_path.exists() or decrypted_path.stat().st_size == 0:
                 logger.error("数据库解密后文件为空或不存在。")
                 return None

            logger.info("数据库解密成功。")
            return decrypted_path

        except (subprocess.CalledProcessError, FileNotFoundError, Exception) as e:
            logger.error(f"解密数据库时发生严重错误: {e}")
            return None

    def _execute_query(self, decrypted_db_path: Path, query: str, params=()) -> List:
        """在解密的数据库上执行查询"""
        try:
            with sqlite3.connect(decrypted_db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                return cursor.fetchall()
        except sqlite3.Error as e:
            logger.error(f"数据库查询失败: {e} in query: {query}")
            return []

    def get_chat_messages(self, decrypted_db_path: Path, last_check_time: int = 0, limit: int = 100) -> List[Dict]:
        """
        从解密的数据库获取聊天记录。
        """
        messages = []
        
        tables_query = "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Chat_%'"
        tables = self._execute_query(decrypted_db_path, tables_query)

        for table in tables:
            table_name = table[0]
            # 群聊ID通常是 @chatroom 后缀
            is_group = "@chatroom" in table_name

            query = f"""
            SELECT
                CreateTime,
                Message,
                Status,
                MsgSvrID,
                MesLocalID,
                MsgSource
            FROM {table_name}
            WHERE CreateTime > ?
            ORDER BY CreateTime DESC
            LIMIT ?
            """
            
            rows = self._execute_query(decrypted_db_path, query, (last_check_time, limit))

            for row in reversed(rows): # 按时间升序处理
                content = row[1]
                sender = None

                if is_group and content and '<sysmsg' not in content:
                    # 解析群聊中的发言人
                    # 格式: wxid_xxxx:\n{content}
                    match = re.match(r"^(wxid_[a-zA-Z0-9]+):\n", content)
                    if match:
                        sender = match.group(1)
                        content = content[match.end():]
                
                messages.append({
                    'create_time': row[0],
                    'content': content,
                    'status': row[2],
                    'msg_id': row[3] or row[4],
                    'room_id': table_name.replace("Chat_", ""),
                    'sender_id': sender,
                    'is_group': is_group,
                })
        
        messages.sort(key=lambda x: x['create_time'])
        return messages

    def get_contacts(self, decrypted_db_path: Path) -> List[Dict]:
        """获取联系人信息"""
        query = """
        SELECT
            UserName,
            NickName,
            Remark,
            Type,
            DBContactChatRoom,
            DBContactRemark
        FROM WCContact
        WHERE Type IN (2, 3) OR (Type = 0 AND UserName LIKE 'gh_%') -- 2:群聊, 3:好友, 0:公众号
        """
        
        rows = self._execute_query(decrypted_db_path, query)
        contacts = []
        for row in rows:
            user_type = "unknown"
            if row[3] == 3:
                user_type = "friend"
            elif row[3] == 2:
                user_type = "group"
            elif row[0].startswith("gh_"):
                user_type = "official_account"

            contacts.append({
                'user_id': row[0],
                'nickname': row[1],
                'remark': row[2] or row[5], # remark字段可能为空，DBContactRemark是备用
                'type': user_type,
            })
        
        return contacts

# 测试代码
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    try:
        hook = MacWeChatHook()
        
        # 查找消息数据库
        msg_db_path = hook.find_main_db_path("msg_2.db") # 通常是msg_2.db或msg_3.db
        if msg_db_path:
            # 解密
            decrypted_msg_db = hook.decrypt_database(msg_db_path)
            
            if decrypted_msg_db:
                print(f"数据库解密成功: {decrypted_msg_db}")
                
                # 获取最近10条消息
                ten_seconds_ago = int(datetime.now().timestamp()) - 1000000
                messages = hook.get_chat_messages(decrypted_msg_db, last_check_time=ten_seconds_ago, limit=10)
                print("\n--- 最近消息 ---")
                for msg in messages:
                    print(f"[{datetime.fromtimestamp(msg['create_time'])}] From: {msg['room_id']}"
                          f" Sender: {msg.get('sender_id', 'N/A')}\n  Content: {msg['content'][:50]}...")

        # 查找联系人数据库
        contact_db_path = hook.find_main_db_path("wccontact_new2.db")
        if contact_db_path:
            decrypted_contact_db = hook.decrypt_database(contact_db_path)
            if decrypted_contact_db:
                print(f"\n联系人数据库解密成功: {decrypted_contact_db}")
                contacts = hook.get_contacts(decrypted_contact_db)
                print("\n--- 部分联系人 ---")
                for contact in contacts[:5]:
                    print(f"ID: {contact['user_id']}, Nick: {contact['nickname']}, Remark: {contact['remark']}, Type: {contact['type']}")

    except (ValueError, FileNotFoundError) as e:
        logger.error(f"启动测试失败: {e}")

"""
Changes:
- Removed `get_db_key_lldb` and replaced with `_get_db_key_from_env`.
- `__init__` now validates the key from the environment.
- Added `_get_wechat_version`.
- Rewritten `find_main_db_path` to handle both old and new WeChat directory structures and correctly select the user data folder.
- Completely rewrote `decrypt_database` to be more robust, efficient (avoids re-decrypting), and safer (checks for `sqlcipher` tool, copies db before decrypting).
- Rewritten `get_chat_messages` to accept `last_check_time`, filter in SQL, correctly parse group chat sender from message content, and return a more structured dictionary.
- Rewritten `get_contacts` to return more structured data.
- Added a `_execute_query` helper for cleaner code.
- Updated main test block to reflect new methods.
"""
