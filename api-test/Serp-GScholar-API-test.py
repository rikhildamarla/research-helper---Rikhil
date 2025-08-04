import requests
import json
import time
from urllib.parse import urlencode

from dotenv import load_dotenv
import os

def test_api_key(api_key):
    """Test if the API key works with a simple query"""
    url = "https://serpapi.com/search"
    params = {
        "engine": "google_scholar",
        "q": "machine learning",
        "api_key": api_key,
        "num": 1
    }
    
    try:
        print("Testing API key...")
        response = requests.get(url, params=params, timeout=15)
        print(f"Test response status: {response.status_code}")
        
        if response.status_code == 401:
            return False, "Invalid API key"
        elif response.status_code == 429:
            return False, "Rate limit exceeded"
        elif response.status_code != 200:
            return False, f"HTTP {response.status_code}: {response.text[:100]}"
        
        data = response.json()
        if "error" in data:
            return False, f"API Error: {data['error']}"
        
        return True, "API key is working!"
        
    except Exception as e:
        return False, f"Test failed: {str(e)}"

def get_professor_papers_direct_search(prof_name, prof_email, api_key, num_papers=10):
    """
    Alternative approach: Search directly for professor's papers using author search
    """
    url = "https://serpapi.com/search"
    
    # Search for papers by this author
    params = {
        "engine": "google_scholar",
        "q": f'author:"{prof_name}"',
        "api_key": api_key,
        "num": num_papers,
        "start": 0
    }
    
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    })
    
    try:
        print(f"Searching for papers by: {prof_name}")
        print(f"Search query: author:\"{prof_name}\"")
        print(f"Request URL: {url}?{urlencode(params)}")
        
        response = session.get(url, params=params, timeout=30)
        print(f"Response status: {response.status_code}")
        
        if response.status_code != 200:
            return {
                "error": f"HTTP {response.status_code}: {response.text[:200]}",
                "professor": {"name": prof_name, "email": prof_email}
            }
        
        data = response.json()
        print(f"API Response keys: {list(data.keys())}")
        
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
                "rank": i + 1,
                "title": result.get("title", "N/A"),
                "authors": result.get("publication_info", {}).get("summary", "N/A"),
                "publication_info": result.get("publication_info", {}).get("summary", "N/A"),
                "snippet": result.get("snippet", "N/A"),
                "cited_by": cited_by_count,
                "link": result.get("link", "N/A"),
                "result_id": result.get("result_id", "N/A")
            }
            papers.append(paper)
        
        # Sort by citation count (descending) and take top 3
        papers_sorted = sorted(papers, key=lambda x: x["cited_by"], reverse=True)
        top_papers = papers_sorted[:3]
        
        # Re-rank them as 1, 2, 3
        for i, paper in enumerate(top_papers):
            paper["rank"] = i + 1
        
        result = {
            "professor": {
                "name": prof_name,
                "email": prof_email,
                "search_method": "Direct author search",
                "total_papers_found": len(papers)
            },
            "top_papers": top_papers,
            "all_papers": papers_sorted  # Include all papers for reference
        }
        
        return result
        
    except requests.exceptions.Timeout:
        return {
            "error": "Request timed out. Try again or check your internet connection.",
            "professor": {"name": prof_name, "email": prof_email}
        }
    except requests.exceptions.ConnectionError:
        return {
            "error": "Connection error. Check your internet connection or try again later.",
            "professor": {"name": prof_name, "email": prof_email}
        }
    except requests.exceptions.RequestException as e:
        return {
            "error": f"Request failed: {str(e)}",
            "professor": {"name": prof_name, "email": prof_email}
        }
    except Exception as e:
        return {
            "error": f"Unexpected error: {str(e)}",
            "professor": {"name": prof_name, "email": prof_email}
        }

