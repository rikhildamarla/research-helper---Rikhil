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
FACULTY_PAGE_URL = "https://www.eecs.mit.edu/role/faculty-cs/"
FACULTY_LINKS_LIMIT = 5  # Maximum number of faculty to process
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
    
    def find_all_faculty_emails_and_names(self, soup: BeautifulSoup, faculty_page_url: str) -> List[Dict]:
        """Find ALL faculty emails and their associated names using AI analysis of raw page content"""
        print("🔍 Searching for all .edu emails and using AI to match names...")
        
        # Get the full page text for AI analysis
        page_text = soup.get_text()
        clean_page_text = re.sub(r'\s+', ' ', page_text).strip()
        
        # Find all .edu emails first - improved regex
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]*\.edu\b'
        all_emails = re.findall(email_pattern, page_text, re.IGNORECASE)
        print(f"   Found {len(all_emails)} .edu emails in page")
        
        # Also try to find emails in HTML attributes and JavaScript
        html_content = str(soup)
        # Look for emails in href attributes
        mailto_pattern = r'mailto:([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]*\.edu)'
        mailto_emails = re.findall(mailto_pattern, html_content, re.IGNORECASE)
        all_emails.extend(mailto_emails)
        
        # Look for obfuscated emails (common pattern: user [at] domain [dot] edu)
        obfuscated_pattern = r'([A-Za-z0-9._%+-]+)\s*(?:\[at\]|@)\s*([A-Za-z0-9.-]*)\s*(?:\[dot\]|\.)\s*edu'
        obfuscated_emails = re.findall(obfuscated_pattern, clean_page_text, re.IGNORECASE)
        for user, domain in obfuscated_emails:
            email = f"{user}@{domain}.edu"
            all_emails.append(email)
        
        print(f"   Total emails found (including mailto and obfuscated): {len(all_emails)}")
        
        # Remove duplicates and filter
        unique_emails = []
        seen = set()
        for email in all_emails:
            email_lower = email.lower().strip()
            if email_lower not in seen and self.is_faculty_email(email_lower):
                seen.add(email_lower)
                unique_emails.append(email)
        
        print(f"   Filtered to {len(unique_emails)} faculty emails")
        
        # If no emails found, try alternative approach: look for faculty names and construct emails
        if not unique_emails:
            print("   No direct emails found, trying to extract names and construct emails...")
            faculty_data = self.extract_names_and_construct_emails(soup, faculty_page_url)
        else:
            # Use AI to analyze the entire page and match emails to names
            faculty_data = self.extract_email_name_pairs_with_ai(clean_page_text, unique_emails)
        
        return faculty_data[:FACULTY_LINKS_LIMIT]
    
    def extract_names_and_construct_emails(self, soup: BeautifulSoup, base_url: str) -> List[Dict]:
        """Extract faculty names and try to construct their email addresses"""
        print("   Extracting faculty names to construct emails...")
        
        # Common selectors for faculty names on university pages
        name_selectors = [
            '.faculty-name', '.person-name', '.profile-name',
            'h2 a', 'h3 a', 'h4 a',  # Common heading patterns
            '.faculty-card h2', '.faculty-card h3',
            '.person-card .name', '.person-title',
            'td a[href*="faculty"]', 'td a[href*="people"]',  # Table-based layouts
        ]
        
        faculty_names = []
        
        for selector in name_selectors:
            elements = soup.select(selector)
            for element in elements:
                name = element.get_text().strip()
                if self.is_valid_professor_name(name):
                    # Try to get associated URL for more context
                    link = element.get('href', '') if element.name == 'a' else ''
                    if link and not link.startswith('http'):
                        link = urljoin(base_url, link)
                    
                    faculty_names.append({
                        'name': name,
                        'profile_url': link,
                        'source_selector': selector
                    })
        
        # Remove duplicates
        seen_names = set()
        unique_faculty = []
        for faculty in faculty_names:
            name_key = faculty['name'].lower()
            if name_key not in seen_names:
                seen_names.add(name_key)
                unique_faculty.append(faculty)
        
        print(f"   Found {len(unique_faculty)} potential faculty names")
        
        # Construct email addresses
        domain = urlparse(base_url).netloc
        if domain.startswith('www.'):
            domain = domain[4:]
        
        faculty_with_emails = []
        for faculty in unique_faculty:
            # Try common email patterns
            name_parts = faculty['name'].lower().split()
            if len(name_parts) >= 2:
                first_name = name_parts[0]
                last_name = name_parts[-1]
                
                # Common email patterns
                email_patterns = [
                    f"{first_name}.{last_name}@{domain}",
                    f"{first_name}{last_name}@{domain}",
                    f"{first_name[0]}{last_name}@{domain}",
                    f"{last_name}@{domain}",
                ]
                
                # Use the first pattern as most likely
                constructed_email = email_patterns[0]
                
                faculty_with_emails.append({
                    'name': faculty['name'],
                    'email': constructed_email,
                    'profile_url': faculty['profile_url'],
                    'source': 'name_extraction_email_construction',
                    'confidence': 'low',  # Since these are constructed, not found
                    'email_patterns_tried': email_patterns
                })
        
        return faculty_with_emails
    
    def is_faculty_email(self, email: str) -> bool:
        """Check if email looks like a faculty email (not admin/generic)"""
        email_lower = email.lower()
        
        # Skip obvious admin/generic emails
        skip_patterns = [
            'info@', 'contact@', 'admin@', 'webmaster@', 'support@',
            'help@', 'noreply@', 'no-reply@', 'postmaster@', 'admissions@',
            'registrar@', 'bursar@', 'communications@', 'marketing@',
            'events@', 'news@', 'media@', 'press@', 'alumni@'
        ]
        
        for pattern in skip_patterns:
            if email_lower.startswith(pattern):
                return False
        
        # Skip emails that look like mailing lists or generic department emails
        generic_keywords = [
            'mailing', 'list', 'newsletter', 'announcements', 'updates',
            'department', 'office', 'committee', 'board', 'council'
        ]
        
        for keyword in generic_keywords:
            if keyword in email_lower:
                return False
        
        return True
    
    def extract_email_name_pairs_with_ai(self, page_text: str, emails: List[str]) -> List[Dict]:
        """Use AI to analyze the entire page content and extract email-name pairs"""
        try:
            # Limit page text size for AI processing
            if len(page_text) > 12000:
                page_text = page_text[:12000] + "..."
            
            # Create email list for the prompt
            email_list = "\n".join(f"- {email}" for email in emails[:20])  # Limit to first 20 emails
            
            prompt = f"""
            You are analyzing a faculty page to match email addresses with professor names.

            FACULTY PAGE TEXT:
            "{page_text}"

            EMAIL ADDRESSES FOUND:
            {email_list}

            Your task: For each email address, find the corresponding professor's name from the page content.

            Return ONLY a JSON array with this structure:
            [
                {{
                    "email": "professor@university.edu",
                    "name": "Professor Full Name",
                    "confidence": "high|medium|low"
                }},
                ...
            ]

            IMPORTANT RULES:
            1. Look for REAL PERSON NAMES (First Last, like "John Smith", "Maria Garcia")
            2. IGNORE generic terms like "Artificial Intelligence", "Programming Languages", "Computer Science"
            3. IGNORE department names, research areas, or field names
            4. If you can't find a real person's name for an email, SKIP that email entirely
            5. The name should be someone who could actually be a professor
            6. Look for context clues like "Professor X", "Dr. Y", or names near the email addresses
            7. Only include entries where you found a real person's name

            Focus on finding actual human names, not research areas or departments.
            """
            
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000,
                temperature=0.1
            )
            
            # Parse the AI response
            try:
                result = json.loads(response.choices[0].message.content)
                faculty_data = []
                
                for entry in result:
                    email = entry.get('email', '').strip()
                    name = entry.get('name', '').strip()
                    confidence = entry.get('confidence', 'medium')
                    
                    # Validate the name
                    if (email and name and 
                        self.is_valid_professor_name(name) and 
                        email in emails):
                        
                        faculty_data.append({
                            'name': name,
                            'email': email,
                            'source': 'ai_page_analysis',
                            'confidence': confidence
                        })
                        print(f"   ✅ AI Found: {name} ({email}) - {confidence} confidence")
                    else:
                        print(f"   ❌ AI returned invalid: {name} ({email})")
                
                return faculty_data
                
            except json.JSONDecodeError as e:
                print(f"   ❌ AI returned invalid JSON: {e}")
                return []
                
        except Exception as e:
            print(f"   ❌ AI analysis error: {e}")
            return []
    
    def is_valid_professor_name(self, name: str) -> bool:
        """Validate that a name looks like a real professor's name"""
        if not name or len(name) < 3:
            return False
        
        # Remove titles
        clean_name = re.sub(r'^(Prof(?:essor)?|Dr\.?)\s+', '', name).strip()
        words = clean_name.split()
        
        # Must have at least 2 words (first and last name)
        if len(words) < 2:
            return False
        
        # Check if it's a generic term (not a person's name)
        generic_terms = [
            'artificial intelligence', 'machine learning', 'computer science',
            'programming languages', 'software engineering', 'data science',
            'information science', 'computer systems', 'algorithms',
            'theoretical computer science', 'human computer interaction',
            'computer graphics', 'computer vision', 'robotics',
            'cybersecurity', 'networks', 'databases', 'quantum computing',
            'integrated circuits', 'game theory', 'computational fabrication',
            'medical devices', 'quantum materials', 'eng thesis',
            'interim vice', 'schwarzman college', 'sibley webster',
            'ellen swallow', 'norbert wiener'  # These might be building/award names
        ]
        
        name_lower = clean_name.lower()
        for term in generic_terms:
            if term in name_lower:
                return False
        
        # Check if words look like names (start with capital, rest lowercase)
        first_two_words = words[:2]
        for word in first_two_words:
            if len(word) < 2:
                return False
            # Allow for names like "McDonald" or "O'Connor"
            if not re.match(r'^[A-Z][a-zA-Z\']*$', word):
                return False
        
        return True
    
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
        """Main function to scrape complete faculty data using DIRECT EMAIL APPROACH"""
        print(f"🎯 DIRECT EMAIL APPROACH: Find all .edu emails + names on faculty page")
        print(f"Scraping faculty page: {faculty_page_url}")
        print(f"Settings: LIMIT={FACULTY_LINKS_LIMIT}, DELAY={REQUEST_DELAY}s, SCHOLAR_DELAY={SCHOLAR_REQUEST_DELAY}s")
        
        # Get the faculty directory page
        soup = self.get_page_content(faculty_page_url)
        if not soup:
            return []
        
        # Find all faculty emails and names directly from the page
        faculty_data = self.find_all_faculty_emails_and_names(soup, faculty_page_url)
        print(f"\n📧 Found {len(faculty_data)} faculty with email+name pairs")
        
        if not faculty_data:
            print("❌ No faculty emails found on the page")
            return []
        
        professors = []
        
        for i, faculty_info in enumerate(faculty_data):
            print(f"\nProcessing {i+1}/{len(faculty_data)}: {faculty_info['name']} ({faculty_info['email']})")
            
            # Step 1: Get research papers from Google Scholar
            print(f"  🔍 Fetching papers for {faculty_info['name']}...")
            papers_result = self.get_professor_papers_direct_search(
                faculty_info['name'], 
                faculty_info['email']
            )
            
            # Step 2: Generate research summary with AI
            if "papers" in papers_result:
                print(f"  🤖 Generating research summary...")
                research_summary = self.generate_research_summary_with_ai(
                    faculty_info['name'], 
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
                'name': faculty_info['name'],
                'email': faculty_info['email'],
                'title': '',  # Not extracted in this approach
                'profile_url': faculty_info.get('profile_url', faculty_page_url),  # Source page
                'research_summary': research_summary['research_summary'],
                'research_keywords': research_summary['research_keywords'],
                'research_areas': research_summary['research_areas'],
                'top_papers': papers_result.get('papers', []),
                'total_papers_found': papers_result.get('total_papers_found', 0),
                'data_sources': {
                    'basic_info': 'faculty_page_email_extraction',
                    'papers': 'google_scholar_api',
                    'research_summary': 'ai_generated'
                },
                'scraping_notes': {
                    'extraction_method': faculty_info.get('source', 'direct_email_search'),
                    'confidence': faculty_info.get('confidence', 'unknown'),
                    'papers_error': papers_result.get('error', None)
                }
            }
            
            professors.append(complete_prof_data)
            
            print(f"  ✅ Complete profile: {len(papers_result.get('papers', []))} papers")
            
            # Be respectful - add delay between requests
            time.sleep(REQUEST_DELAY)
            
            # Additional delay after Google Scholar requests
            if "papers" in papers_result:
                time.sleep(SCHOLAR_REQUEST_DELAY)
        
        return professors


def main():
    print(f"🎯 DIRECT EMAIL FACULTY SCRAPER CONFIGURATION:")
    print(f"   Faculty URL: {FACULTY_PAGE_URL}")
    print(f"   Faculty Limit: {FACULTY_LINKS_LIMIT}")
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
            "faculty_limit": FACULTY_LINKS_LIMIT,
            "request_delay": REQUEST_DELAY,
            "scholar_request_delay": SCHOLAR_REQUEST_DELAY
        },
        "data_sources": {
            "basic_info": "Direct email extraction from faculty page",
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
        print(f"  Research Summary: {sample['research_summary'][:100]}..." if sample['research_summary'] else "  Research Summary: (none)")
        print(f"  Research Keywords: {sample['research_keywords'][:5]}")
        print(f"  Top Papers: {len(sample['top_papers'])} papers")
        print(f"  Total Papers Found: {sample['total_papers_found']}")


if __name__ == "__main__":
    main()