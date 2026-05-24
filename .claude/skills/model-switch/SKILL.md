---
name: model-switch
description: Manually switch between DeepSeek models (pro/flash/chat/reasoner). Changes take effect after restart.
origin: custom
version: 0.1
---

# Model Switch

当用户要求切换 DeepSeek 模型时，执行以下操作：

## 操作步骤

1. 从用户消息中提取模型别名（pro/flash/chat/reasoner/v4-pro/v4-flash 或完整模型 ID）
2. 执行切换脚本：
   ```
   powershell -File ".claude/scripts/switch_model.ps1" -ModelAlias "<alias>"
   ```
3. 将脚本输出转述给用户，强调**需要重启 Claude Code 才能生效**

## 参数说明

| 别名 | 完整模型 ID | 说明 |
|------|-----------|------|
| pro / v4-pro | deepseek-v4-pro | 最强能力，复杂任务 |
| flash / v4-flash | deepseek-v4-flash | 快速响应，日常使用 |
| chat | deepseek-chat | 通用对话 |
| reasoner | deepseek-reasoner | 推理增强 |

## 无参调用

如果用户没指定模型，执行无参命令显示当前模型和可用列表：
```
powershell -File ".claude/scripts/switch_model.ps1"
```
