"""提取抖音 Cookie 并写入 Douyin API 配置. """
import browser_cookie3
import re

# 从浏览器提取
cookies = browser_cookie3.load(domain_name='douyin.com')
cookie_list = list(cookies)
print(f"找到 {len(cookie_list)} 个 Cookie")

if not cookie_list:
    # Try Edge
    cookies = browser_cookie3.edge(domain_name='douyin.com')
    cookie_list = list(cookies)
    print(f"Edge: 找到 {len(cookie_list)} 个 Cookie")

if not cookie_list:
    print("未找到 Cookie，请先登录抖音网页版")
    exit(1)

# 构建 cookie 字符串
cookie_str = "; ".join(f"{c.name}={c.value}" for c in cookie_list if c.value)

print(f"Cookie 长度: {len(cookie_str)}")

# 写入配置文件
config_path = r"C:\Users\Administrator\AppData\Local\Temp\Douyin_TikTok_Download_API\crawlers\douyin\web\config.yaml"
with open(config_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 替换 Cookie 行
# 匹配 Cookie: 后面到换行或下一个key
new_content = re.sub(
    r'(Cookie:\s*).*(\n\s{2}[a-zA-Z])',
    lambda m: f"Cookie: {cookie_str}{m.group(2)}",
    content,
    count=1
)

with open(config_path, 'w', encoding='utf-8') as f:
    f.write(new_content)

print("Cookie 已更新！")
print(f"预览: {cookie_str[:80]}...")
