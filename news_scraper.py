import asyncio
import aiohttp
import requests
import logging
from bs4 import BeautifulSoup
from transformers import pipeline

logging.basicConfig(
    filename='scraper.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class NewsScraperConfig:
    BATCH_SIZE = 5
    TIMEOUT = 30
    # FLASK_SERVER_URL = 'http://localhost:5000/data'
    FLASK_SERVER_URL = 'https://piyamianglae.pythonanywhere.com/data'

    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        self.summarizer = pipeline("summarization", model="facebook/bart-large-cnn")

        self.attack_types = {
            'ransomware': ['ransomware', 'ransom', 'encryption attack', 'decrypt key'],
            'malware': ['malware', 'virus', 'trojan', 'worm'],
            'phishing': ['phishing', 'spear phishing', 'social engineering'],
            'data breach': ['data breach', 'leak', 'exposed data'],
            'ddos': ['ddos', 'denial of service', 'traffic flood'],
            'vulnerability': ['vulnerability', 'exploit', 'zero-day', 'security flaw']
        }


class NewsScraper:
    def __init__(self, config: NewsScraperConfig):
        self.config = config
        self.session = None
        self.processed_titles = set()
        self.init_processed_titles()

    def init_processed_titles(self):
        response = requests.get(self.config.FLASK_SERVER_URL)
        if response.status_code == 200:
            articles = response.json()
            if isinstance(articles, list):
                self.processed_titles = {article['Title'] for article in articles}
            else:
                logging.error("Unexpected data format: articles is not a list.")
        else:
            logging.error(f"Error fetching initial data from Flask server: {response.status_code}")

    async def init_session(self):
        if not self.session:
            timeout = aiohttp.ClientTimeout(total=self.config.TIMEOUT)
            self.session = aiohttp.ClientSession(timeout=timeout)

    async def close_session(self):
        if self.session:
            await self.session.close()

    async def fetch_page(self, url: str, retries: int = 3) -> str:
        for attempt in range(retries):
            try:
                async with self.session.get(url, headers=self.config.headers) as response:
                    if response.status == 200:
                        return await response.text()
                    await asyncio.sleep(1)
            except Exception as e:
                logging.error(f"Error fetching {url}: {e}")
                if attempt == retries - 1:
                    return None
                await asyncio.sleep(1)
        return None

    def classify_content(self, content: str) -> str:
        content_lower = content.lower()
        for category, keywords in self.config.attack_types.items():
            if any(keyword in content_lower for keyword in keywords):
                return category
        return None

    async def summarize_content(self, content: str) -> str:
        if len(content) > 1024:
            content = content[:1024]
        summary = self.config.summarizer(content, max_length=130, min_length=50, do_sample=False)
        return summary[0]['summary_text']

    async def get_article_links(self, url: str) -> list:
        content = await self.fetch_page(url)
        if not content:
            return []
        soup = BeautifulSoup(content, 'html.parser')
        return [a['href'] for a in soup.select('ul#bc-home-news-main-wrap li h4 a')]

    async def get_article_details(self, url: str) -> dict:
        content = await self.fetch_page(url)
        if not content:
            return None

        try:
            soup = BeautifulSoup(content, 'html.parser')

            title = soup.find('h1').text.strip() if soup.find('h1') else ""
            if title in self.processed_titles:
                return None

            date = soup.find('li', class_='cz-news-date').text.strip() if soup.find('li', class_='cz-news-date') else ""
            content = ' '.join([p.text for p in soup.select('div.articleBody p')])

            if not all([title, date, content]):
                return None

            category = self.classify_content(content)
            if not category:
                return None

            summary = await self.summarize_content(content)

            return {
                'Title': title,
                'Date': date,
                'Category': category,
                'Summary': summary
            }

        except Exception as e:
            logging.error(f"Error processing {url}: {e}")
            return None

    def save_to_flask_server(self, articles: list):
        if not articles:
            return
        for article in articles:
            if article and article['Title'] not in self.processed_titles:
                response = requests.post(self.config.FLASK_SERVER_URL, json=article)
                if response.status_code == 201:
                    self.processed_titles.add(article['Title'])
                else:
                    logging.error(f"Error saving article to Flask server: {response.status_code}")

    async def process_articles_batch(self, links: list):
        tasks = []
        for i in range(0, len(links), self.config.BATCH_SIZE):
            batch = links[i:i + self.config.BATCH_SIZE]
            tasks = [self.get_article_details(link) for link in batch]
            results = await asyncio.gather(*tasks)
            valid_results = [r for r in results if r is not None]
            if valid_results:
                self.save_to_flask_server(valid_results)
            await asyncio.sleep(1)

    async def run(self, start_url: str, max_pages: int = 1):
        await self.init_session()
        try:
            current_url = start_url
            page_number = 1

            while current_url and page_number <= max_pages:
                logging.info(f"Processing page {page_number}")
                print(f"Processing page {page_number}")

                links = await self.get_article_links(current_url)
                if links:
                    await self.process_articles_batch(links)

                content = await self.fetch_page(current_url)
                if not content:
                    break

                soup = BeautifulSoup(content, 'html.parser')
                next_link = soup.find('a', {'aria-label': 'Next Page'})
                current_url = next_link['href'] if next_link else None

                page_number += 1
                await asyncio.sleep(2)

            print("Scraping completed.")
        except Exception as e:
            logging.error(f"Error during scraping: {e}")
        finally:
            await self.close_session()


async def main():
    config = NewsScraperConfig()
    scraper = NewsScraper(config)
    await scraper.run("https://www.bleepingcomputer.com/news/security", max_pages=2)


if __name__ == "__main__":
    asyncio.run(main())v
