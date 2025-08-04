import imaplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import ssl

from dotenv import load_dotenv
import os

load_dotenv()

def create_gmail_draft():
    # Gmail IMAP settings
    IMAP_SERVER = "imap.gmail.com"
    IMAP_PORT = 993
    
    # Your credentials (use app password)
    EMAIL = "periodicstockpriceupdatebot@gmail.com"
    PASSWORD = os.getenv("EMAIL_APP_PW")  # App password, not regular password

    
    # Create the email message
    msg = MIMEMultipart('alternative')
    msg['From'] = EMAIL
    msg['To'] = "recipient@example.com"
    msg['Subject'] = "Test Subject - Gmail Draft via Python"
    
    # Create text and HTML versions
    text_content = """
    This is test content for the draft email.
    
    This email was created using Python and saved directly to Gmail drafts.
    It demonstrates how to create a draft that appears in your Gmail drafts folder.
    
    Best regards,
    Your Python Script
    """
    
    html_content = """
    <html>
        <body>
            <h2>Test Email Draft</h2>
            <p>This is <strong>test content</strong> for the draft email.</p>
            
            <p>This email was created using <em>Python</em> and saved directly to Gmail drafts.</p>
            <p>It demonstrates how to create a draft that appears in your Gmail drafts folder.</p>
            
            <p>Best regards,<br>
            Your Python Script</p>
        </body>
    </html>
    """
    
    # Attach parts
    text_part = MIMEText(text_content, 'plain')
    html_part = MIMEText(html_content, 'html')
    
    msg.attach(text_part)
    msg.attach(html_part)
    
    try:
        # Connect to Gmail IMAP
        context = ssl.create_default_context()
        with imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT, ssl_context=context) as imap:
            print("Connecting to Gmail...")
            imap.login(EMAIL, PASSWORD)
            print("Login successful!")
            
            # Select the drafts folder
            # Gmail uses '[Gmail]/Drafts' for the drafts folder
            imap.select('[Gmail]/Drafts')
            
            # Add the draft flag and save to drafts folder
            message_bytes = msg.as_bytes()
            imap.append('[Gmail]/Drafts', r'(\Draft)', None, message_bytes)
            
            print("✅ Draft successfully saved to Gmail drafts folder!")
            print("📧 Check your Gmail drafts - you should see the email there.")
            
    except imaplib.IMAP4.error as e:
        print(f"❌ IMAP Error: {e}")
        print("Make sure you're using an app password, not your regular password.")
    except Exception as e:
        print(f"❌ Error: {e}")


print("Creating Gmail draft...")
print("Make sure to update EMAIL and PASSWORD variables with your credentials!")
print()

create_gmail_draft()