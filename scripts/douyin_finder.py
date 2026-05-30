"""
抖音热点视频搜索器 - 极轻量版
用法: python douyin_finder.py "搜索关键词"
"""
import asyncio, sys


async def search(keyword: str):
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        url = f"https://www.douyin.com/search/{keyword}?type=video"
        print(f"搜索: {url}")

        try:
            await page.goto(url, timeout=15000, wait_until="domcontentloaded")
            await page.wait_for_timeout(4000)
        except Exception as e:
            print(f"页面加载异常: {e}")

        # 方法1: 从链接提取 video ID
        video_links = await page.evaluate("""() => {
            const links = document.querySelectorAll('a[href*="/video/"]');
            const ids = new Set();
            links.forEach(a => {
                const m = a.href.match(/video[\\\\/](\\\\d+)/);
                if (m) ids.add(m[1]);
            });
            return [...ids].slice(0, 5).map(id => 'https://www.douyin.com/video/' + id);
        }""")

        # 方法2: 从页面文本提取视频 ID (RENDER_DATA)
        if not video_links:
            html = await page.content()
            import re
            ids = re.findall(r'aweme_id["\':]\s*["\']?(\d+)', html)
            video_links = [f"https://www.douyin.com/video/{i}" for i in set(ids[:5])]

        # 方法3: 看看页面有没有搜索结果卡片
        if not video_links:
            text = await page.inner_text('body')
            print(f"页面预览: {text[:200]}...")

        await browser.close()
        return video_links


async def main():
    kw = sys.argv[1] if len(sys.argv) > 1 else "AI设备"
    print(f"搜索关键词: {kw}")
    links = await search(kw)

    if links:
        print(f"\n找到 {len(links)} 个视频:")
        for url in links:
            print(f"  {url}")
        print(f"\n复制上面任一链接发给 Claude")
    else:
        print("\n没找到视频链接")
        print("可能原因: 需要登录 / 反爬拦截 / 页面结构变了")
        print("试试在浏览器里手动搜一个视频, 把链接复制过来")


if __name__ == "__main__":
    asyncio.run(main())
