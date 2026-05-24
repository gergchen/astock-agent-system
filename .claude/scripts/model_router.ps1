# Model Router Hook — UserPromptSubmit
# 从 stdin 读取 JSON，提取用户提示词，判断复杂度并输出模型选择

$rawInput = $input | Out-String
$json = $rawInput | ConvertFrom-Json
$prompt = $json.prompt ?? $json.user_message ?? $json.user_prompt ?? ""

# 复杂任务关键词
$complex = @(
    "写代码", "实现", "修复", "重构", "调试", "debug",
    "优化", "设计", "架构", "review", "审查",
    "写.*脚本", "写.*程序", "开发", "改.*bug",
    "implement", "refactor", "fix", "build", "create",
    "optimize", "design", "architect", "migrate",
    "PR", "pull request", "commit", "测试", "test",
    "部署", "deploy", "配置", "config",
    "分析.*代码", "分析.*项目", "code review",
    "security", "安全", "漏洞", "vulnerability",
    "回测", "backtest", "策略", "strategy"
)

# 简单任务关键词
$simple = @(
    "是什么", "怎么用", "解释", "说明", "什么是",
    "what is", "how to", "explain", "文档",
    "今天", "天气", "新闻", "翻译", "translate",
    "总结", "summarize", "帮我查", "搜索", "search",
    "记录", "日志", "journal"
)

$isComplex = $false
foreach ($kw in $complex) {
    if ($prompt -match $kw) {
        $isComplex = $true
        break
    }
}

if (-not $isComplex) {
    foreach ($kw in $simple) {
        if ($prompt -match $kw) {
            Write-Output '{"model":"deepseek-flash"}'
            exit 0
        }
    }
}

# 默认走 Pro
Write-Output '{"model":"deepseek-pro"}'