def try_profile_search_with_timeout(prof_name, prof_email, api_key):
    """
    Try the profile search but with a very short timeout to avoid hanging
    """
    url = "https://serpapi.com/search"
    params = {
        "engine": "google_scholar_profiles",
        "mauthors": prof_name,
        "api_key": api_key
    }
    
    try:
        print(f"Attempting profile search for: {prof_name} (5 second timeout)")
        response = requests.get(url, params=params, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            if "profiles" in data and data["profiles"]:
                return data["profiles"][0].get("author_id")
        
        return None
        
    except:
        print("Profile search timed out or failed, using direct search instead")
        return None

def get_papers_by_author_id(author_id, api_key):
    """Get papers using author ID if we have it"""
    url = "https://serpapi.com/search"
    params = {
        "engine": "google_scholar_author",
        "author_id": author_id,
        "api_key": api_key,
        "num": 10
    }
    
    try:
        response = requests.get(url, params=params, timeout=30)
        if response.status_code == 200:
            data = response.json()
            if "articles" in data:
                return data["articles"][:3]  # Top 3 articles
        return None
    except:
        return None

def get_professor_top_papers(prof_name, prof_email, api_key, num_papers=3):
    """
    Main function that tries profile search first, then falls back to direct search
    """
    
    # Try to get author ID with short timeout
    author_id = try_profile_search_with_timeout(prof_name, prof_email, api_key)
    
    if author_id:
        print(f"Found author ID: {author_id}, trying to get papers...")
        papers = get_papers_by_author_id(author_id, api_key)
        
        if papers:
            formatted_papers = []
            for i, paper in enumerate(papers):
                formatted_paper = {
                    "rank": i + 1,
                    "title": paper.get("title", "N/A"),
                    "authors": paper.get("authors", "N/A"),
                    "publication_info": paper.get("publication", "N/A"),
                    "year": paper.get("year", "N/A"),
                    "cited_by": paper.get("cited_by", {}).get("value", 0),
                    "link": paper.get("link", "N/A")
                }
                formatted_papers.append(formatted_paper)
            
            return {
                "professor": {
                    "name": prof_name,
                    "email": prof_email,
                    "search_method": "Google Scholar Profile",
                    "author_id": author_id
                },
                "top_papers": formatted_papers
            }
    
    # Fallback to direct search
    print("Using direct search method...")
    return get_professor_papers_direct_search(prof_name, prof_email, api_key, 20)

def print_results(result):
    """Pretty print the results"""
    print("="*80)
    print("PROFESSOR RESEARCH PAPERS")
    print("="*80)
    
    prof = result["professor"]
    print(f"Name: {prof['name']}")
    print(f"Email: {prof['email']}")
    
    if "search_method" in prof:
        print(f"Search Method: {prof['search_method']}")
    if "author_id" in prof:
        print(f"Google Scholar Author ID: {prof['author_id']}")
    if "total_papers_found" in prof:
        print(f"Total Papers Found: {prof['total_papers_found']}")
    
    print("\n" + "="*80)
    print("TOP 3 RESEARCH PAPERS (by citation count)")
    print("="*80)
    
    if "error" in result:
        print(f"ERROR: {result['error']}")
        return
    
    if not result.get("top_papers"):
        print("No papers found.")
        return
    
    for paper in result["top_papers"]:
        print(f"\n{paper['rank']}. {paper['title']}")
        print(f"   Authors: {paper['authors']}")
        if paper.get('publication_info'):
            print(f"   Publication: {paper['publication_info']}")
        if paper.get('year'):
            print(f"   Year: {paper['year']}")
        print(f"   Citations: {paper['cited_by']}")
        if paper.get('link') and paper['link'] != 'N/A':
            print(f"   Link: {paper['link']}")

# Main execution
if __name__ == "__main__":
    # Configuration
    PROF_NAME = "Maneesh Agrawala"
    PROF_EMAIL = "maneesh@cs.stanford.edu"
    load_dotenv()
    API_KEY = os.getenv("SERPAPI_API_KEY")
    
    # Test API key first
    print("="*60)
    print("TESTING API KEY")
    print("="*60)
    is_working, message = test_api_key(API_KEY)
    print(message)
    
    if not is_working:
        print("\n❌ API key test failed. Please check your key or try again later.")
        exit(1)
    
    print("\n✅ API key is working! Proceeding with professor search...\n")
    
    # Fetch and display results
    result = get_professor_top_papers(PROF_NAME, PROF_EMAIL, API_KEY)
    print_results(result)
    
    # Save to JSON file
    with open("professor_papers.json", "w") as f:
        json.dump(result, f, indent=2)
    
    print(f"\nResults saved to 'professor_papers.json'")