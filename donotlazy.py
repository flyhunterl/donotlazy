# encoding:utf-8

import os
import json
import sqlite3
from datetime import datetime, timedelta
import plugins
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_message import ChatMessage
from common.log import logger
from plugins import *
from config import conf


@plugins.register(
    name="donotlazy",
    desire_priority=90,
    hidden=True,
    desc="记录群消息已读情况",
    version="0.1",
    author="wangcl",
)
class DoNotLazy(Plugin):
    def __init__(self):
        super().__init__()
        try:
            logger.info(f"[donotlazy] 开始初始化插件")
            self.curdir = os.path.dirname(__file__)
            logger.info(f"[donotlazy] 插件目录: {self.curdir}")
            
            # 加载配置
            self.config = super().load_config()
            logger.info(f"[donotlazy] 加载配置结果: {self.config}")
            
            if not self.config:
                logger.warning("[donotlazy] 未找到配置文件，使用默认配置")
                self.config = {
                    "max_record_days": 7,
                    "read_keyword": "已读",
                    "class_name": "3班",
                    "student_file": "students.json"
                }
            
            self.max_record_days = self.config.get("max_record_days", 7)
            self.read_keyword = self.config.get("read_keyword", "已读")
            self.class_name = self.config.get("class_name", "3班")
            self.student_file = self.config.get("student_file", "students.json")
            
            logger.info(f"[donotlazy] 配置: max_record_days={self.max_record_days}, read_keyword={self.read_keyword}, class_name={self.class_name}, student_file={self.student_file}")
            
            # 加载学生名单
            self.students = self.load_students()
            
            # 初始化数据库
            self.db_path = os.path.join(self.curdir, "read_records.db")
            logger.info(f"[donotlazy] 数据库路径: {self.db_path}")
            self.init_database()
            
            logger.info(f"[donotlazy] 插件初始化成功，已加载 {len(self.students)} 名学生")
            self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
            self.handlers[Event.ON_RECEIVE_MESSAGE] = self.on_receive_message
            
        except Exception as e:
            logger.error(f"[donotlazy] 初始化异常：{e}")
            raise f"[donotlazy] 初始化失败，忽略插件: {e}"
    
    def load_students(self):
        """加载学生名单"""
        students = {}
        try:
            # 尝试从插件目录加载JSON格式的学生名单
            student_file = os.path.join(self.curdir, self.student_file)
            logger.info(f"[donotlazy] 尝试加载学生名单: {student_file}")
            
            if not os.path.exists(student_file):
                logger.warning(f"[donotlazy] 找不到学生名单文件: {student_file}")
                # 尝试直接加载students.json
                default_file = os.path.join(self.curdir, "students.json")
                if os.path.exists(default_file):
                    student_file = default_file
                    logger.info(f"[donotlazy] 尝试使用默认名单文件: {default_file}")
                else:
                    logger.error(f"[donotlazy] 默认名单文件也不存在: {default_file}")
                    return {}
            
            # 检查文件大小
            file_size = os.path.getsize(student_file)
            logger.info(f"[donotlazy] 学生名单文件大小: {file_size} 字节")
            
            # 读取JSON文件
            with open(student_file, "r", encoding="utf-8") as f:
                file_content = f.read()
                logger.info(f"[donotlazy] 文件内容前100个字符: {file_content[:100]}")
                
                # 解析JSON
                data = json.loads(file_content)
                logger.info(f"[donotlazy] 成功解析JSON，数据结构: {list(data.keys()) if isinstance(data, dict) else '非字典'}")
                
            # 解析学生数据
            if "students" in data and isinstance(data["students"], list):
                student_list = data["students"]
                for student in student_list:
                    if "name" in student and "id" in student:
                        students[student["name"]] = student["id"]
                        
            # 记录加载结果
            count = len(students)
            logger.info(f"[donotlazy] 成功从文件加载了 {count} 名学生")
            if count > 0:
                logger.info(f"[donotlazy] 部分学生名单: {list(students.keys())[:5]}...")
            else:
                logger.warning(f"[donotlazy] 从文件加载的学生名单为空")
            
            return students
        except Exception as e:
            logger.error(f"[donotlazy] 加载学生名单异常: {e}")
            logger.exception(e)  # 打印完整堆栈
            return {}
    
    def init_database(self):
        """初始化数据库"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # 创建已读记录表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS read_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        group_id TEXT,
                        student_name TEXT,
                        read_time TEXT,
                        create_date TEXT,
                        UNIQUE(group_id, student_name, create_date)
                    )
                ''')
                # 创建消息记录表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS message_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        group_id TEXT,
                        message_content TEXT,
                        create_time TEXT,
                        create_date TEXT
                    )
                ''')
                conn.commit()
                logger.info("[donotlazy] 数据库初始化成功")
        except Exception as e:
            logger.error(f"[donotlazy] 数据库初始化异常：{e}")
    
    def on_handle_context(self, e_context: EventContext):
        """处理用户命令"""
        if e_context["context"].type not in [ContextType.TEXT]:
            return
            
        msg: ChatMessage = e_context["context"]["msg"]
        content = e_context["context"].content.strip()
        
        # 查询已读同学
        if content == "查询已读同学":
            self._handle_query_read(e_context, msg)
        # 查询未读同学
        elif content == "查询未读同学":
            self._handle_query_unread(e_context, msg)
        # 重置记录
        elif content == "重置记录":
            self._handle_reset_confirm(e_context, msg)
        # 确认重置
        elif content == "确认重置":
            self._handle_reset_records(e_context, msg)
        # 查看学生名单
        elif content == "查看学生名单":
            self._handle_show_students(e_context, msg)
        # 更新学生名单
        elif content == "更新学生名单":
            self._handle_reload_students(e_context, msg)
        # 测试记录命令
        elif content == "测试记录同学24":
            self._handle_test_record(e_context, msg, "同学24")
    
    def _handle_query_read(self, e_context, msg):
        """处理查询已读同学命令"""
        reply = Reply()
        reply.type = ReplyType.TEXT
        
        try:
            # 获取查询日期范围（今天和7天前）
            today = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=self.max_record_days-1)).strftime('%Y-%m-%d')
            
            group_id = msg.other_user_id if e_context["context"]["isgroup"] else "私聊"
            group_name = msg.other_user_nickname if e_context["context"]["isgroup"] else "私聊"
            
            # 记录请求日志
            logger.info(f"[donotlazy] 查询已读同学, 群组ID: {group_id}, 群名: {group_name}, 日期范围: {start_date} 至 {today}")
            
            # 检查学生名单是否为空
            if not self.students:
                reply.content = f"未能加载学生名单，请检查配置。"
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
                return
            
            logger.info(f"[donotlazy] 已加载学生名单，共 {len(self.students)} 人")
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 检查数据库是否有记录
                cursor.execute("SELECT COUNT(*) FROM read_records")
                total_records = cursor.fetchone()[0]
                logger.info(f"[donotlazy] 数据库中共有 {total_records} 条已读记录")
                
                # 查询记录 - 在私聊中查询所有记录而不仅是私聊的记录
                if e_context["context"]["isgroup"]:
                    # 群聊中只查询该群的记录
                    cursor.execute('''
                        SELECT student_name, read_time, create_date, group_id
                        FROM read_records
                        WHERE group_id = ? AND create_date BETWEEN ? AND ?
                        ORDER BY create_date DESC, read_time ASC
                    ''', (group_id, start_date, today))
                else:
                    # 私聊中查询所有记录
                    cursor.execute('''
                        SELECT student_name, read_time, create_date, group_id
                        FROM read_records
                        WHERE create_date BETWEEN ? AND ?
                        ORDER BY create_date DESC, read_time ASC
                    ''', (start_date, today))
                
                records = cursor.fetchall()
                logger.info(f"[donotlazy] 查询到 {len(records)} 条符合条件的记录")
            
            if not records:
                reply.content = f"在 {start_date} 至 {today} 期间，{group_name} 没有记录到已读信息。"
            else:
                # 按日期分组
                date_groups = {}
                group_info = {}
                
                # 获取群组名称映射
                if not e_context["context"]["isgroup"]:
                    unique_group_ids = set(record[3] for record in records if record[3] != "私聊")
                    for unique_id in unique_group_ids:
                        group_info[unique_id] = "未知群组"  # 默认名称
                
                for record in records:
                    student_name, read_time, create_date, record_group_id = record
                    if create_date not in date_groups:
                        date_groups[create_date] = []
                    
                    # 在私聊模式下，添加群组信息
                    if not e_context["context"]["isgroup"]:
                        date_groups[create_date].append((student_name, read_time, record_group_id))
                    else:
                        date_groups[create_date].append((student_name, read_time))
                
                # 构建回复内容
                result = f"已读情况统计（{start_date} 至 {today}）\n\n"
                
                # 先显示今天的已读情况
                if today in date_groups:
                    today_students = date_groups[today]
                    result += f"今日（{today}）已读情况：\n"
                    
                    if not e_context["context"]["isgroup"]:
                        # 私聊中显示群组信息
                        for i, (name, time, record_group_id) in enumerate(today_students):
                            group_display = f"[{record_group_id}]" if record_group_id != "私聊" else ""
                            result += f"{i+1}. {name}{group_display}（{time}）\n"
                        
                        # 今日统计（私聊模式下不显示未读人数，因为跨群了）
                        result += f"今日已读：{len(today_students)}人\n\n"
                    else:
                        # 群聊中的显示方式
                        for i, (name, time) in enumerate(today_students):
                            result += f"{i+1}. {name}（{time}）\n"
                        result += f"今日已读：{len(today_students)}人，未读：{len(self.students) - len(today_students)}人\n\n"
                
                # 显示历史记录
                result += "历史已读记录：\n"
                for date, students in sorted(date_groups.items(), reverse=True):
                    if date == today:  # 今天的已经显示过了
                        continue
                    
                    if not e_context["context"]["isgroup"]:
                        # 按日期和群组汇总
                        group_counts = {}
                        for _, _, record_group_id in students:
                            if record_group_id not in group_counts:
                                group_counts[record_group_id] = 0
                            group_counts[record_group_id] += 1
                        
                        result += f"日期：{date} - 总计{len(students)}人已读\n"
                        # 显示每个群的情况
                        for group_id, count in group_counts.items():
                            group_display = f"[{group_id}]" if group_id != "私聊" else "[私聊]"
                            result += f"  {group_display}: {count}人\n"
                    else:
                        # 群聊中只显示人数
                        result += f"日期：{date} - {len(students)}人已读\n"
                
                reply.content = result.strip()
        except Exception as e:
            logger.error(f"[donotlazy] 查询已读同学异常：{e}")
            reply.content = f"查询失败：{str(e)}"
        
        e_context["reply"] = reply
        e_context.action = EventAction.BREAK_PASS
    
    def _handle_query_unread(self, e_context, msg):
        """处理查询未读同学命令"""
        reply = Reply()
        reply.type = ReplyType.TEXT
        
        try:
            # 获取当前日期
            today = datetime.now().strftime('%Y-%m-%d')
            
            group_id = msg.other_user_id if e_context["context"]["isgroup"] else "私聊"
            group_name = msg.other_user_nickname if e_context["context"]["isgroup"] else "私聊"
            
            # 在私聊中查询所有群组的未读情况
            if e_context["context"]["isgroup"]:
                # 获取今日该群已读学生
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT student_name
                        FROM read_records
                        WHERE group_id = ? AND create_date = ?
                    ''', (group_id, today))
                    
                    read_students = [record[0] for record in cursor.fetchall()]
                
                # 找出未读的学生
                unread_students = []
                for name in self.students.keys():
                    if name not in read_students:
                        unread_students.append(name)
                
                if not unread_students:
                    reply.content = f"在 {today}，{group_name} 所有同学均已阅读。"
                else:
                    result = f"未读情况统计（{today}）\n\n"
                    result += f"已读人数：{len(read_students)}人\n"
                    result += f"未读人数：{len(unread_students)}人\n\n"
                    result += f"未读同学名单：\n"
                    for i, name in enumerate(unread_students):
                        student_id = self.students.get(name, "")
                        result += f"{i+1}. {name}（学号：{student_id}）\n"
                    
                    reply.content = result.strip()
            else:
                # 私聊模式：获取所有群组的阅读情况
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    
                    # 获取所有活跃的群组
                    cursor.execute('''
                        SELECT DISTINCT group_id 
                        FROM read_records 
                        WHERE create_date = ? AND group_id != '私聊'
                    ''', (today,))
                    
                    active_groups = [record[0] for record in cursor.fetchall()]
                    
                    if not active_groups:
                        reply.content = f"在 {today}，没有任何群组的已读记录。"
                        e_context["reply"] = reply
                        e_context.action = EventAction.BREAK_PASS
                        return
                    
                    result = f"未读情况统计（{today}）\n\n"
                    
                    # 获取每个群的已读情况
                    for group_id in active_groups:
                        cursor.execute('''
                            SELECT student_name
                            FROM read_records
                            WHERE group_id = ? AND create_date = ?
                        ''', (group_id, today))
                        
                        read_students = [record[0] for record in cursor.fetchall()]
                        
                        # 找出未读的学生
                        unread_students = []
                        for name in self.students.keys():
                            if name not in read_students:
                                unread_students.append(name)
                        
                        result += f"【群组: {group_id}】\n"
                        result += f"已读人数：{len(read_students)}人\n"
                        result += f"未读人数：{len(unread_students)}人\n"
                        
                        if len(unread_students) > 0:
                            result += f"未读同学名单：\n"
                            # 只显示前10个未读学生，如果太多的话
                            display_limit = min(10, len(unread_students))
                            for i in range(display_limit):
                                student_id = self.students.get(unread_students[i], "")
                                result += f"{i+1}. {unread_students[i]}（学号：{student_id}）\n"
                            
                            if len(unread_students) > display_limit:
                                result += f"...等共 {len(unread_students)} 人未读\n"
                        
                        result += "\n"
                    
                    reply.content = result.strip()
        except Exception as e:
            logger.error(f"[donotlazy] 查询未读同学异常：{e}")
            reply.content = f"查询失败：{str(e)}"
        
        e_context["reply"] = reply
        e_context.action = EventAction.BREAK_PASS
    
    def _handle_reset_confirm(self, e_context, msg):
        """处理重置记录确认"""
        reply = Reply()
        reply.type = ReplyType.TEXT
        
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            group_id = msg.other_user_id if e_context["context"]["isgroup"] else "私聊"
            group_name = msg.other_user_nickname if e_context["context"]["isgroup"] else "私聊"
            
            # 查询当天记录数量
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT COUNT(*)
                    FROM read_records
                    WHERE group_id = ? AND create_date = ?
                ''', (group_id, today))
                
                count = cursor.fetchone()[0]
            
            if count == 0:
                reply.content = f"当前没有 {today} 的已读记录，无需重置。"
            else:
                reply.content = f"确认要重置 {today} 的已读记录吗？将删除 {count} 条记录。\n如果确认，请回复「确认重置」"
            
        except Exception as e:
            logger.error(f"[donotlazy] 重置确认异常：{e}")
            reply.content = f"操作失败：{str(e)}"
        
        e_context["reply"] = reply
        e_context.action = EventAction.BREAK_PASS
    
    def _handle_reset_records(self, e_context, msg):
        """处理重置记录命令"""
        reply = Reply()
        reply.type = ReplyType.TEXT
        
        try:
            group_id = msg.other_user_id if e_context["context"]["isgroup"] else "私聊"
            today = datetime.now().strftime('%Y-%m-%d')
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    DELETE FROM read_records
                    WHERE group_id = ? AND create_date = ?
                ''', (group_id, today))
                conn.commit()
                
                deleted_count = cursor.rowcount
            
            reply.content = f"已重置{today}的阅读记录，共删除 {deleted_count} 条记录。"
        except Exception as e:
            logger.error(f"[donotlazy] 重置记录异常：{e}")
            reply.content = f"重置失败：{str(e)}"
        
        e_context["reply"] = reply
        e_context.action = EventAction.BREAK_PASS
    
    def _handle_show_students(self, e_context, msg):
        """显示当前加载的学生名单"""
        reply = Reply()
        reply.type = ReplyType.TEXT
        
        try:
            if not self.students:
                reply.content = "当前未加载任何学生信息。"
            else:
                result = f"当前已加载 {len(self.students)} 名学生信息：\n\n"
                for i, (name, student_id) in enumerate(self.students.items()):
                    result += f"{i+1}. {name}（学号：{student_id}）\n"
                    
                # 检查是否包含特定学生
                if "同学24" in self.students:
                    result += f"\n同学24在名单中，学号为：{self.students['同学24']}"
                else:
                    result += f"\n注意：同学24不在名单中"
                    
                reply.content = result
        except Exception as e:
            logger.error(f"[donotlazy] 显示学生名单异常：{e}")
            reply.content = f"获取学生名单失败：{str(e)}"
        
        e_context["reply"] = reply
        e_context.action = EventAction.BREAK_PASS
    
    def on_receive_message(self, e_context: EventContext):
        """处理接收到的消息"""
        if e_context["context"].type not in [ContextType.TEXT]:
            return
            
        msg: ChatMessage = e_context["context"]["msg"]
        content = e_context["context"].content.strip()
        
        # 不是群消息则跳过
        if not e_context["context"]["isgroup"]:
            return
        
        # 自动清理过期数据
        self._clean_expired_records()
        
        # 记录群消息
        self._record_message(msg)
        
        # 优化已读消息识别
        self._process_read_message(msg, content)
    
    def _process_read_message(self, msg, content):
        """处理可能的已读消息"""
        try:
            logger.info(f"[donotlazy] 处理消息: {content}, 发送者: {msg.actual_user_nickname}")
            
            # 直接发送"已读"的情况
            if content == self.read_keyword:
                student_name = msg.actual_user_nickname
                logger.info(f"[donotlazy] 检测到纯已读消息，发送者: {student_name}")
                if student_name in self.students:
                    self._record_read_status(msg, student_name)
                    return
            
            # "XXX已读"的情况
            if self.read_keyword in content:
                logger.info(f"[donotlazy] 检测到可能包含已读的消息: {content}")
                
                # 先尝试精确匹配 "某某已读"
                for name in self.students.keys():
                    pattern = f"{name}{self.read_keyword}"
                    if pattern in content:
                        logger.info(f"[donotlazy] 从消息中精确匹配到学生: {name}")
                        self._record_read_status(msg, name)
                        return
                    
                # 尝试匹配发送者，如果是学生并且发送包含已读关键词的消息
                student_name = msg.actual_user_nickname
                if student_name in self.students and self.read_keyword in content:
                    logger.info(f"[donotlazy] 发送者是学生且消息包含已读关键词: {student_name}")
                    self._record_read_status(msg, student_name)
                    return
                
                # 尝试更宽松的匹配
                for name in self.students.keys():
                    # 部分匹配，姓名出现在已读关键词之前
                    if name in content and content.find(name) < content.find(self.read_keyword):
                        logger.info(f"[donotlazy] 从消息中模糊匹配到学生: {name}")
                        self._record_read_status(msg, name)
                        return
        except Exception as e:
            logger.error(f"[donotlazy] 处理已读消息异常: {e}")
    
    def _record_message(self, msg):
        """记录群消息"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                now = datetime.now()
                time_str = now.strftime('%Y-%m-%d %H:%M:%S')
                date_str = now.strftime('%Y-%m-%d')
                
                cursor.execute('''
                    INSERT INTO message_records (group_id, message_content, create_time, create_date)
                    VALUES (?, ?, ?, ?)
                ''', (
                    msg.other_user_id,
                    msg.content,
                    time_str,
                    date_str
                ))
                conn.commit()
        except Exception as e:
            logger.error(f"[donotlazy] 记录群消息异常：{e}")
    
    def _record_read_status(self, msg, student_name):
        """记录学生已读状态"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                now = datetime.now()
                time_str = now.strftime('%Y-%m-%d %H:%M:%S')
                date_str = now.strftime('%Y-%m-%d')
                
                group_id = msg.other_user_id
                
                # 检查该学生今日是否已记录
                cursor.execute('''
                    SELECT id FROM read_records 
                    WHERE group_id = ? AND student_name = ? AND create_date = ?
                ''', (group_id, student_name, date_str))
                record = cursor.fetchone()
                
                if record:
                    logger.info(f"[donotlazy] 学生 {student_name} 今日已有记录，更新时间")
                    cursor.execute('''
                        UPDATE read_records 
                        SET read_time = ? 
                        WHERE group_id = ? AND student_name = ? AND create_date = ?
                    ''', (time_str, group_id, student_name, date_str))
                else:
                    logger.info(f"[donotlazy] 新增学生 {student_name} 的已读记录")
                    cursor.execute('''
                        INSERT INTO read_records (group_id, student_name, read_time, create_date)
                        VALUES (?, ?, ?, ?)
                    ''', (group_id, student_name, time_str, date_str))
                
                conn.commit()
                logger.info(f"[donotlazy] 成功记录 {student_name} 的已读状态, 群组ID: {group_id}, 日期: {date_str}")
        except Exception as e:
            logger.error(f"[donotlazy] 记录已读状态异常：{e}")
    
    def _clean_expired_records(self):
        """清理过期记录"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                expire_date = (datetime.now() - timedelta(days=self.max_record_days)).strftime('%Y-%m-%d')
                
                # 清理已读记录
                cursor.execute('''
                    DELETE FROM read_records
                    WHERE create_date < ?
                ''', (expire_date,))
                
                # 清理消息记录
                cursor.execute('''
                    DELETE FROM message_records
                    WHERE create_date < ?
                ''', (expire_date,))
                
                conn.commit()
        except Exception as e:
            logger.error(f"[donotlazy] 清理过期记录异常：{e}")
    
    def get_help_text(self, **kwargs):
        help_text = "【不要偷懒】插件使用说明：\n"
        help_text += "1. 发送「已读」即可记录已读状态\n"
        help_text += "2. 发送「查询已读同学」查看已读情况\n"
        help_text += "3. 发送「查询未读同学」查看未读情况\n"
        help_text += "4. 发送「重置记录」清空当日记录\n"
        help_text += "5. 发送「查看学生名单」查看当前加载的学生名单\n"
        help_text += "6. 发送「更新学生名单」手动重新加载学生名单\n"
        help_text += "7. 学生可以直接发送「XXX已读」记录指定学生已读状态\n"
        help_text += "8. 发送「测试记录同学24」测试记录功能\n"
        return help_text
    
    def _load_config_template(self):
        logger.info("[donotlazy] 使用配置模板")
        try:
            plugin_config_path = os.path.join(self.path, "config.json.template")
            if os.path.exists(plugin_config_path):
                with open(plugin_config_path, "r", encoding="utf-8") as f:
                    plugin_conf = json.load(f)
                    return plugin_conf
            return {}
        except Exception as e:
            logger.exception(e)
            return {}
    
    def _handle_test_record(self, e_context, msg, student_name):
        """测试记录指定学生的已读状态"""
        reply = Reply()
        reply.type = ReplyType.TEXT
        
        try:
            if student_name not in self.students:
                reply.content = f"学生名单中不存在 {student_name}，可用学生: {list(self.students.keys())[:5]}"
            else:
                self._record_read_status(msg, student_name)
                reply.content = f"已成功记录 {student_name} 的已读状态。"
        except Exception as e:
            logger.error(f"[donotlazy] 测试记录异常：{e}")
            reply.content = f"测试记录失败：{str(e)}"
        
        e_context["reply"] = reply
        e_context.action = EventAction.BREAK_PASS
    
    def _handle_reload_students(self, e_context, msg):
        """重新加载学生名单"""
        reply = Reply()
        reply.type = ReplyType.TEXT
        
        try:
            # 记录之前的学生数量
            old_count = len(self.students)
            old_students = list(self.students.keys())[:5]
            
            # 重新加载学生名单
            self.students = self.load_students()
            
            # 计算新增学生
            new_count = len(self.students)
            
            if new_count == 0:
                reply.content = "学生名单加载失败，当前没有学生信息。"
            else:
                reply.content = f"学生名单已更新。之前有 {old_count} 名学生，现在有 {new_count} 名学生。\n"
                reply.content += f"之前的前5名学生: {old_students}\n"
                reply.content += f"现在的前5名学生: {list(self.students.keys())[:5]}"
                
                # 检查同学24是否在名单中
                if "同学24" in self.students:
                    reply.content += f"\n同学24在名单中，学号为: {self.students['同学24']}"
        except Exception as e:
            logger.error(f"[donotlazy] 重新加载学生名单异常: {e}")
            reply.content = f"更新学生名单失败: {str(e)}"
        
        e_context["reply"] = reply
        e_context.action = EventAction.BREAK_PASS 