import json
import os
import time
import imaplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import ssl
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv
import re

# Load environment variables
load_dotenv()

class ProfessorEmailGenerator:
    def __init__(self):
        """Initialize the email generator with OpenAI and Gmail credentials"""
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.gmail_email = "rikhil.rdamarla@gmail.com"
        self.gmail_password = os.getenv("EMAIL_APP_PW")
        
        # Email template settings
        self.sender_name = "Rikhil Damarla"
        self.sender_phone = "+1 925-694-2662"
        self.research_topic = "Can Financial Predictive Models Detect Early Signs of Gentrification Risk for Vulnerable Communities?"
        self.resume_file = "Rikhil Damarla-RESUME.pdf"
        self.email_template_file = "email-template.txt"
        
        # Track processed professors to avoid duplicates
        self.processed_professors = set()
        
    def load_email_template(self) -> str:
        """Load the email template from external file"""
        try:
            if not os.path.exists(self.email_template_file):
                raise FileNotFoundError(f"Email template file '{self.email_template_file}' not found")
            
            with open(self.email_template_file, 'r', encoding='utf-8') as f:
                template_content = f.read().strip()
            
            print(f"✅ Email template loaded from {self.email_template_file}")
            return template_content
            
        except Exception as e:
            print(f"❌ Error loading email template: {e}")
            print(f"   Please ensure '{self.email_template_file}' exists in the current directory")
            raise
        
    def load_all_professors(self, directory_path: str) -> list:
        """Load all professors from JSON files in the directory"""
        professors = []
        directory = Path(directory_path)
        
        if not directory.exists():
            print(f"❌ Directory '{directory_path}' not found")
            return []
        
        json_files = list(directory.glob("*.json"))
        print(f"📁 Found {len(json_files)} JSON files in {directory_path}")
        
        for json_file in json_files:
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if 'professors' in data and isinstance(data['professors'], list):
                    for prof in data['professors']:
                        if prof.get('name') and prof.get('email'):
                            # Add source file info
                            prof['source_file'] = json_file.name
                            prof['source_url'] = data.get('source_url', '')
                            professors.append(prof)
                
                print(f"   ✅ Loaded {len(data.get('professors', []))} professors from {json_file.name}")
                
            except Exception as e:
                print(f"   ❌ Error loading {json_file.name}: {e}")
        
        print(f"📊 Total professors loaded: {len(professors)}")
        return professors
    
    def get_professor_last_name(self, full_name: str) -> str:
        """Extract last name from full name"""
        name_parts = full_name.strip().split()
        return name_parts[-1] if name_parts else full_name
    
    def select_best_paper(self, professor: dict) -> dict:
        """Select the most relevant paper for gentrification research"""
        papers = professor.get('top_papers', [])
        
        if not papers:
            return None
        
        # Keywords related to gentrification, urban planning, economics, finance
        relevant_keywords = [
            'housing', 'urban', 'neighborhood', 'gentrification', 'displacement',
            'real estate', 'property', 'economic', 'finance', 'financial',
            'prediction', 'model', 'risk', 'community', 'demographic',
            'spatial', 'geographic', 'policy', 'development', 'inequality',
            'machine learning', 'data', 'analysis', 'forecasting'
        ]
        
        # Score papers based on relevance
        scored_papers = []
        for paper in papers:
            title = paper.get('title', '').lower()
            snippet = paper.get('snippet', '').lower()
            combined_text = f"{title} {snippet}"
            
            relevance_score = 0
            for keyword in relevant_keywords:
                relevance_score += combined_text.count(keyword.lower())
            
            # Also consider citation count
            citations = paper.get('cited_by', 0)
            total_score = relevance_score * 10 + (citations / 100)  # Weight relevance more than citations
            
            scored_papers.append({
                'paper': paper,
                'relevance_score': relevance_score,
                'total_score': total_score
            })
        
        # Sort by total score and return the best one
        scored_papers.sort(key=lambda x: x['total_score'], reverse=True)
        return scored_papers[0]['paper'] if scored_papers else papers[0]
    
    def generate_personalized_email(self, professor: dict) -> dict:
        """Generate a personalized email using GPT-4"""
        try:
            # Load email template from file
            template_content = self.load_email_template()
            
            # Get professor info
            prof_name = professor['name']
            last_name = self.get_professor_last_name(prof_name)
            
            # Select best paper
            selected_paper = self.select_best_paper(professor)
            
            # Prepare professor context for AI
            prof_context = f"""
            Professor: {prof_name}
            Email: {professor['email']}
            Research Summary: {professor.get('research_summary', 'N/A')}
            Research Keywords: {', '.join(professor.get('research_keywords', []))}
            Research Areas: {', '.join(professor.get('research_areas', []))}
            """
            
            paper_context = ""
            if selected_paper:
                paper_context = f"""
                Selected Paper: {selected_paper.get('title', 'N/A')}
                Paper Abstract/Snippet: {selected_paper.get('snippet', 'N/A')}
                Citations: {selected_paper.get('cited_by', 0)}
                """
            
            # Format the template with the context
            prompt = template_content.format(
                prof_context=prof_context,
                paper_context=paper_context
            )
            
            response = self.client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
                temperature=0.3
            )
            
            email_content = response.choices[0].message.content.strip()
            
            # Add bold formatting to key phrases
            email_content = self.add_bold_formatting(email_content)
            
            return {
                'professor_name': prof_name,
                'professor_email': professor['email'],
                'last_name': last_name,
                'email_content': email_content,
                'selected_paper_title': selected_paper.get('title', 'N/A') if selected_paper else 'N/A',
                'source_file': professor.get('source_file', ''),
                'success': True
            }
            
        except Exception as e:
            print(f"   ❌ Error generating email for {professor['name']}: {e}")
            return {
                'professor_name': professor['name'],
                'professor_email': professor['email'],
                'error': str(e),
                'success': False
            }
    
    def add_bold_formatting(self, email_content: str) -> str:
        """Add HTML bold formatting to key phrases"""
        # Key phrases to make bold
        bold_phrases = [
            'Financial Predictive Models',
            'Gentrification Risk',
            'Vulnerable Communities',
            '15 minute chat',
            'research journey',
            'contributing to this field'
        ]
        
        for phrase in bold_phrases:
            # Use word boundaries to avoid partial matches
            pattern = r'\b' + re.escape(phrase) + r'\b'
            email_content = re.sub(pattern, f'<strong>{phrase}</strong>', email_content, flags=re.IGNORECASE)
        
        return email_content
    
    def attach_resume(self, msg):
        """Attach the resume PDF to the email message"""
        try:
            if not os.path.exists(self.resume_file):
                print(f"   ⚠️  Resume file '{self.resume_file}' not found. Email will be sent without attachment.")
                return False
            
            with open(self.resume_file, "rb") as attachment:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(attachment.read())
            
            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition',
                f'attachment; filename= {self.resume_file}',
            )
            
            msg.attach(part)
            return True
            
        except Exception as e:
            print(f"   ❌ Error attaching resume: {e}")
            return False
    
    def create_gmail_draft(self, professor_data: dict) -> bool:
        """Create a Gmail draft for the professor"""
        try:
            # Create the email message
            msg = MIMEMultipart('mixed')
            msg['From'] = self.gmail_email
            msg['To'] = professor_data['professor_email']
            msg['Subject'] = f"Research question & Mentorship advice request"
            
            # Create a multipart alternative for text/html content
            msg_alternative = MIMEMultipart('alternative')
            
            # Create HTML version of the email
            html_content = f"""
            <html>
                <body style="font-family: Arial, sans-serif; font-size: 14px; line-height: 1.6;">
                    {professor_data['email_content'].replace(chr(10), '<br>')}
                </body>
            </html>
            """
            
            # Create plain text version (remove HTML tags)
            text_content = re.sub(r'<[^>]+>', '', professor_data['email_content'])
            
            # Attach text and HTML parts to alternative
            text_part = MIMEText(text_content, 'plain')
            html_part = MIMEText(html_content, 'html')
            
            msg_alternative.attach(text_part)
            msg_alternative.attach(html_part)
            
            # Attach the alternative part to main message
            msg.attach(msg_alternative)
            
            # Attach resume PDF
            resume_attached = self.attach_resume(msg)
            if resume_attached:
                print(f"   ✅ Resume attached successfully")
            
            # Connect to Gmail IMAP and save draft
            context = ssl.create_default_context()
            with imaplib.IMAP4_SSL("imap.gmail.com", 993, ssl_context=context) as imap:
                imap.login(self.gmail_email, self.gmail_password)
                imap.select('[Gmail]/Drafts')
                
                message_bytes = msg.as_bytes()
                imap.append('[Gmail]/Drafts', r'(\Draft)', None, message_bytes)
            
            return True
            
        except Exception as e:
            print(f"   ❌ Error creating Gmail draft for {professor_data['professor_name']}: {e}")
            return False
    
    def generate_all_emails(self, directory_path: str = "professor-info", create_drafts: bool = True):
        """Main function to generate emails for all professors"""
        print(f"🎯 PROFESSOR EMAIL GENERATOR")
        print(f"   Directory: {directory_path}")
        print(f"   Research Topic: {self.research_topic}")
        print(f"   Resume File: {self.resume_file}")
        print(f"   Email Template: {self.email_template_file}")
        print(f"   Create Gmail Drafts: {create_drafts}")
        print()
        
        # Check if email template file exists
        if not os.path.exists(self.email_template_file):
            print(f"❌ Email template file '{self.email_template_file}' not found in current directory.")
            print(f"   Please create this file with your email template content.")
            return
        
        # Check if resume file exists
        if not os.path.exists(self.resume_file):
            print(f"⚠️  Resume file '{self.resume_file}' not found in current directory.")
            print(f"   Emails will be generated without the resume attachment.")
            print()
        
        # Check API keys
        if not self.client.api_key:
            print("❌ OPENAI_API_KEY not found in environment variables")
            return
        
        if create_drafts and not self.gmail_password:
            print("❌ EMAIL_APP_PW not found in environment variables")
            print("   Set create_drafts=False to only generate emails without creating drafts")
            return
        
        # Load all professors
        professors = self.load_all_professors(directory_path)
        
        if not professors:
            print("❌ No professors found in the directory")
            return
        
        print(f"\n📧 Generating personalized emails for {len(professors)} professors...")
        
        # Generate emails
        successful_emails = []
        failed_emails = []
        successful_drafts = 0
        
        for i, professor in enumerate(professors):
            print(f"\nProcessing {i+1}/{len(professors)}: {professor['name']} ({professor.get('source_file', 'unknown')})")
            
            # Generate email
            email_result = self.generate_personalized_email(professor)
            
            if email_result['success']:
                print(f"   ✅ Email generated successfully")
                successful_emails.append(email_result)
                
                # Create Gmail draft if requested
                if create_drafts:
                    if self.create_gmail_draft(email_result):
                        print(f"   ✅ Gmail draft created")
                        successful_drafts += 1
                    else:
                        print(f"   ❌ Failed to create Gmail draft")
                
                # Show preview
                preview = email_result['email_content'][:200].replace('\n', ' ')
                print(f"   📧 Preview: {preview}...")
                
            else:
                print(f"   ❌ Failed to generate email")
                failed_emails.append(email_result)
            
            # Rate limiting - be respectful to OpenAI API
            time.sleep(1)
        
        # Save results to file
        results = {
            "generation_summary": {
                "total_professors": len(professors),
                "successful_emails": len(successful_emails),
                "failed_emails": len(failed_emails),
                "successful_drafts": successful_drafts,
                "research_topic": self.research_topic,
                "resume_file": self.resume_file,
                "email_template_file": self.email_template_file,
                "resume_attached": os.path.exists(self.resume_file),
                "generated_at": time.strftime("%Y-%m-%d %H:%M:%S")
            },
            "successful_emails": successful_emails,
            "failed_emails": failed_emails
        }
        
        with open('generated_emails.json', 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        # Final summary
        print(f"\n{'='*80}")
        print(f"📊 EMAIL GENERATION COMPLETE")
        print(f"{'='*80}")
        print(f"✅ Successfully generated: {len(successful_emails)}/{len(professors)} emails")
        print(f"📧 Gmail drafts created: {successful_drafts}/{len(successful_emails)}")
        print(f"❌ Failed: {len(failed_emails)} emails")
        print(f"📎 Resume attached: {'Yes' if os.path.exists(self.resume_file) else 'No'}")
        print(f"📧 Template file: {self.email_template_file}")
        print(f"💾 Results saved to: generated_emails.json")
        
        if create_drafts and successful_drafts > 0:
            print(f"\n📬 Check your Gmail drafts folder - {successful_drafts} emails are ready to send!")
        
        if failed_emails:
            print(f"\n❌ Failed professors:")
            for failed in failed_emails[:5]:  # Show first 5 failures
                print(f"   - {failed['professor_name']}: {failed.get('error', 'Unknown error')}")


def main():
    """Main function to run the email generator"""
    generator = ProfessorEmailGenerator()
    
    # Generate emails and create Gmail drafts
    generator.generate_all_emails(
        directory_path="professor-info",
        create_drafts=True  # Set to False if you only want to generate emails without creating drafts
    )


if __name__ == "__main__":
    main()