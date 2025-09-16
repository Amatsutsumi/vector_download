import os
import re
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from tqdm import tqdm

# --- 配置区 ---
TARGET_URLS = [
    "https://www.vector.co.jp/vpack/filearea/winnt/game/avg/",
    "https://www.vector.co.jp/vpack/filearea/win95/game/avg/",
    "https://www.vector.co.jp/vpack/filearea/win95/amuse/novel/",
    "https://www.vector.co.jp/vpack/filearea/win95/amuse/vbook/"
]
DOWNLOAD_DIR = "vector_games"
FAILED_LOG_FILE = "failed_downloads.log"
PROGRESS_FILE = "processed_links.log" # 进度记录文件名
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Referer': 'https://www.vector.co.jp/'
}
SLEEP_TIME = 1.0

# --- 辅助功能 ---

def sanitize_filename(name: str) -> str:
    """清理文件名中的非法字符"""
    sanitized = re.sub(r'[\\/:*?"<>|]', '_', name)
    return sanitized.strip('. ')

def log_failure(url: str):
    """记录下载失败的链接"""
    print(f"  [!] 操作失败，已将链接记录到 {FAILED_LOG_FILE}")
    with open(FAILED_LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(url + '\n')

def load_progress() -> set:
    """读取进度文件，返回已处理的链接集合"""
    if not os.path.exists(PROGRESS_FILE):
        return set()
    with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
        processed_links = {line.strip() for line in f if line.strip()}
    print(f"[*] 已从 {PROGRESS_FILE} 加载 {len(processed_links)} 条进度记录。")
    return processed_links

def save_progress(url: str):
    """将成功处理的链接写入进度文件"""
    with open(PROGRESS_FILE, 'a', encoding='utf-8') as f:
        f.write(url + '\n')

# --- 核心功能 ---

def get_all_game_links_from_category(start_url, session):
    """从分类首页开始，抓取所有分页，返回全部游戏链接"""
    print(f"\n[*] 正在从分类首页 {start_url} 深度抓取所有游戏...")
    all_game_links = []
    pages_to_scrape = [start_url]
    scraped_pages = set()

    while pages_to_scrape:
        current_url = pages_to_scrape.pop(0)
        if current_url in scraped_pages: continue

        print(f"  -> 正在抓取列表页: {current_url}")
        scraped_pages.add(current_url)
        try:
            response = session.get(current_url, headers=HEADERS, timeout=15)
            response.raise_for_status()
            response.encoding = 'shift_jis'
            soup = BeautifulSoup(response.text, 'html.parser')
            
            game_elements = soup.select('ul.file_list li a[href*="/soft/"]')
            for link in game_elements:
                if '/game/se' in link['href']:
                    full_url = urljoin(current_url, link['href'])
                    if full_url not in all_game_links: all_game_links.append(full_url)
            
            page_nav_links = soup.select('div.pagenav a')
            for page_link in page_nav_links:
                page_url = urljoin(current_url, page_link['href'])
                if page_url not in scraped_pages: pages_to_scrape.append(page_url)
        except requests.RequestException as e:
            print(f"  [!] 抓取页面 {current_url} 失败: {e}")
        time.sleep(SLEEP_TIME)

    print(f"[+] 分类 {start_url} 抓取完成，共找到 {len(all_game_links)} 个不重复的游戏链接。")
    return all_game_links

def get_download_info_page_url(intro_page_url, session):
    """第1步: 获取下载信息页URL和游戏标题"""
    print(f"  [1/4] 正在访问软件介绍页: {intro_page_url}")
    try:
        response = session.get(intro_page_url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        response.encoding = 'shift_jis'
        soup = BeautifulSoup(response.text, 'html.parser')
        
        game_title_element = soup.select_one('h1 strong.fn')
        game_title = game_title_element.text.strip() if game_title_element else "Unknown_Game"

        download_link = soup.select_one('div.action a.download_go')
        if download_link:
            url = urljoin(intro_page_url, download_link['href'])
            print(f"  [+] 成功找到游戏标题: '{game_title}'")
            print(f"  [+] 成功找到下载信息页链接: {url}")
            return url, game_title
        else:
            print(f"  [!] 在页面上未找到下载信息页的按钮。")
            return None, None
    except requests.RequestException as e:
        print(f"  [!] 访问软件介绍页失败: {e}")
        return None, None

def get_download_trigger_url(info_page_url, session):
    """第2步: 获取下载触发页的链接"""
    print(f"  [2/4] 正在访问下载信息页: {info_page_url}")
    try:
        response = session.get(info_page_url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        response.encoding = 'shift_jis'
        soup = BeautifulSoup(response.text, 'html.parser')
        trigger_link = soup.select_one('div.action a.download')
        if trigger_link:
            url = urljoin(info_page_url, trigger_link['href'])
            print(f"  [+] 成功找到下载触发页链接: {url}")
            return url
        else:
            print(f"  [!] 在页面上未找到下载触发页的按钮。")
            return None
    except requests.RequestException as e:
        print(f"  [!] 访问下载信息页失败: {e}")
        return None

def get_final_ftp_url(trigger_url, session):
    """第3步: 解析出最终的 FTP 下载链接"""
    print(f"  [3/4] 正在解析下载触发页: {trigger_url}")
    try:
        response = session.get(trigger_url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        response.encoding = 'shift_jis'
        soup = BeautifulSoup(response.text, 'html.parser')
        final_link = soup.select_one('div#summary a[href*="ftp.vector.co.jp"]')
        if final_link:
            ftp_url = final_link['href']
            print(f"  [+] 成功解析出最终FTP链接: {ftp_url}")
            return ftp_url
        else:
            print(f"  [!] 未能解析出最终FTP链接。")
            return None
    except requests.RequestException as e:
        print(f"  [!] 解析下载触发页失败: {e}")
        return None

def download_file(ftp_url, game_title, session) -> bool:
    """第4步: 下载文件并重命名。成功返回True，失败返回False"""
    if not ftp_url: return False

    original_filename = ftp_url.split('/')[-1]
    _, extension = os.path.splitext(original_filename)
    sanitized_title = sanitize_filename(game_title)
    new_filename = f"{sanitized_title}{extension}"
    filepath = os.path.join(DOWNLOAD_DIR, new_filename)

    if os.path.exists(filepath):
        print(f"  [*] 文件 '{new_filename}' 已存在，跳过。")
        return True # 文件已存在也算作成功处理

    print(f"  [4/4] 开始下载: {original_filename} -> {new_filename}")
    try:
        with session.get(ftp_url, headers=HEADERS, stream=True, timeout=180) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            
            with open(filepath, 'wb') as f, tqdm(
                total=total_size, unit='iB', unit_scale=True, unit_divisor=1024,
                desc="      " + new_filename[:30], leave=False
            ) as bar:
                for chunk in r.iter_content(chunk_size=8192):
                    size = f.write(chunk)
                    bar.update(size)
        print(f"  [+] 下载并重命名完成: {new_filename}")
        return True
    except Exception as e:
        print(f"  [!] 下载文件 '{original_filename}' 失败: {e}")
        log_failure(ftp_url)
        if os.path.exists(filepath): os.remove(filepath)
        return False

def main():
    print("--- Vector 批量下载脚本启动 (v4.0 - 带进度断点续传) ---")
    session = requests.Session()
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)
        print(f"[*] 已创建下载目录: {DOWNLOAD_DIR}")

    # 加载已完成的进度
    processed_links = load_progress()

    # 仅在第一次运行时获取全部链接，以避免重复抓取
    all_links_file = "all_game_links.txt"
    if not os.path.exists(all_links_file):
        print("[*] 首次运行，正在获取所有游戏链接...")
        all_game_links = []
        for url in TARGET_URLS:
            all_game_links.extend(get_all_game_links_from_category(url, session))
        unique_game_links = sorted(list(set(all_game_links)))
        with open(all_links_file, 'w', encoding='utf-8') as f:
            for link in unique_game_links:
                f.write(link + '\n')
        print(f"[*] 所有链接已获取并保存到 {all_links_file}。")
    else:
        print(f"[*] 从 {all_links_file} 加载游戏链接列表...")
        with open(all_links_file, 'r', encoding='utf-8') as f:
            unique_game_links = [line.strip() for line in f if line.strip()]

    if not unique_game_links:
        print("[!] 未找到任何游戏，程序退出。")
        return

    print("-" * 50)
    print(f"[*] 任务开始，总计 {len(unique_game_links)} 个游戏，已完成 {len(processed_links)} 个。")
    print("-" * 50)

    for i, intro_link in enumerate(unique_game_links):
        print(f"--- 进度 {i+1}/{len(unique_game_links)} ---")

        # 核心功能：检查进度
        if intro_link in processed_links:
            print(f"[*] 根据进度文件，跳过已处理的链接: {intro_link}")
            continue

        download_successful = False
        
        info_page_url, game_title = get_download_info_page_url(intro_link, session)
        time.sleep(SLEEP_TIME)

        if info_page_url:
            trigger_url = get_download_trigger_url(info_page_url, session)
            time.sleep(SLEEP_TIME)
            if trigger_url:
                ftp_url = get_final_ftp_url(trigger_url, session)
                time.sleep(SLEEP_TIME)
                if ftp_url:
                    if download_file(ftp_url, game_title, session):
                        download_successful = True
        
        if download_successful:
            # 只有当文件确定下载完成或已存在时，才记录进度
            save_progress(intro_link)
        else:
            # 如果中间任何一步失败，都记录到失败日志
            log_failure(intro_link)

    print("\n" + "=" * 50)
    print("[*] 所有任务已完成！")
    print(f"[*] 请检查 '{DOWNLOAD_DIR}' 目录。")
    print(f"[*] 失败的链接记录在 '{FAILED_LOG_FILE}'。")
    print(f"[*] 本次运行进度已记录在 '{PROGRESS_FILE}'。")
    print("=" * 50)

if __name__ == '__main__':
    main()
