# donotlazy 插件 dow的插件

## 功能介绍

用于记录群聊中学生的已读情况，适用于班级通知的发布和阅读情况追踪。

## 主要功能
1. 自动记录群成员发送的"已读"消息
2. 支持查询已读/未读同学名单
3. 支持重置阅读记录
4. 自动清理7天前的历史记录

## 使用方法

### 学生端
- 发送"已读"即可记录已读状态

### 教师端
- 发送"查询已读同学"查看已读情况
- 发送"查询未读同学"查看未读情况
- 发送"重置记录"清空当日记录
- 发送"查看学生名单"查看当前加载的学生名单 
- 发送"更新学生名单"手动重新加载学生名单

## 配置说明

插件配置文件中可以设置以下参数：
- `max_record_days`: 记录保存天数，默认7天
- `read_keyword`: 已读关键词，默认"已读"
- `class_name`: 班级名称，默认"3班"
- `student_file`: 学生名单文件，默认"students.json"

## 学生名单格式

学生名单使用JSON格式，存放在`students.json`文件中，格式如下：

```json
{
  "students": [
    {"name": "同学1", "id": "1"},
    {"name": "同学2", "id": "2"},
    {"name": "同学24", "id": "24"}
  ]
}
```

## 注意事项

1. 学生需要在群内的昵称与学生名单中的姓名一致，才能正确记录
2. 插件会从`students.json`文件读取学生信息
3. 所有记录会在设定的天数后自动删除 