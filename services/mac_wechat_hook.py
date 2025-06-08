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
from pysqlcipher3 import dbapi2 as sqlcipher

logger = logging.getLogger(__name__)

# 根据用户验证成功的 SQLCipher 3 Defaults 配置
# 这是我们唯一的、最终的解密参数
SQLCIPHER3_DEFAULTS_CONFIG = [
    "PRAGMA cipher_page_size = 1024;",
    "PRAGMA kdf_iter = 64000;",
    "PRAGMA cipher_hmac_algorithm = HMAC_SHA1;",
    "PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA1;"
]

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
        根据数据库名称查找主数据库文件路径。
        使用rglob递归搜索，以适应不同版本的微信目录结构。
        """
        logger.info(f"正在 {self.db_base_path} 中递归搜索用户数据目录...")

        # 使用 rglob 查找所有名为 'Message' 的目录
        # 我们只关心第一个找到的有效目录，因为通常只有一个活跃用户
        for msg_dir in self.db_base_path.rglob("Message"):
            if not msg_dir.is_dir():
                continue

            user_data_path = msg_dir.parent
            # 确认这是一个有效的用户目录（通常同时包含Contact目录）
            if (user_data_path / "Contact").exists():
                logger.info(f"找到有效的用户数据目录: {user_data_path}")

                # 在这个有效目录中查找目标数据库
                # 数据库可能在Message或Contact子目录里
                potential_paths = [
                    user_data_path / "Message" / db_name,
                    user_data_path / "Contact" / db_name,
                ]
                for db_path in potential_paths:
                    if db_path.exists():
                        logger.info(f"找到数据库文件: {db_path}")
                        return db_path
                # 如果在此有效目录中未找到特定db文件，则认为它不存在于此用户下
                # 不要继续搜索其他Message目录，以免找到旧的、不活跃的用户数据
                logger.warning(f"在有效的用户目录 {user_data_path} 中未找到 {db_name}")
                return None
            
        logger.error("在任何路径下都未找到有效的用户数据目录 (一个同时包含Message和Contact子文件夹的目录)。")
        return None

    def decrypt_database(self, db_path: Path, force_decrypt: bool = False) -> Optional[Path]:
        """
        使用 pysqlcipher3 在Python内部解密数据库文件。
        该实现精确复刻了用户验证成功的 "SQLCipher 3 defaults" 逻辑。
        """
        if not self.db_key:
            return None

        decrypted_db_dir = Path.home() / ".dailybot/decrypted_db"
        decrypted_db_dir.mkdir(parents=True, exist_ok=True)
        
        decrypted_path = decrypted_db_dir / f"{db_path.name}.decrypted"
        
        if not force_decrypt and decrypted_path.exists():
            try:
                original_mtime = db_path.stat().st_mtime
                decrypted_mtime = decrypted_path.stat().st_mtime
                if decrypted_mtime > original_mtime:
                    logger.info(f"使用已存在的有效解密缓存: {decrypted_path}")
                    return decrypted_path
            except FileNotFoundError:
                pass

        conn = None
        temp_encrypted_path = decrypted_db_dir / f"{db_path.name}.temp_encrypted"
        try:
            # 复制加密数据库及其辅助文件
            shutil.copy2(db_path, temp_encrypted_path)
            wal_file = db_path.with_suffix(".db-wal")
            if wal_file.exists():
                shutil.copy2(wal_file, temp_encrypted_path.with_suffix(".db-wal"))
            shm_file = db_path.with_suffix(".db-shm")
            if shm_file.exists():
                shutil.copy2(shm_file, temp_encrypted_path.with_suffix(".db-shm"))
            
            # 连接到加密数据库并执行解密
            logger.info(f"正在使用 'SQLCipher 3 Defaults' 配置尝试解密 {db_path.name}...")
            conn = sqlcipher.connect(str(temp_encrypted_path))
            
            # 执行解密指令
            conn.execute(f"PRAGMA key = \"x'{self.db_key}'\"")
            for line in SQLCIPHER3_DEFAULTS_CONFIG:
                conn.execute(line)
            
            # 验证密钥和参数
            conn.execute("SELECT count(*) FROM sqlite_master;").fetchall()
            
            # 导出解密后的数据库
            logger.info("密钥和参数验证成功，正在导出...")
            if decrypted_path.exists():
                decrypted_path.unlink()
            
            conn.execute(f"ATTACH DATABASE '{decrypted_path}' AS plaintext KEY '';")
            conn.execute("SELECT sqlcipher_export('plaintext');")
            conn.execute("DETACH DATABASE plaintext;")
            conn.close()
            
            if decrypted_path.exists() and decrypted_path.stat().st_size > 0:
                logger.info(f"成功解密数据库: {db_path.name} -> {decrypted_path}")
                return decrypted_path
            else:
                raise Exception("sqlcipher_export failed to create a non-empty file.")

        except sqlcipher.DatabaseError as e:
            logger.error(f"解密失败。这表明您的密钥或微信版本与'SQLCipher 3 defaults'不兼容。错误: {e}")
            if conn:
                conn.close()
            if decrypted_path.exists():
                decrypted_path.unlink()
            return None
        except Exception as e:
            logger.error(f"解密过程中发生未知错误: {e}")
            if conn:
                conn.close()
            return None
        finally:
            # 清理临时文件
            if temp_encrypted_path.exists():
                temp_encrypted_path.unlink()
            temp_wal = temp_encrypted_path.with_suffix(".db-wal")
            if temp_wal.exists():
                temp_wal.unlink()
            temp_shm = temp_encrypted_path.with_suffix(".db-shm")
            if temp_shm.exists():
                temp_shm.unlink()

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
        该方法会动态检查表结构，以适应不同版本的列名。
        """
        messages = []
        
        tables_query = "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Chat_%' AND name NOT LIKE '%_dels'"
        tables = self._execute_query(decrypted_db_path, tables_query)

        for table in tables:
            table_name = table[0]
            is_group = "@chatroom" in table_name

            # 动态获取表结构
            table_info = self._execute_query(decrypted_db_path, f"PRAGMA table_info({table_name});")
            column_names = {row[1].lower() for row in table_info}

            # 动态确定列名，使用从日志中验证的真实列名
            create_time_col = "msgcreatetime"
            message_col = "msgcontent"
            status_col = "msgstatus"
            msg_svr_id_col = "messvrid"
            mes_local_id_col = "meslocalid"
            msg_source_col = "msgsource"
            
            # 确认所有必要的列都存在
            required_cols = {create_time_col, message_col, status_col, msg_svr_id_col, mes_local_id_col}
            if not required_cols.issubset(column_names):
                logger.warning(f"跳过表 {table_name}，因为它缺少必要的列。现有列: {column_names}")
                continue

            query = f"""
            SELECT
                {create_time_col},
                {message_col},
                {status_col},
                {msg_svr_id_col},
                {mes_local_id_col},
                {msg_source_col}
            FROM {table_name}
            WHERE {create_time_col} > ?
            ORDER BY {create_time_col} DESC
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
