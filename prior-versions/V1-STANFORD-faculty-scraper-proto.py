import requests
from bs4 import BeautifulSoup
import json
import re
import time
from urllib.parse import urljoin, urlparse, urlencode
from openai import OpenAI
from dotenv import load_dotenv
import os
from typing import List, Dict, Optional

# Load environment variables
load_dotenv()

# CONFIGURATION VARIABLES
FACULTY_PAGE_URL = "https://www.cs.stanford.edu/people/faculty"
FACULTY_LINKS_LIMIT = 5  # Maximum number of faculty profile links to process
REQUEST_DELAY = 2  # Seconds to wait between requests (be respectful)
SCHOLAR_REQUEST_DELAY = 3  # Seconds to wait between Google Scholar requests

class IntegratedFacultyScraper:
    def __init__(self):
        """Initialize the scraper with OpenAI client and API keys"""
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
        # Initialize OpenAI client
        self.client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY")
        )
        
        # SerpAPI key for Google Scholar
        self.serpapi_key = os.getenv("SERPAPI_API_KEY")
        
    def get_page_content(self, url: str) -> Optional[BeautifulSoup]:
        """Fetch and parse a web page"""
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'html.parser')
        except Exception as e:
            print(f"Error fetching {url}: {e}")
            return None
    
    def find_emails_in_page(self, soup: BeautifulSoup) -> List[Dict]:
        """Find all academic emails in the page and their surrounding context"""
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        emails_found = []
        
        # Look for mailto links first (more reliable)
        mailto_links = soup.find_all('a', href=re.compile(r'^mailto:'))
        for link in mailto_links:
            email = link['href'].replace('mailto:', '').strip()
            if self.is_academic_email(email):
                emails_found.append({
                    'email': email,
                    'context_element': link
                })
        
        # Also search for email patterns in text (backup)
        text_elements = soup.find_all(['p', 'div', 'span', 'td', 'li'])
        for element in text_elements:
            text = element.get_text()
            emails = re.findall(email_pattern, text)
            for email in emails:
                if self.is_academic_email(email) and not any(e['email'] == email for e in emails_found):
                    emails_found.append({
                        'email': email,
                        'context_element': element
                    })
        
        return emails_found
    
    def is_academic_email(self, email: str) -> bool:
        """Check if email looks like an academic/faculty email"""
        email_lower = email.lower()
        
        # Skip generic/admin emails
        generic_prefixes = [
            'info@', 'contact@', 'admin@', 'webmaster@', 'support@',
            'help@', 'noreply@', 'no-reply@', 'postmaster@'
        ]
        
        for prefix in generic_prefixes:
            if email_lower.startswith(prefix):
                return False
        
        # Must be from an academic domain
        academic_domains = [
            'stanford.edu', 'cs.stanford.edu', '.edu', '.ac.uk', '.ac.jp'
        ]
        
        return any(domain in email_lower for domain in academic_domains)
    
    def extract_faculty_links(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        """Extract individual faculty profile URLs from faculty directory page"""
        faculty_links = []
        
        # More specific selectors for individual faculty profiles
        selectors = [
            'a[href*="/people/"][href*="-"]',  # Stanford-style individual profile URLs
            '.faculty-list a[href*="/people/"]',
            '.person-card a',
            '.faculty-member a[href*="profile"]',
            '.directory-entry a',
            'a[href*="/~"]',  # Academic tilde URLs
            '.people-list a[href*="/people/"]'
        ]
        
        for selector in selectors:
            links = soup.select(selector)
            for link in links:
                href = link.get('href')
                if href:
                    full_url = urljoin(base_url, href)
                    # More rigorous filtering
                    if self.is_individual_faculty_profile(full_url, link.text, link):
                        faculty_links.append(full_url)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_links = []
        for link in faculty_links:
            if link not in seen:
                seen.add(link)
                unique_links.append(link)
                
        return unique_links[:FACULTY_LINKS_LIMIT]  # Use configurable limit
    
    def is_individual_faculty_profile(self, url: str, link_text: str, link_element) -> bool:
        """More rigorous check to identify individual faculty profile links"""
        url_lower = url.lower()
        text_lower = link_text.lower().strip()
        
        # Exclude obvious navigation/category pages
        exclude_patterns = [
            'faculty-name', 'emeritus-faculty', 'courtesy-faculty', 
            'adjunct-faculty', 'visiting-and-acting-faculty',
            '/people/faculty', '/people-cs/', '/faculty$', '/emeritus$',
            'directory', 'all-faculty', 'faculty-list', 'staff',
            'students', 'admin', 'news', 'events', 'calendar',
            'contact', 'about', 'home', 'search'
        ]
        
        for pattern in exclude_patterns:
            if pattern in url_lower:
                return False
        
        # Exclude generic category text
        exclude_text = [
            'faculty by name', 'emeritus faculty', 'courtesy faculty',
            'adjunct faculty', 'visiting and acting faculty', 'faculty',
            'all faculty', 'directory', 'people'
        ]
        
        for pattern in exclude_text:
            if text_lower == pattern or text_lower.startswith(pattern):
                return False
        
        # Must have individual identifiers (name-like patterns)
        url_parts = url.split('/')
        last_part = url_parts[-1] if url_parts else ""
        
        # Check if URL looks like an individual profile
        individual_indicators = [
            '-' in last_part and len(last_part) > 5,  # Has hyphens (name-like)
            re.match(r'^[a-z]+-[a-z]+', last_part),  # firstname-lastname pattern
            re.match(r'^~[a-z]+', last_part),        # Tilde username
            len(last_part.split('-')) >= 2           # Multiple parts separated by hyphens
        ]
        
        # Must have at least one individual indicator
        if not any(individual_indicators):
            return False
        
        return True  # If it passes other checks, include it
    
    def extract_professor_basic_data(self, soup: BeautifulSoup, profile_url: str) -> Optional[Dict]:
        """Extract basic professor data (name and email) using raw dump parsing"""
        try:
            # Find emails in the page
            emails_data = self.find_emails_in_page(soup)
            
            if not emails_data:
                print(f"    No academic emails found")
                return None
            
            # Use the first email found
            email_data = emails_data[0]  # Take the first email
            email = email_data['email']
            
            # Get RAW DUMP of the entire page content
            raw_page_text = soup.get_text()
            clean_page_text = re.sub(r'\s+', ' ', raw_page_text).strip()
            
            # Use OpenAI to parse the raw dump and extract structured data
            parsed_data = self.parse_raw_content_with_ai(clean_page_text, email, profile_url)
            
            if not parsed_data or not parsed_data.get('name'):
                print(f"    AI parsing failed for email {email}")
                return None
            
            print(f"    ✅ Found: {parsed_data['name']} ({email})")
            
            return {
                'name': parsed_data['name'],
                'email': email,
                'title': parsed_data.get('title', ''),
                'profile_url': profile_url,
                'ai_confidence': parsed_data.get('confidence', 'medium')
            }
            
        except Exception as e:
            print(f"Error extracting basic data from {profile_url}: {e}")
            return None
    
    def parse_raw_content_with_ai(self, raw_text: str, email: str, profile_url: str) -> Optional[Dict]:
        """Use AI to parse raw page content and extract structured professor data"""
        try:
            # Limit text size to avoid token limits
            if len(raw_text) > 8000:  # Keep reasonable size for GPT
                raw_text = raw_text[:8000] + "..."
            
            prompt = f"""
            You are parsing a professor's profile page. The page contains a lot of navigation and menu content mixed with the actual profile information.

            EMAIL FOUND: {email}
            PROFILE URL: {profile_url}
            
            RAW PAGE TEXT:
            "{raw_text}"
            
            Your task: Extract the professor's information from this raw text dump. Look for the actual person's name and title while ignoring navigation menus, course listings, and administrative content.
            
            Return ONLY a JSON object with this exact structure:
            {{
                "name": "Professor's full name (e.g., 'John Smith' or 'Jane Doe')",
                "title": "Academic title (e.g., 'Associate Professor of Computer Science')",
                "confidence": "high|medium|low - your confidence in the extraction"
            }}
            
            Rules:
            - The name should be a real person's name (first and last name)
            - Ignore generic terms like "Mail Code", "Contact", "Faculty", etc.
            - Look for context around the email address for the person's actual name
            - The title should be their academic position, not administrative labels
            - If you can't find reliable information, use empty strings but still return the JSON structure
            - Focus on content that appears to be about an individual person, not general university information
            """
            
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
                temperature=0.1
            )
            
            result = json.loads(response.choices[0].message.content)
            
            # Validate the result
            if (result.get('name') and 
                len(result['name'].split()) >= 2 and  # At least first and last name
                result['name'] not in ['Mail Code', 'Contact', 'Faculty', 'Professor']):
                return result
            else:
                print(f"    AI returned invalid name: {result.get('name')}")
                return None
                
        except Exception as e:
            print(f"    AI parsing error: {e}")
            return None
    
    def get_professor_papers_direct_search(self, prof_name: str, prof_email: str, num_papers: int = 10) -> Dict:
        """Search directly for professor's papers using author search"""
        if not self.serpapi_key:
            return {
                "error": "SERPAPI_API_KEY not found in environment variables",
                "professor": {"name": prof_name, "email": prof_email}
            }
        
        url = "https://serpapi.com/search"
        
        # Search for papers by this author
        params = {
            "engine": "google_scholar",
            "q": f'author:"{prof_name}"',
            "api_key": self.serpapi_key,
            "num": num_papers,
            "start": 0
        }
        
        try:
            print(f"    📚 Searching for papers by: {prof_name}")
            
            response = self.session.get(url, params=params, timeout=30)
            
            if response.status_code != 200:
                return {
                    "error": f"HTTP {response.status_code}: {response.text[:200]}",
                    "professor": {"name": prof_name, "email": prof_email}
                }
            
            data = response.json()
            
            if "error" in data:
                return {
                    "error": f"API Error: {data['error']}",
                    "professor": {"name": prof_name, "email": prof_email}
                }
            
            if "organic_results" not in data or not data["organic_results"]:
                return {
                    "error": f"No papers found for {prof_name}",
                    "professor": {"name": prof_name, "email": prof_email}
                }
            
            # Extract and sort papers by citation count
            papers = []
            for i, result in enumerate(data["organic_results"]):
                # Get citation count if available
                cited_by_count = 0
                if "inline_links" in result and "cited_by" in result["inline_links"]:
                    cited_by_count = result["inline_links"]["cited_by"].get("total", 0)
                
                paper = {
                    "title": result.get("title", "N/A"),
                    "authors": result.get("publication_info", {}).get("summary", "N/A"),
                    "publication_info": result.get("publication_info", {}).get("summary", "N/A"),
                    "snippet": result.get("snippet", "N/A"),
                    "cited_by": cited_by_count,
                    "link": result.get("link", "N/A")
                }
                papers.append(paper)
            
            # Sort by citation count (descending) and take top 5
            papers_sorted = sorted(papers, key=lambda x: x["cited_by"], reverse=True)
            top_papers = papers_sorted[:5]
            
            print(f"    📊 Found {len(papers)} papers, top cited: {top_papers[0]['cited_by'] if top_papers else 0}")
            
            return {
                "papers": top_papers,
                "total_papers_found": len(papers)
            }
            
        except requests.exceptions.Timeout:
            return {"error": "Request timed out"}
        except requests.exceptions.RequestException as e:
            return {"error": f"Request failed: {str(e)}"}
        except Exception as e:
            return {"error": f"Unexpected error: {str(e)}"}
    
    def generate_research_summary_with_ai(self, prof_name: str, papers: List[Dict]) -> Dict:
        """Use AI to generate research summary from papers"""
        try:
            if not papers:
                return {
                    "research_summary": "",
                    "research_keywords": [],
                    "research_areas": []
                }
            
            # Prepare papers text for AI
            papers_text = ""
            for i, paper in enumerate(papers[:5]):  # Use top 5 papers
                papers_text += f"\n{i+1}. {paper['title']}\n"
                if paper.get('snippet') and paper['snippet'] != 'N/A':
                    papers_text += f"   Abstract/Snippet: {paper['snippet']}\n"
                papers_text += f"   Citations: {paper['cited_by']}\n"
            
            prompt = f"""
            Analyze the following research papers from Professor {prof_name} and generate a research summary.

            PAPERS:
            {papers_text}

            Generate a JSON response with:
            {{
                "research_summary": "2-3 sentence summary of their main research focus and contributions",
                "research_keywords": ["list", "of", "key", "research", "terms"],
                "research_areas": ["broader", "research", "areas", "they", "work", "in"]
            }}

            Focus on:
            - Main research themes and methodologies
            - Key technical areas (AI, machine learning, computer vision, etc.)
            - Application domains
            - Notable contributions or innovations

            Make it concise but informative.
            """
            
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400,
                temperature=0.1
            )
            
            result = json.loads(response.choices[0].message.content)
            return result
            
        except Exception as e:
            print(f"    AI research summary error: {e}")
            return {
                "research_summary": "",
                "research_keywords": [],
                "research_areas": []
            }
    
    def scrape_complete_faculty_data(self, faculty_page_url: str) -> List[Dict]:
        """Main function to scrape complete faculty data using integrated approach"""
        print(f"🎯 INTEGRATED APPROACH: Basic Info + Google Scholar Papers + AI Research Summary")
        print(f"Scraping faculty page: {faculty_page_url}")
        print(f"Settings: LIMIT={FACULTY_LINKS_LIMIT}, DELAY={REQUEST_DELAY}s, SCHOLAR_DELAY={SCHOLAR_REQUEST_DELAY}s")
        
        # Get the faculty directory page
        soup = self.get_page_content(faculty_page_url)
        if not soup:
            return []
        
        # Extract individual faculty profile URLs
        faculty_links = self.extract_faculty_links(soup, faculty_page_url)
        print(f"Found {len(faculty_links)} potential faculty profile links")
        
        # Debug: print first few links
        print("Sample links found:")
        for i, link in enumerate(faculty_links[:5]):
            print(f"  {i+1}. {link}")
        
        professors = []
        
        for i, profile_url in enumerate(faculty_links):
            print(f"\nProcessing {i+1}/{len(faculty_links)}: {profile_url}")
            
            # Step 1: Get basic professor data (name, email, title)
            profile_soup = self.get_page_content(profile_url)
            if not profile_soup:
                print(f"  ❌ Failed to fetch page")
                continue
            
            basic_data = self.extract_professor_basic_data(profile_soup, profile_url)
            if not basic_data:
                continue
            
            # Step 2: Get research papers from Google Scholar
            print(f"  🔍 Fetching papers for {basic_data['name']}...")
            papers_result = self.get_professor_papers_direct_search(
                basic_data['name'], 
                basic_data['email']
            )
            
            # Step 3: Generate research summary with AI
            if "papers" in papers_result:
                print(f"  🤖 Generating research summary...")
                research_summary = self.generate_research_summary_with_ai(
                    basic_data['name'], 
                    papers_result['papers']
                )
            else:
                print(f"  ⚠️  No papers found, skipping research summary")
                research_summary = {
                    "research_summary": "",
                    "research_keywords": [],
                    "research_areas": []
                }
            
            # Combine all data
            complete_prof_data = {
                'name': basic_data['name'],
                'email': basic_data['email'],
                'title': basic_data['title'],
                'profile_url': basic_data['profile_url'],
                'research_summary': research_summary['research_summary'],
                'research_keywords': research_summary['research_keywords'],
                'research_areas': research_summary['research_areas'],
                'top_papers': papers_result.get('papers', []),
                'total_papers_found': papers_result.get('total_papers_found', 0),
                'data_sources': {
                    'basic_info': 'web_scraping_ai_parsing',
                    'papers': 'google_scholar_api',
                    'research_summary': 'ai_generated'
                },
                'scraping_notes': {
                    'ai_confidence': basic_data['ai_confidence'],
                    'papers_error': papers_result.get('error', None)
                }
            }
            
            professors.append(complete_prof_data)
            
            print(f"  ✅ Complete profile for {basic_data['name']}: {len(papers_result.get('papers', []))} papers")
            
            # Be respectful - add delay between requests
            time.sleep(REQUEST_DELAY)
            
            # Additional delay after Google Scholar requests
            if "papers" in papers_result:
                time.sleep(SCHOLAR_REQUEST_DELAY)
        
        return professors


