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

import csv
import os
from pathlib import Path

# Load environment variables
load_dotenv()

# CONFIGURATION VARIABLES
FACULTY_PAGE_URL = "https://www.cs.princeton.edu/people/faculty"
FACULTY_LINKS_LIMIT = 5  # Maximum number of faculty to process
REQUEST_DELAY = 2  # Seconds to wait between requests (be respectful)
SCHOLAR_REQUEST_DELAY = 3  # Seconds to wait between Google Scholar requests
LINK_ANALYSIS_LIMIT = 10  # Maximum number of profile links to analyze

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
        
        # Track visited URLs to prevent infinite recursion
        self.visited_urls = set()
        
    def get_page_content(self, url: str) -> Optional[BeautifulSoup]:
        """Fetch and parse a web page"""
        try:
            # Add to visited URLs
            self.visited_urls.add(url)
            
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
    
    def find_relevant_faculty_links(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        """Use AI to identify relevant faculty profile links from the page"""
        print("🔗 Analyzing page links to find faculty profiles...")
        
        # Extract all links from the page
        all_links = []
        for link in soup.find_all('a', href=True):
            href = link.get('href')
            if not href:
                continue
            
            # Convert relative URLs to absolute
            if not href.startswith('http'):
                href = urljoin(base_url, href)
            
            # Skip already visited URLs
            if href in self.visited_urls:
                continue
            
            # Get link text and context
            link_text = link.get_text().strip()
            
            # Get some surrounding context
            parent = link.parent
            context = parent.get_text().strip()[:200] if parent else ""
            
            all_links.append({
                'url': href,
                'text': link_text,
                'context': context
            })
        
        if not all_links:
            print("   No links found on page")
            return []
        
        print(f"   Found {len(all_links)} total links")
        
        # Use AI to filter for faculty profile links
        try:
            # Prepare links data for AI analysis (limit to avoid token limits)
            links_sample = all_links[:50]  # Analyze first 50 links
            links_text = ""
            for i, link in enumerate(links_sample):
                links_text += f"\n{i+1}. URL: {link['url']}\n"
                links_text += f"   Text: {link['text']}\n"
                links_text += f"   Context: {link['context'][:100]}...\n"
            
            prompt = f"""
            You are analyzing links from a faculty directory page to identify which ones lead to individual faculty profiles.

            LINKS FROM PAGE:
            {links_text}

            Your task: Identify which URLs are most likely to be individual faculty member profiles.

            Return ONLY a JSON array of the most relevant URLs (maximum 10):
            [
                "https://example.edu/faculty/professor-name",
                "https://example.edu/people/john-smith",
                ...
            ]

            LOOK FOR:
            - Links with professor names (John Smith, Maria Garcia, etc.)
            - URLs containing patterns like /faculty/, /people/, /profiles/, /staff/
            - Link text that looks like person names
            - Context mentioning titles like "Professor", "Dr.", "PhD"

            AVOID:
            - Generic links (About, Contact, Home, etc.)
            - Administrative links
            - External links to other domains
            - Course or curriculum links
            - News or event links
            - Social media links

            Return ONLY the URL strings, no explanations.
            """
            
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
                temperature=0.1
            )
            
            try:
                relevant_urls = json.loads(response.choices[0].message.content)
                
                # Validate URLs
                valid_urls = []
                for url in relevant_urls:
                    if isinstance(url, str) and url.startswith('http') and url not in self.visited_urls:
                        valid_urls.append(url)
                
                print(f"   AI identified {len(valid_urls)} relevant faculty profile links")
                return valid_urls[:LINK_ANALYSIS_LIMIT]
                
            except json.JSONDecodeError as e:
                print(f"   ❌ AI returned invalid JSON for link analysis: {e}")
                return []
                
        except Exception as e:
            print(f"   ❌ AI link analysis error: {e}")
            return []
    
    def extract_faculty_info_from_profile(self, profile_url: str) -> Optional[Dict]:
        """Extract faculty information from an individual profile page"""
        print(f"   📄 Analyzing profile: {profile_url}")
        
        soup = self.get_page_content(profile_url)
        if not soup:
            return None
        
        page_text = soup.get_text()
        clean_page_text = re.sub(r'\s+', ' ', page_text).strip()
        
        # Use AI to extract faculty information from the profile page
        try:
            # Limit page text for AI processing
            if len(clean_page_text) > 8000:
                clean_page_text = clean_page_text[:8000] + "..."
            
            prompt = f"""
            You are analyzing an individual faculty member's profile page to extract their information.

            PROFILE PAGE TEXT:
            "{clean_page_text}"

            Extract the following information and return as JSON:
            {{
                "name": "Full Name of Professor",
                "email": "email@university.edu (if found)",
                "title": "Professor/Associate Professor/Assistant Professor title",
                "department": "Department name",
                "research_interests": ["list", "of", "research", "areas"],
                "confidence": "high|medium|low"
            }}

            RULES:
            1. Look for a clear person's name (First Last format)
            2. Find their email address if present (look for @university.edu pattern)
            3. Identify their academic title/position
            4. Extract research interests or specializations
            5. If you can't find clear information, set confidence to "low"
            6. If this doesn't appear to be a faculty profile, return null for name

            Focus on accuracy - only extract clear, identifiable information.
            """
            
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400,
                temperature=0.1
            )
            
            try:
                result = json.loads(response.choices[0].message.content)
                
                # Validate the extracted information
                name = result.get('name', '').strip()
                email = result.get('email', '').strip()
                
                if not name or not self.is_valid_professor_name(name):
                    print(f"      ❌ Invalid or missing name: {name}")
                    return None
                
                # If no email found, try to construct one
                if not email or email == "email@university.edu (if found)":
                    domain = urlparse(profile_url).netloc
                    if domain.startswith('www.'):
                        domain = domain[4:]
                    
                    name_parts = name.lower().split()
                    if len(name_parts) >= 2:
                        first_name = name_parts[0]
                        last_name = name_parts[-1]
                        email = f"{first_name}.{last_name}@{domain}"
                        result['email'] = email
                        result['email_constructed'] = True
                
                result['profile_url'] = profile_url
                result['source'] = 'individual_profile_analysis'
                
                print(f"      ✅ Extracted: {name} ({email})")
                return result
                
            except json.JSONDecodeError as e:
                print(f"      ❌ AI returned invalid JSON: {e}")
                return None
                
        except Exception as e:
            print(f"      ❌ Profile analysis error: {e}")
            return None
    
    def scrape_faculty_from_links(self, faculty_page_url: str) -> List[Dict]:
        """Fallback method: scrape faculty info by analyzing individual profile links"""
        print(f"\n🔄 FALLBACK: Link Analysis Approach")
        print(f"Analyzing embedded links for faculty profiles...")
        
        # Get the main faculty page
        soup = self.get_page_content(faculty_page_url)
        if not soup:
            return []
        
        # Find relevant faculty profile links
        faculty_links = self.find_relevant_faculty_links(soup, faculty_page_url)
        
        if not faculty_links:
            print("❌ No relevant faculty profile links found")
            return []
        
        print(f"📋 Processing {len(faculty_links)} faculty profile links...")
        
        faculty_data = []
        
        for i, profile_url in enumerate(faculty_links):
            if len(faculty_data) >= FACULTY_LINKS_LIMIT:
                print(f"   Reached limit of {FACULTY_LINKS_LIMIT} profiles")
                break
            
            print(f"   Processing {i+1}/{len(faculty_links)}: {profile_url}")
            
            # Extract faculty info from individual profile
            faculty_info = self.extract_faculty_info_from_profile(profile_url)
            
            if faculty_info:
                faculty_data.append({
                    'name': faculty_info['name'],
                    'email': faculty_info['email'],
                    'title': faculty_info.get('title', ''),
                    'department': faculty_info.get('department', ''),
                    'profile_url': faculty_info['profile_url'],
                    'research_interests': faculty_info.get('research_interests', []),
                    'source': 'link_analysis_fallback',
                    'confidence': faculty_info.get('confidence', 'medium'),
                    'email_constructed': faculty_info.get('email_constructed', False)
                })
                print(f"      ✅ Added to results")
            else:
                print(f"      ❌ Could not extract valid faculty info")
            
            # Respectful delay
            time.sleep(REQUEST_DELAY)
        
        print(f"📊 Link analysis found {len(faculty_data)} faculty members")
        return faculty_data
    
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
        """Main function to scrape complete faculty data using DIRECT EMAIL APPROACH with link analysis fallback"""
        print(f"🎯 DIRECT EMAIL APPROACH: Find all .edu emails + names on faculty page")
        print(f"Scraping faculty page: {faculty_page_url}")
        print(f"Settings: LIMIT={FACULTY_LINKS_LIMIT}, DELAY={REQUEST_DELAY}s, SCHOLAR_DELAY={SCHOLAR_REQUEST_DELAY}s")
        
        # Clear visited URLs for this scraping session
        self.visited_urls.clear()
        
        # STEP 1: Try original direct email extraction approach (UNCHANGED)
        print(f"\n📧 STEP 1: Direct Email Extraction Approach (Original Logic)")
        soup = self.get_page_content(faculty_page_url)
        if not soup:
            return []
        
        # Find all faculty emails and names directly from the page (ORIGINAL METHOD)
        faculty_data = self.find_all_faculty_emails_and_names(soup, faculty_page_url)
        print(f"\n📧 Found {len(faculty_data)} faculty with email+name pairs")
        
        # STEP 2: If no results, try link analysis fallback
        if len(faculty_data) == 0:
            print(f"\n🔄 STEP 2: Link Analysis Fallback (no direct emails found)")
            faculty_data = self.scrape_faculty_from_links(faculty_page_url)
        
        if not faculty_data:
            print("❌ No faculty data found with either approach")
            return []
        
        print(f"\n📊 Processing {len(faculty_data)} faculty members for papers and research summaries...")
        
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
                'title': faculty_info.get('title', ''),  # Not extracted in direct approach
                'department': faculty_info.get('department', ''),
                'profile_url': faculty_info.get('profile_url', faculty_page_url),  # Source page or individual profile
                'research_summary': research_summary['research_summary'],
                'research_keywords': research_summary['research_keywords'],
                'research_areas': research_summary['research_areas'],
                'research_interests': faculty_info.get('research_interests', []),
                'top_papers': papers_result.get('papers', []),
                'total_papers_found': papers_result.get('total_papers_found', 0),
                'data_sources': {
                    'basic_info': faculty_info.get('source', 'faculty_page_email_extraction'),
                    'papers': 'google_scholar_api',
                    'research_summary': 'ai_generated'
                },
                'scraping_notes': {
                    'extraction_method': faculty_info.get('source', 'direct_email_search'),
                    'confidence': faculty_info.get('confidence', 'unknown'),
                    'email_constructed': faculty_info.get('email_constructed', False),
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


# Add this enhanced error handling around your AI JSON parsing

def extract_faculty_from_emails_with_ai(self, content, emails):
    """Enhanced version with better error handling"""
    try:
        # Your existing prompt construction code here...
        
        print(f"🤖 Sending request to AI with {len(emails)} emails...")
        
        response = self.client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a faculty data extraction expert..."},
                {"role": "user", "content": your_prompt}
            ],
            temperature=0
        )
        
        ai_response = response.choices[0].message.content.strip()
        
        # Enhanced debugging
        print(f"📝 AI Response Length: {len(ai_response)} characters")
        print(f"📝 AI Response Preview: {ai_response[:200]}...")
        
        # Check if response is empty
        if not ai_response:
            print("❌ AI returned empty response")
            return []
            
        # Check if response looks like JSON
        if not (ai_response.startswith('[') or ai_response.startswith('{')):
            print(f"❌ AI response doesn't look like JSON: {ai_response[:100]}...")
            return []
        
        # Try to parse JSON with better error handling
        try:
            faculty_data = json.loads(ai_response)
        except json.JSONDecodeError as je:
            print(f"❌ JSON Parse Error: {je}")
            print(f"   Raw response: {ai_response}")
            
            # Try to extract JSON from response if it's wrapped in text
            import re
            json_match = re.search(r'(\[.*\]|\{.*\})', ai_response, re.DOTALL)
            if json_match:
                try:
                    faculty_data = json.loads(json_match.group(1))
                    print("✅ Successfully extracted JSON from wrapped response")
                except:
                    print("❌ Failed to parse extracted JSON")
                    return []
            else:
                return []
        
        print(f"✅ Successfully parsed {len(faculty_data)} faculty records")
        return faculty_data
        
    except Exception as e:
        print(f"❌ Error in AI extraction: {e}")
        print(f"   Error type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        return []

# Enhanced main function with better error handling
def main():
    print(f"🎯 ENHANCED FACULTY SCRAPER - BATCH PROCESSING FROM CSV")
    print(f"   CSV File: faculty-urls.csv")
    print(f"   Output Folder: professor-info/")
    print(f"   Faculty Limit per URL: {FACULTY_LINKS_LIMIT}")
    print(f"   Request Delay: {REQUEST_DELAY}s")
    print(f"   Scholar API Delay: {SCHOLAR_REQUEST_DELAY}s")
    print()
    
    # Check if CSV file exists
    csv_file = "faculty-urls.csv"
    if not os.path.exists(csv_file):
        print(f"❌ CSV file '{csv_file}' not found in current directory")
        return
    
    # Create output directory
    output_dir = Path("professor-info")
    output_dir.mkdir(exist_ok=True)
    
    # Read URLs from CSV
    faculty_urls = []
    try:
        with open(csv_file, 'r', encoding='utf-8') as file:
            csv_reader = csv.reader(file)
            for row in csv_reader:
                if row and row[0].strip():
                    url = row[0].strip()
                    if url.startswith('http'):
                        faculty_urls.append(url)
    except Exception as e:
        print(f"❌ Error reading CSV file: {e}")
        return
    
    if not faculty_urls:
        print(f"❌ No valid URLs found in {csv_file}")
        return
    
    print(f"📋 Found {len(faculty_urls)} valid URLs to process")
    
    # Initialize scraper
    scraper = IntegratedFacultyScraper()
    
    # Process each URL with enhanced error handling
    for i, faculty_url in enumerate(faculty_urls):
        print(f"\n{'='*80}")
        print(f"🌐 PROCESSING URL {i+1}/{len(faculty_urls)}: {faculty_url}")
        print(f"{'='*80}")
        
        try:
            # Add longer delay between requests in batch mode
            if i > 0:
                print(f"⏳ Waiting {REQUEST_DELAY * 3}s between universities...")
                time.sleep(REQUEST_DELAY * 3)
            
            # Generate filename
            from urllib.parse import urlparse
            parsed_url = urlparse(faculty_url)
            domain = parsed_url.netloc.replace('www.', '')
            path = parsed_url.path.replace('/', '_').replace('-', '_')
            if not path or path == '_':
                path = 'faculty'
            filename = f"{domain}{path}.json"
            filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
            filepath = output_dir / filename
            
            print(f"📁 Output file: {filepath}")
            
            # Try scraping with timeout protection
            professors = []
            try:
                professors = scraper.scrape_complete_faculty_data(faculty_url)
            except Exception as scrape_error:
                print(f"❌ Scraping error for {faculty_url}: {scrape_error}")
                continue
            
            if professors:
                # Create output data
                output = {
                    "source_url": faculty_url,
                    "total_professors": len(professors),
                    "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "scraping_approach": "Direct email extraction with link analysis fallback",
                    "professors": professors
                }
                
                # Save to JSON file
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(output, f, indent=2, ensure_ascii=False)
                
                print(f"✅ Successfully scraped {len(professors)} professors")
                print(f"📁 Saved to: {filepath}")
                
                # Print sample
                if professors:
                    sample = professors[0]
                    print(f"📋 Sample: {sample['name']} ({sample['email']})")
            else:
                print(f"❌ No professors found for {faculty_url}")
                
        except Exception as e:
            print(f"❌ Critical error processing {faculty_url}: {e}")
            import traceback
            traceback.print_exc()
            continue


if __name__ == "__main__":
    main()