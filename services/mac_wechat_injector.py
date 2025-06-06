"""
Mac WeChat Injector
用于将动态库注入到微信进程中实现Hook功能
"""

import os
import subprocess
import logging
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class MacWeChatInjector:
    """微信进程注入器"""
    
    def __init__(self):
        self.wechat_path = "/Applications/WeChat.app/Contents/MacOS/WeChat"
        self.dylib_path = None
        self.backup_path = None
        
    def create_hook_dylib(self) -> Optional[str]:
        """创建Hook动态库"""
        
        # Objective-C Hook代码
        hook_code = '''
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#import <objc/message.h>

// 日志宏
#define WCLog(fmt, ...) NSLog(@"[WeChatHook] " fmt, ##__VA_ARGS__)

@interface WeChatHookManager : NSObject
+ (instancetype)sharedManager;
- (void)startHook;
@end

@implementation WeChatHookManager

+ (instancetype)sharedManager {
    static WeChatHookManager *manager = nil;
    static dispatch_once_t onceToken;
    dispatch_once(&onceToken, ^{
        manager = [[WeChatHookManager alloc] init];
    });
    return manager;
}

- (void)startHook {
    WCLog(@"Starting WeChat Hook...");
    
    // Hook消息接收
    [self hookMessageReceive];
    
    // Hook消息发送
    [self hookMessageSend];
    
    // Hook数据库操作
    [self hookDatabase];
}

- (void)hookMessageReceive {
    // Hook消息接收方法
    Class messageServiceClass = NSClassFromString(@"MessageService");
    if (!messageServiceClass) {
        WCLog(@"MessageService class not found");
        return;
    }
    
    SEL originalSelector = @selector(onRecvMessage:);
    SEL swizzledSelector = @selector(hook_onRecvMessage:);
    
    Method originalMethod = class_getInstanceMethod(messageServiceClass, originalSelector);
    Method swizzledMethod = class_getInstanceMethod([self class], swizzledSelector);
    
    if (originalMethod && swizzledMethod) {
        method_exchangeImplementations(originalMethod, swizzledMethod);
        WCLog(@"Successfully hooked message receive");
    }
}

- (void)hook_onRecvMessage:(id)message {
    // 调用原始方法
    [self hook_onRecvMessage:message];
    
    // 处理消息
    @try {
        NSString *content = [message valueForKey:@"msgContent"];
        NSString *fromUser = [message valueForKey:@"fromUsrName"];
        NSNumber *msgType = [message valueForKey:@"messageType"];
        
        WCLog(@"Received message from %@: %@", fromUser, content);
        
        // 自动回复逻辑
        if ([self shouldAutoReply:message]) {
            [self performAutoReply:fromUser content:content];
        }
        
        // 保存消息到文件
        [self saveMessageToFile:@{
            @"from": fromUser ?: @"",
            @"content": content ?: @"",
            @"type": msgType ?: @0,
            @"timestamp": @([[NSDate date] timeIntervalSince1970])
        }];
        
    } @catch (NSException *exception) {
        WCLog(@"Error processing message: %@", exception);
    }
}

- (void)hookMessageSend {
    // Hook发送消息方法
    Class messageSenderClass = NSClassFromString(@"MessageSender");
    if (!messageSenderClass) {
        WCLog(@"MessageSender class not found");
        return;
    }
    
    SEL originalSelector = @selector(SendTextMessage:toUsrName:msgSource:);
    SEL swizzledSelector = @selector(hook_SendTextMessage:toUsrName:msgSource:);
    
    Method originalMethod = class_getInstanceMethod(messageSenderClass, originalSelector);
    Method swizzledMethod = class_getInstanceMethod([self class], swizzledSelector);
    
    if (originalMethod && swizzledMethod) {
        method_exchangeImplementations(originalMethod, swizzledMethod);
        WCLog(@"Successfully hooked message send");
    }
}

- (void)hook_SendTextMessage:(NSString *)content toUsrName:(NSString *)userName msgSource:(int)source {
    WCLog(@"Sending message to %@: %@", userName, content);
    
    // 调用原始方法
    [self hook_SendTextMessage:content toUsrName:userName msgSource:source];
}

- (void)hookDatabase {
    // Hook数据库相关方法
    Class databaseClass = NSClassFromString(@"WCTDatabase");
    if (!databaseClass) {
        WCLog(@"WCTDatabase class not found");
        return;
    }
    
    SEL originalSelector = @selector(setCipherKey:);
    SEL swizzledSelector = @selector(hook_setCipherKey:);
    
    Method originalMethod = class_getInstanceMethod(databaseClass, originalSelector);
    Method swizzledMethod = class_getInstanceMethod([self class], swizzledSelector);
    
    if (originalMethod && swizzledMethod) {
        method_exchangeImplementations(originalMethod, swizzledMethod);
        WCLog(@"Successfully hooked database");
    }
}

- (void)hook_setCipherKey:(NSData *)cipherKey {
    WCLog(@"Database cipher key captured: %@", [cipherKey description]);
    
    // 保存密钥
    [self saveCipherKey:cipherKey];
    
    // 调用原始方法
    [self hook_setCipherKey:cipherKey];
}

- (BOOL)shouldAutoReply:(id)message {
    // 自动回复判断逻辑
    NSString *content = [message valueForKey:@"msgContent"];
    if (!content) return NO;
    
    // 关键词匹配
    NSArray *keywords = @[@"你好", @"在吗", @"hello"];
    for (NSString *keyword in keywords) {
        if ([content.lowercaseString containsString:keyword.lowercaseString]) {
            return YES;
        }
    }
    
    return NO;
}

- (void)performAutoReply:(NSString *)toUser content:(NSString *)originalContent {
    // 延迟1-3秒回复
    double delayInSeconds = 1.0 + (arc4random_uniform(2000) / 1000.0);
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(delayInSeconds * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
        
        NSString *replyContent = [self generateReplyContent:originalContent];
        
        // 获取消息发送器
        Class messageSenderClass = NSClassFromString(@"MessageSender");
        id sender = [messageSenderClass performSelector:@selector(sharedInstance)];
        
        if (sender) {
            SEL sendSelector = @selector(SendTextMessage:toUsrName:msgSource:);
            if ([sender respondsToSelector:sendSelector]) {
                ((void (*)(id, SEL, NSString *, NSString *, int))objc_msgSend)
                    (sender, sendSelector, replyContent, toUser, 0);
                WCLog(@"Auto reply sent to %@", toUser);
            }
        }
    });
}

- (NSString *)generateReplyContent:(NSString *)originalContent {
    // 简单的回复生成逻辑
    if ([originalContent containsString:@"你好"]) {
        return @"你好！我现在有事不在，稍后回复你。";
    } else if ([originalContent containsString:@"在吗"]) {
        return @"在的，请问有什么事吗？";
    } else {
        return @"收到你的消息了，我会尽快回复。";
    }
}

- (void)saveMessageToFile:(NSDictionary *)messageData {
    NSString *documentsPath = NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES)[0];
    NSString *logPath = [documentsPath stringByAppendingPathComponent:@"wechat_messages.json"];
    
    NSMutableArray *messages = [NSMutableArray array];
    
    // 读取现有消息
    if ([[NSFileManager defaultManager] fileExistsAtPath:logPath]) {
        NSData *data = [NSData dataWithContentsOfFile:logPath];
        NSArray *existingMessages = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
        if (existingMessages) {
            [messages addObjectsFromArray:existingMessages];
        }
    }
    
    // 添加新消息
    [messages addObject:messageData];
    
    // 保存
    NSData *jsonData = [NSJSONSerialization dataWithJSONObject:messages options:NSJSONWritingPrettyPrinted error:nil];
    [jsonData writeToFile:logPath atomically:YES];
}

- (void)saveCipherKey:(NSData *)keyData {
    NSString *documentsPath = NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES)[0];
    NSString *keyPath = [documentsPath stringByAppendingPathComponent:@"wechat_db_key.txt"];
    
    NSString *keyHex = [self hexStringFromData:keyData];
    [keyHex writeToFile:keyPath atomically:YES encoding:NSUTF8StringEncoding error:nil];
    
    WCLog(@"Database key saved to: %@", keyPath);
}

- (NSString *)hexStringFromData:(NSData *)data {
    const unsigned char *bytes = (const unsigned char *)data.bytes;
    NSMutableString *hex = [NSMutableString stringWithCapacity:data.length * 2];
    for (NSUInteger i = 0; i < data.length; i++) {
        [hex appendFormat:@"%02x", bytes[i]];
    }
    return hex;
}

@end

// 构造函数，动态库加载时自动执行
__attribute__((constructor))
static void WeChatHookInitialize() {
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(1.0 * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
        [[WeChatHookManager sharedManager] startHook];
    });
}
'''
        
        try:
            # 创建临时目录
            temp_dir = tempfile.mkdtemp()
            
            # 写入源代码
            source_file = os.path.join(temp_dir, "WeChatHook.m")
            with open(source_file, 'w') as f:
                f.write(hook_code)
            
            # 编译动态库
            dylib_file = os.path.join(temp_dir, "WeChatHook.dylib")
            compile_cmd = [
                "clang",
                "-dynamiclib",
                "-framework", "Foundation",
                "-framework", "AppKit",
                "-arch", "x86_64",
                "-arch", "arm64",
                "-fobjc-arc",
                "-o", dylib_file,
                source_file
            ]
            
            result = subprocess.run(compile_cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                logger.info(f"成功创建Hook动态库: {dylib_file}")
                self.dylib_path = dylib_file
                return dylib_file
            else:
                logger.error(f"编译失败: {result.stderr}")
                return None
                
        except Exception as e:
            logger.error(f"创建动态库失败: {e}")
            return None
    
    def inject_dylib(self) -> bool:
        """注入动态库到微信"""
        if not self.dylib_path:
            logger.error("动态库未创建")
            return False
        
        try:
            # 备份原始微信
            self.backup_path = f"{self.wechat_path}.backup"
            if not os.path.exists(self.backup_path):
                subprocess.run(["cp", self.wechat_path, self.backup_path])
                logger.info("已备份原始微信")
            
            # 使用insert_dylib注入
            # 需要先安装insert_dylib工具
            inject_cmd = [
                "insert_dylib",
                "--strip-codesig",
                "--all-yes",
                self.dylib_path,
                self.wechat_path,
                self.wechat_path
            ]
            
            result = subprocess.run(inject_cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                logger.info("成功注入动态库")
                
                # 重新签名
                codesign_cmd = ["codesign", "-f", "-s", "-", self.wechat_path]
                subprocess.run(codesign_cmd)
                
                return True
            else:
                logger.error(f"注入失败: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"注入过程出错: {e}")
            return False
    
    def restore_wechat(self) -> bool:
        """恢复原始微信"""
        if not self.backup_path or not os.path.exists(self.backup_path):
            logger.error("未找到备份文件")
            return False
        
        try:
            subprocess.run(["cp", self.backup_path, self.wechat_path])
            logger.info("已恢复原始微信")
            return True
        except Exception as e:
            logger.error(f"恢复失败: {e}")
            return False
    
    def check_insert_dylib(self) -> bool:
        """检查是否安装了insert_dylib工具"""
        try:
            result = subprocess.run(["which", "insert_dylib"], capture_output=True)
            return result.returncode == 0
        except:
            return False
    
    def install_insert_dylib(self):
        """安装insert_dylib工具"""
        logger.info("正在安装insert_dylib工具...")
        
        # 下载并编译insert_dylib
        commands = [
            "git clone https://github.com/Tyilo/insert_dylib.git /tmp/insert_dylib",
            "cd /tmp/insert_dylib && make",
            "sudo cp /tmp/insert_dylib/insert_dylib /usr/local/bin/"
        ]
        
        for cmd in commands:
            subprocess.run(cmd, shell=True)
        
        logger.info("insert_dylib安装完成")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    injector = MacWeChatInjector()
    
    # 检查工具
    if not injector.check_insert_dylib():
        injector.install_insert_dylib()
    
    # 创建并注入动态库
    if injector.create_hook_dylib():
        injector.inject_dylib() 