def main():
    print(f"🎯 INTEGRATED FACULTY SCRAPER CONFIGURATION:")
    print(f"   Faculty URL: {FACULTY_PAGE_URL}")
    print(f"   Links Limit: {FACULTY_LINKS_LIMIT}")
    print(f"   Request Delay: {REQUEST_DELAY}s")
    print(f"   Scholar API Delay: {SCHOLAR_REQUEST_DELAY}s")
    print()
    
    # Initialize scraper (API keys loaded from .env)
    scraper = IntegratedFacultyScraper()
    
    # Check if required API keys are available
    if not scraper.client.api_key:
        print("❌ OPENAI_API_KEY not found in environment variables")
        return
    
    if not scraper.serpapi_key:
        print("❌ SERPAPI_API_KEY not found in environment variables")
        print("   You can still scrape basic info, but won't get research papers")
    
    # Scrape the faculty page
    professors = scraper.scrape_complete_faculty_data(FACULTY_PAGE_URL)
    
    # Output results
    output = {
        "source_url": FACULTY_PAGE_URL,
        "total_professors": len(professors),
        "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "settings": {
            "links_limit": FACULTY_LINKS_LIMIT,
            "request_delay": REQUEST_DELAY,
            "scholar_request_delay": SCHOLAR_REQUEST_DELAY
        },
        "data_sources": {
            "basic_info": "Web scraping + AI parsing",
            "research_papers": "Google Scholar API (SerpAPI)",
            "research_summary": "AI-generated from papers"
        },
        "professors": professors
    }
    
    # Save to JSON file
    with open('complete_professors.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Successfully scraped {len(professors)} complete professor profiles")
    print(f"📁 Results saved to complete_professors.json")
    
    # Print sample data
    if professors:
        print(f"\n📋 Sample professor data:")
        sample = professors[0]
        print(f"  Name: {sample['name']}")
        print(f"  Email: {sample['email']}")
        print(f"  Title: {sample['title']}")
        print(f"  Research Summary: {sample['research_summary'][:100]}...")
        print(f"  Research Keywords: {sample['research_keywords'][:5]}")
        print(f"  Top Papers: {len(sample['top_papers'])} papers")
        print(f"  Total Papers Found: {sample['total_papers_found']}")


if __name__ == "__main__":
    main()