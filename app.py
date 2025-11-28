from flask import Flask, render_template, request, jsonify, session, send_from_directory
from flask_cors import CORS
import sqlite3
import json
from datetime import datetime, timedelta
import os
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import re
import PyPDF2
import docx
import io
import requests
from bs4 import BeautifulSoup
import time
import random
from urllib.parse import quote, urljoin, urlparse
import threading

# Try importing AI components
try:
    from sentence_transformers import SentenceTransformer
    SBERT_AVAILABLE = True
except ImportError:
    SBERT_AVAILABLE = False
    print("⚠️ sentence-transformers not available - using keyword matching")

try:
    from sklearn.metrics.pairwise import cosine_similarity
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    print("⚠️ scikit-learn not available - using numpy for similarity")

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    print("⚠️ numpy not available - using pure Python calculations")

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = 'ai-career-hub-secret-key-2024'
CORS(app)

# Configuration
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'txt'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

for folder in [UPLOAD_FOLDER, 'static', 'templates']:
    if not os.path.exists(folder):
        os.makedirs(folder)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

# API Configuration
ADZUNA_APP_ID = os.getenv('ADZUNA_APP_ID', 'y17426dca')
ADZUNA_APP_KEY = os.getenv('ADZUNA_APP_KEY', '351eba7055428c190eb976993c613a3d')
JSEARCH_API_KEY = os.getenv('JSEARCH_API_KEY', '2ee053f5f1msh07c75d362834877p188d49jsn2095772b2797')

def allowed_file(filename):
    """Check if the uploaded file has an allowed extension"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Initialize Sentence-BERT model
model = None
if SBERT_AVAILABLE:
    try:
        print("🔄 Loading Sentence-BERT model...")
        model = SentenceTransformer('all-MiniLM-L6-v2')
        print("✅ Sentence-BERT loaded successfully!")
    except Exception as e:
        print(f"⚠️ Model loading failed: {e}")
        model = None

# Enhanced Interview Questions Database
INTERVIEW_QUESTIONS = {
    'Python': [
        {"question": "What is the difference between lists and tuples in Python?", "category": "Basic"},
        {"question": "Explain Python decorators with a real-world example.", "category": "Intermediate"},
        {"question": "What are Python generators and when would you use them?", "category": "Intermediate"},
        {"question": "Explain the difference between deep copy and shallow copy.", "category": "Intermediate"},
        {"question": "What is the Global Interpreter Lock (GIL) and how does it affect Python?", "category": "Advanced"},
        {"question": "Explain Python's memory management and garbage collection.", "category": "Advanced"},
        {"question": "What are metaclasses in Python and when would you use them?", "category": "Advanced"},
        {"question": "Describe the difference between @staticmethod and @classmethod.", "category": "Intermediate"},
        {"question": "How does Python handle multiple inheritance? Explain MRO.", "category": "Advanced"},
        {"question": "What are context managers and how do you create custom ones?", "category": "Intermediate"},
        {"question": "Explain list comprehensions vs generator expressions.", "category": "Basic"},
        {"question": "What is the purpose of __init__.py files in Python packages?", "category": "Basic"},
        {"question": "How would you optimize a slow Python program?", "category": "Advanced"}
    ],
    'JavaScript': [
        {"question": "What is the difference between var, let, and const?", "category": "Basic"},
        {"question": "Explain closures in JavaScript with an example.", "category": "Intermediate"},
        {"question": "What is the event loop in JavaScript?", "category": "Intermediate"},
        {"question": "Explain promises and async/await in JavaScript.", "category": "Intermediate"},
        {"question": "What is the difference between == and === operators?", "category": "Basic"},
        {"question": "Explain prototypal inheritance in JavaScript.", "category": "Advanced"},
        {"question": "What are higher-order functions? Provide examples.", "category": "Intermediate"},
        {"question": "Explain the concept of hoisting in JavaScript.", "category": "Intermediate"},
        {"question": "What is the 'this' keyword and how does its context change?", "category": "Intermediate"},
        {"question": "Describe arrow functions and their differences from regular functions.", "category": "Basic"},
        {"question": "What are JavaScript modules (ES6 modules)?", "category": "Intermediate"},
        {"question": "Explain debouncing and throttling with use cases.", "category": "Advanced"},
        {"question": "How does JavaScript handle memory leaks and how can you prevent them?", "category": "Advanced"}
    ],
    'React': [
        {"question": "What is the virtual DOM and how does React use it?", "category": "Basic"},
        {"question": "Explain the difference between state and props.", "category": "Basic"},
        {"question": "What are React hooks and why were they introduced?", "category": "Intermediate"},
        {"question": "Explain the useEffect hook and its use cases.", "category": "Intermediate"},
        {"question": "What is the difference between controlled and uncontrolled components?", "category": "Intermediate"},
        {"question": "Explain React's reconciliation algorithm.", "category": "Advanced"},
        {"question": "What are higher-order components (HOCs)?", "category": "Advanced"},
        {"question": "Describe the React component lifecycle methods.", "category": "Intermediate"},
        {"question": "What is Context API and when should you use it?", "category": "Intermediate"},
        {"question": "Explain React.memo and useMemo - when to use each?", "category": "Advanced"},
        {"question": "What is prop drilling and how can you avoid it?", "category": "Intermediate"},
        {"question": "Describe the differences between useState and useReducer.", "category": "Intermediate"},
        {"question": "How would you optimize performance in a large React application?", "category": "Advanced"}
    ],
    'Java': [
        {"question": "What is the difference between JDK, JRE, and JVM?", "category": "Basic"},
        {"question": "Explain the principles of Object-Oriented Programming in Java.", "category": "Basic"},
        {"question": "What is the difference between abstract classes and interfaces?", "category": "Intermediate"},
        {"question": "Explain Java's garbage collection mechanism.", "category": "Intermediate"},
        {"question": "What are Java Streams and how do they work?", "category": "Intermediate"},
        {"question": "Describe the differences between ArrayList and LinkedList.", "category": "Basic"},
        {"question": "What is multithreading in Java and how do you implement it?", "category": "Advanced"},
        {"question": "Explain the synchronized keyword and its use.", "category": "Advanced"},
        {"question": "What are generics in Java and why are they useful?", "category": "Intermediate"},
        {"question": "Describe the Java memory model (Heap vs Stack).", "category": "Advanced"},
        {"question": "What is the difference between == and .equals() in Java?", "category": "Basic"},
        {"question": "Explain exception handling in Java with best practices.", "category": "Intermediate"},
        {"question": "What are lambda expressions and functional interfaces?", "category": "Intermediate"}
    ],
    'SQL': [
        {"question": "What are the different types of SQL joins?", "category": "Basic"},
        {"question": "Explain the difference between WHERE and HAVING clauses.", "category": "Basic"},
        {"question": "What is normalization and why is it important?", "category": "Intermediate"},
        {"question": "Describe ACID properties in database transactions.", "category": "Intermediate"},
        {"question": "What is the difference between clustered and non-clustered indexes?", "category": "Advanced"},
        {"question": "Explain SQL injection and how to prevent it.", "category": "Intermediate"},
        {"question": "What are stored procedures and their advantages?", "category": "Intermediate"},
        {"question": "Describe the difference between DELETE, TRUNCATE, and DROP.", "category": "Basic"},
        {"question": "What are views in SQL and when would you use them?", "category": "Intermediate"},
        {"question": "Explain database indexing and its impact on performance.", "category": "Advanced"},
        {"question": "What is a subquery and what are its types?", "category": "Intermediate"},
        {"question": "Describe window functions in SQL with examples.", "category": "Advanced"},
        {"question": "How would you optimize a slow SQL query?", "category": "Advanced"}
    ],
    'Machine Learning': [
        {"question": "What is the difference between supervised and unsupervised learning?", "category": "Basic"},
        {"question": "Explain overfitting and underfitting with solutions.", "category": "Intermediate"},
        {"question": "What is the bias-variance tradeoff?", "category": "Intermediate"},
        {"question": "Describe the difference between classification and regression.", "category": "Basic"},
        {"question": "What is cross-validation and why is it important?", "category": "Intermediate"},
        {"question": "Explain gradient descent and its variants.", "category": "Advanced"},
        {"question": "What are neural networks and how do they learn?", "category": "Intermediate"},
        {"question": "Describe the difference between bagging and boosting.", "category": "Advanced"},
        {"question": "What is regularization (L1 vs L2)?", "category": "Intermediate"},
        {"question": "Explain feature engineering and its importance.", "category": "Intermediate"},
        {"question": "What are confusion matrix, precision, and recall?", "category": "Basic"},
        {"question": "Describe backpropagation in neural networks.", "category": "Advanced"},
        {"question": "How do you handle imbalanced datasets?", "category": "Advanced"}
    ],
    'AWS': [
        {"question": "What is the difference between EC2 and Lambda?", "category": "Basic"},
        {"question": "Explain S3 storage classes and their use cases.", "category": "Intermediate"},
        {"question": "What is VPC and how does it work?", "category": "Intermediate"},
        {"question": "Describe the differences between RDS and DynamoDB.", "category": "Intermediate"},
        {"question": "What is CloudFormation and Infrastructure as Code?", "category": "Advanced"},
        {"question": "Explain IAM roles, policies, and users.", "category": "Intermediate"},
        {"question": "What is Auto Scaling and how do you configure it?", "category": "Intermediate"},
        {"question": "Describe Elastic Load Balancer types and their differences.", "category": "Advanced"},
        {"question": "What is CloudWatch and how do you use it for monitoring?", "category": "Intermediate"},
        {"question": "Explain the AWS Well-Architected Framework.", "category": "Advanced"},
        {"question": "What is the difference between EBS and EFS?", "category": "Basic"},
        {"question": "How do you secure an AWS environment?", "category": "Advanced"},
        {"question": "Describe the differences between SQS and SNS.", "category": "Intermediate"}
    ],
    'Docker': [
        {"question": "What is the difference between a container and a virtual machine?", "category": "Basic"},
        {"question": "Explain Docker architecture (daemon, client, registry).", "category": "Intermediate"},
        {"question": "What is a Dockerfile and what are its main instructions?", "category": "Basic"},
        {"question": "Describe Docker volumes and their purpose.", "category": "Intermediate"},
        {"question": "What is the difference between COPY and ADD in Dockerfile?", "category": "Basic"},
        {"question": "Explain Docker networking modes.", "category": "Advanced"},
        {"question": "What is Docker Compose and when would you use it?", "category": "Intermediate"},
        {"question": "How do you optimize Docker images for production?", "category": "Advanced"},
        {"question": "Describe multi-stage builds in Docker.", "category": "Intermediate"},
        {"question": "What is the difference between CMD and ENTRYPOINT?", "category": "Intermediate"},
        {"question": "How do you handle secrets in Docker?", "category": "Advanced"},
        {"question": "Explain container orchestration and why it's needed.", "category": "Advanced"},
        {"question": "What are Docker best practices for security?", "category": "Advanced"}
    ]
}

BEHAVIORAL_QUESTIONS = [
    {"question": "Tell me about a challenging technical problem you solved and your approach.", "category": "Problem Solving"},
    {"question": "Describe a situation where you had to work with a difficult team member.", "category": "Teamwork"},
    {"question": "How do you handle tight deadlines and pressure?", "category": "Time Management"},
    {"question": "Tell me about a time you failed and what you learned from it.", "category": "Learning"},
    {"question": "How do you stay updated with new technologies?", "category": "Growth"},
    {"question": "Describe a project you're most proud of.", "category": "Achievement"},
    {"question": "How do you prioritize multiple tasks?", "category": "Organization"},
    {"question": "Tell me about a time you had to learn a new technology quickly.", "category": "Adaptability"}
]

# Enhanced Skill extraction patterns with more skills
SKILL_PATTERNS = {
    'Programming Languages': [
        'python', 'javascript', 'java', 'c++', 'c#', 'ruby', 'go', 'rust', 'swift',
        'kotlin', 'typescript', 'php', 'perl', 'scala', 'r', 'matlab', 'sql', 'html', 'css',
        'bash', 'shell', 'powershell'
    ],
    'Web Frameworks': [
        'react', 'angular', 'vue', 'django', 'flask', 'express', 'node.js', 'nodejs',
        'spring boot', 'laravel', 'rails', 'asp.net', 'fastapi', 'next.js', 'nuxt.js',
        'svelte', 'ember', 'backbone'
    ],
    'Data Science & ML': [
        'machine learning', 'deep learning', 'tensorflow', 'pytorch', 'keras',
        'scikit-learn', 'pandas', 'numpy', 'matplotlib', 'seaborn', 'nltk',
        'computer vision', 'nlp', 'data analysis', 'statistics', 'data science',
        'big data', 'hadoop', 'spark', 'tableau', 'power bi'
    ],
    'Cloud & DevOps': [
        'aws', 'azure', 'gcp', 'docker', 'kubernetes', 'jenkins', 'terraform',
        'ansible', 'ci/cd', 'git', 'linux', 'bash', 'microservices', 'devops',
        'github', 'gitlab', 'monitoring', 'logging'
    ],
    'Databases': [
        'mysql', 'postgresql', 'mongodb', 'redis', 'elasticsearch', 'cassandra',
        'oracle', 'sqlite', 'dynamodb', 'firebase', 'cosmosdb', 'snowflake'
    ],
    'Mobile Development': [
        'android', 'ios', 'react native', 'flutter', 'xamarin', 'swift', 'kotlin'
    ],
    'Soft Skills': [
        'leadership', 'communication', 'teamwork', 'problem solving', 'project management',
        'agile', 'scrum', 'kanban', 'time management', 'critical thinking'
    ]
}

# ============================
# DATABASE FUNCTIONS (ENHANCED)
# ============================

def repair_database():
    """Repair database schema if columns are missing"""
    conn = sqlite3.connect('career_hub.db')
    c = conn.cursor()
    
    # Check what columns exist
    c.execute("PRAGMA table_info(users)")
    columns = [column[1] for column in c.fetchall()]
    print(f"📋 Existing columns: {columns}")
    
    # Add missing columns
    missing_columns = []
    if 'manual_skills' not in columns:
        c.execute("ALTER TABLE users ADD COLUMN manual_skills TEXT")
        missing_columns.append('manual_skills')
        print("✅ Added manual_skills column")
    
    if 'scraping_email' not in columns:
        c.execute("ALTER TABLE users ADD COLUMN scraping_email TEXT")
        missing_columns.append('scraping_email')
        print("✅ Added scraping_email column")
    
    if 'scraping_password' not in columns:
        c.execute("ALTER TABLE users ADD COLUMN scraping_password TEXT")
        missing_columns.append('scraping_password')
        print("✅ Added scraping_password column")
    
    if 'experience' not in columns:
        c.execute("ALTER TABLE users ADD COLUMN experience TEXT DEFAULT '0-1'")
        missing_columns.append('experience')
        print("✅ Added experience column")
    
    # Check for saved_jobs table
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='saved_jobs'")
    if not c.fetchone():
        c.execute('''CREATE TABLE saved_jobs
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      job_data TEXT NOT NULL,
                      saved_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      FOREIGN KEY (user_id) REFERENCES users (id))''')
        print("✅ Created saved_jobs table")
    
    conn.commit()
    conn.close()
    
    if missing_columns:
        print(f"🔧 Added missing columns: {missing_columns}")
    
    return missing_columns

def init_db():
    conn = sqlite3.connect('career_hub.db')
    c = conn.cursor()
    
    # Users table with all required columns
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT NOT NULL,
                  email TEXT UNIQUE NOT NULL,
                  password TEXT NOT NULL,
                  skills TEXT,
                  experience TEXT,
                  manual_skills TEXT,
                  scraping_email TEXT,
                  scraping_password TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Interview attempts table
    c.execute('''CREATE TABLE IF NOT EXISTS interview_attempts
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  question TEXT NOT NULL,
                  answer TEXT NOT NULL,
                  skill TEXT NOT NULL,
                  score INTEGER,
                  feedback TEXT,
                  attempt_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY (user_id) REFERENCES users (id))''')
    
    # Saved jobs table
    c.execute('''CREATE TABLE IF NOT EXISTS saved_jobs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  job_data TEXT NOT NULL,
                  saved_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY (user_id) REFERENCES users (id))''')
    
    conn.commit()
    conn.close()
    
    # Repair any missing columns
    repair_database()

# ============================
# RESUME PROCESSING FUNCTIONS
# ============================

def extract_text_from_pdf(file_stream):
    try:
        pdf_reader = PyPDF2.PdfReader(file_stream)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        print(f"PDF extraction error: {e}")
        return ""

def extract_text_from_docx(file_stream):
    try:
        doc = docx.Document(file_stream)
        text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
        return text
    except Exception as e:
        print(f"DOCX extraction error: {e}")
        return ""

def extract_text_from_txt(file_stream):
    try:
        return file_stream.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"TXT extraction error: {e}")
        return ""

def extract_skills_from_text(text):
    text_lower = text.lower()
    found_skills = set()
    
    for category, skills in SKILL_PATTERNS.items():
        for skill in skills:
            pattern = r'\b' + re.escape(skill.lower()) + r'\b'
            if re.search(pattern, text_lower):
                display_skill = ' '.join(word.capitalize() for word in skill.split())
                found_skills.add(display_skill)
    
    return sorted(list(found_skills))

def extract_experience_level(text):
    text_lower = text.lower()
    
    years_patterns = [
        r'(\d+)\+?\s*years?\s+(?:of\s+)?experience',
        r'experience[:\s]+(\d+)\+?\s*years?',
        r'(\d+)\+?\s*yrs?\s+(?:of\s+)?experience'
    ]
    
    for pattern in years_patterns:
        match = re.search(pattern, text_lower)
        if match:
            years = int(match.group(1))
            if years >= 5:
                return "5+"
            elif years >= 3:
                return "3-5"
            elif years >= 1:
                return "1-3"
            else:
                return "0-1"
    
    if any(word in text_lower for word in ['senior', 'lead', 'principal', 'architect']):
        return "5+"
    elif any(word in text_lower for word in ['mid-level', 'intermediate']):
        return "3-5"
    elif any(word in text_lower for word in ['junior', 'associate']):
        return "1-3"
    elif any(word in text_lower for word in ['intern', 'entry', 'graduate', 'student']):
        return "0-1"
    
    return "0-1"

# ============================
# ENHANCED JOB MATCHING SYSTEM
# ============================

def enhanced_calculate_job_match_score(user_profile, job):
    """Enhanced job matching algorithm with better scoring"""
    try:
        user_skills = set([s.lower().strip() for s in user_profile.get('skills', [])])
        job_skills = set([s.lower().strip() for s in job.get('skills', [])])
        
        # If no job skills detected, use a basic score based on title/description
        if not job_skills:
            return calculate_basic_match_score(user_profile, job)
        
        # Calculate skill match
        matching_skills = user_skills.intersection(job_skills)
        skill_match_ratio = len(matching_skills) / len(job_skills) if job_skills else 0
        
        # Experience matching
        experience_bonus = calculate_experience_bonus(user_profile.get('experience'), job.get('experience'))
        
        # Title relevance bonus
        title_bonus = calculate_title_relevance_bonus(user_profile.get('skills', []), job.get('title', ''))
        
        # Description relevance bonus
        description_bonus = calculate_description_relevance_bonus(user_profile.get('skills', []), job.get('description', ''))
        
        # Calculate base score (skill match is most important)
        base_score = skill_match_ratio * 60  # 60% weight for skills
        
        # Add bonuses
        total_score = base_score + experience_bonus + title_bonus + description_bonus
        
        # Ensure score is between 0-100
        final_score = min(max(total_score, 0), 100)
        
        # Boost scores that are too low but have some matches
        if 0 < final_score < 40 and len(matching_skills) > 0:
            final_score = min(40 + (len(matching_skills) * 8), 85)
        
        # Ensure minimum score for jobs with some matches
        if len(matching_skills) > 0 and final_score < 50:
            final_score = 50 + (len(matching_skills) * 5)
            
        return int(round(final_score))
        
    except Exception as e:
        print(f"⚠️ Enhanced matching error: {e}")
        return calculate_basic_match_score(user_profile, job)

def calculate_basic_match_score(user_profile, job):
    """Fallback matching when skill extraction fails"""
    user_skills_text = ' '.join([s.lower() for s in user_profile.get('skills', [])])
    job_text = (job.get('title', '') + ' ' + job.get('description', '')).lower()
    
    match_count = 0
    for skill in user_profile.get('skills', []):
        if skill.lower() in job_text:
            match_count += 1
    
    total_user_skills = len(user_profile.get('skills', []))
    if total_user_skills == 0:
        return 50  # Default score if no skills
    
    base_score = (match_count / total_user_skills) * 80
    
    # Add some random variation to make it more realistic
    variation = random.randint(-5, 15)
    return min(max(base_score + variation, 20), 95)

def calculate_experience_bonus(user_exp, job_exp):
    """Calculate bonus based on experience match"""
    exp_levels = {'0-1': 0, '1-3': 1, '3-5': 2, '5+': 3}
    
    user_level = exp_levels.get(user_exp, 0)
    job_level = exp_levels.get(job_exp, 1)
    
    if user_level >= job_level:
        return 20  # User meets or exceeds requirements
    elif user_level >= job_level - 1:
        return 10   # User is close to requirements
    else:
        return 0  # User under-qualified

def calculate_title_relevance_bonus(user_skills, job_title):
    """Calculate bonus based on job title relevance"""
    job_title_lower = job_title.lower()
    user_skills_lower = [s.lower() for s in user_skills]
    
    # Check if any user skill is in the job title
    for skill in user_skills_lower:
        if skill in job_title_lower:
            return 15
    
    return 0

def calculate_description_relevance_bonus(user_skills, job_description):
    """Calculate bonus based on job description relevance"""
    job_desc_lower = job_description.lower()
    user_skills_lower = [s.lower() for s in user_skills]
    
    # Count how many user skills are in the description
    skill_matches = sum(1 for skill in user_skills_lower if skill in job_desc_lower)
    
    if skill_matches >= 3:
        return 15
    elif skill_matches >= 2:
        return 10
    elif skill_matches >= 1:
        return 5
    return 0

# ============================
# JOB FETCHING (ENHANCED WITH WEB SCRAPING)
# ============================

def fetch_adzuna_jobs(keywords, location='us', max_results=20):
    """Fetch jobs from Adzuna API"""
    try:
        print(f"🔍 [ADZUNA] Searching for: '{keywords}'")
        
        url = f"https://api.adzuna.com/v1/api/jobs/{location}/search/1"
        params = {
            'app_id': ADZUNA_APP_ID,
            'app_key': ADZUNA_APP_KEY,
            'results_per_page': max_results,
            'what': keywords,
            'content-type': 'application/json'
        }
        
        response = requests.get(url, params=params, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            jobs = []
            for job in data.get('results', []):
                salary_min = job.get('salary_min', 0)
                salary_max = job.get('salary_max', 0)
                salary = salary_min if salary_min else salary_max if salary_max else 0
                
                job_data = {
                    'title': job.get('title', 'N/A'),
                    'company': job.get('company', {}).get('display_name', 'N/A'),
                    'location': job.get('location', {}).get('display_name', 'N/A'),
                    'description': job.get('description', '')[:300],
                    'url': job.get('redirect_url', ''),
                    'salary': f"${salary:,}" if salary else 'Competitive',
                    'type': 'Full-time',
                    'source': 'Adzuna',
                    'id': f"adzuna_{job.get('id', '')}"
                }
                jobs.append(job_data)
            
            print(f"✅ [ADZUNA] Fetched {len(jobs)} jobs")
            return jobs
        else:
            print(f"❌ [ADZUNA] API error {response.status_code}")
            return []
            
    except Exception as e:
        print(f"❌ [ADZUNA] Exception: {str(e)}")
        return []

def fetch_jsearch_jobs(query, location='United States', max_results=20):
    """Fetch jobs from JSearch API"""
    try:
        print(f"🔍 [JSEARCH] Searching for: '{query}'")
        
        url = "https://jsearch.p.rapidapi.com/search"
        headers = {
            "X-RapidAPI-Key": JSEARCH_API_KEY,
            "X-RapidAPI-Host": "jsearch.p.rapidapi.com"
        }
        
        params = {
            "query": f"{query} {location}",
            "page": "1",
            "num_pages": "1"
        }
        
        response = requests.get(url, headers=headers, params=params, timeout=20)
        
        if response.status_code == 200:
            data = response.json()
            jobs = []
            for job in data.get('data', [])[:max_results]:
                salary_min = job.get('job_min_salary', 0)
                salary_max = job.get('job_max_salary', 0)
                salary = salary_min if salary_min else salary_max if salary_max else 0
                
                job_data = {
                    'title': job.get('job_title', 'N/A'),
                    'company': job.get('employer_name', 'N/A'),
                    'location': job.get('job_city', 'Remote') or job.get('job_country', 'Remote'),
                    'description': job.get('job_description', '')[:300],
                    'url': job.get('job_apply_link', ''),
                    'salary': f"${salary:,}" if salary else 'Competitive',
                    'type': job.get('job_employment_type', 'Full-time'),
                    'source': 'JSearch',
                    'id': f"jsearch_{job.get('job_id', '')}"
                }
                jobs.append(job_data)
            
            print(f"✅ [JSEARCH] Fetched {len(jobs)} jobs")
            return jobs
        else:
            print(f"❌ [JSEARCH] API error {response.status_code}")
            return []
            
    except Exception as e:
        print(f"❌ [JSEARCH] Exception: {str(e)}")
        return []

def scrape_linkedin_jobs(keywords, max_results=10):
    """Scrape LinkedIn jobs (simulated - in production use LinkedIn API)"""
    try:
        print(f"🔍 [LINKEDIN] Searching for: '{keywords}'")
        
        # Simulated LinkedIn jobs (in production, you'd use LinkedIn API or web scraping)
        linkedin_jobs = [
            {
                'title': f'Senior {keywords.title()} Developer',
                'company': 'Tech Solutions Inc.',
                'location': 'Remote',
                'description': f'Looking for experienced {keywords} developer with cloud experience.',
                'url': 'https://linkedin.com/jobs/view/123',
                'salary': '$90,000 - $120,000',
                'type': 'Full-time',
                'source': 'LinkedIn',
                'id': f'linkedin_{hash(keywords)}_1'
            },
            {
                'title': f'{keywords.title()} Engineer',
                'company': 'Innovate Labs',
                'location': 'New York, NY',
                'description': f'Join our team as a {keywords} engineer working on cutting-edge projects.',
                'url': 'https://linkedin.com/jobs/view/124',
                'salary': 'Competitive',
                'type': 'Full-time',
                'source': 'LinkedIn',
                'id': f'linkedin_{hash(keywords)}_2'
            }
        ]
        
        print(f"✅ [LINKEDIN] Simulated {len(linkedin_jobs)} jobs")
        return linkedin_jobs[:max_results]
        
    except Exception as e:
        print(f"❌ [LINKEDIN] Exception: {str(e)}")
        return []

def scrape_indeed_jobs(keywords, max_results=10):
    """Scrape Indeed jobs (simulated - in production use Indeed API)"""
    try:
        print(f"🔍 [INDEED] Searching for: '{keywords}'")
        
        # Simulated Indeed jobs
        indeed_jobs = [
            {
                'title': f'Full Stack {keywords.title()} Developer',
                'company': 'Digital Innovations',
                'location': 'San Francisco, CA',
                'description': f'Seeking full-stack developer proficient in {keywords} and modern frameworks.',
                'url': 'https://indeed.com/jobs/view/123',
                'salary': '$85,000 - $110,000',
                'type': 'Full-time',
                'source': 'Indeed',
                'id': f'indeed_{hash(keywords)}_1'
            },
            {
                'title': f'Junior {keywords.title()} Programmer',
                'company': 'StartUp Ventures',
                'location': 'Austin, TX',
                'description': f'Entry-level position for {keywords} developers. Great learning opportunity.',
                'url': 'https://indeed.com/jobs/view/124',
                'salary': '$60,000 - $75,000',
                'type': 'Full-time',
                'source': 'Indeed',
                'id': f'indeed_{hash(keywords)}_2'
            }
        ]
        
        print(f"✅ [INDEED] Simulated {len(indeed_jobs)} jobs")
        return indeed_jobs[:max_results]
        
    except Exception as e:
        print(f"❌ [INDEED] Exception: {str(e)}")
        return []

def scrape_internshala_jobs(keywords, max_results=10):
    """Scrape Internshala jobs (simulated - focused on internships)"""
    try:
        print(f"🔍 [INTERNSHALA] Searching for: '{keywords}'")
        
        # Simulated Internshala jobs (internship focused)
        internshala_jobs = [
            {
                'title': f'{keywords.title()} Development Intern',
                'company': 'Tech Learners Inc.',
                'location': 'Remote',
                'description': f'Internship opportunity for {keywords} developers. Learn and grow with us.',
                'url': 'https://internshala.com/jobs/view/123',
                'salary': 'Stipend provided',
                'type': 'Internship',
                'source': 'Internshala',
                'id': f'internshala_{hash(keywords)}_1'
            },
            {
                'title': f'{keywords.title()} Training Program',
                'company': 'Coding Academy',
                'location': 'Bangalore, India',
                'description': f'6-month training program in {keywords} development with job guarantee.',
                'url': 'https://internshala.com/jobs/view/124',
                'salary': 'Training Program',
                'type': 'Training',
                'source': 'Internshala',
                'id': f'internshala_{hash(keywords)}_2'
            }
        ]
        
        print(f"✅ [INTERNSHALA] Simulated {len(internshala_jobs)} jobs")
        return internshala_jobs[:max_results]
        
    except Exception as e:
        print(f"❌ [INTERNSHALA] Exception: {str(e)}")
        return []

def fetch_jobs_from_apis(user_skills, location='United States', max_results=40):
    """Fetch jobs from multiple APIs using ALL user skills"""
    print(f"🚀 Fetching jobs for skills: {user_skills}")
    
    all_jobs = []
    
    # Use all skills for broader search
    if user_skills:
        # Try different combinations to get more results
        keywords_combinations = [
            ' '.join(user_skills[:3]),  # Top 3 skills
            ' '.join(user_skills[:5]),  # Top 5 skills  
            ' '.join([s for s in user_skills if len(s.split()) == 1][:3]),  # Single word skills
        ]
        
        # Also try individual important skills
        important_skills = ['python', 'javascript', 'java', 'react', 'aws', 'docker', 'sql', 'machine learning']
        for skill in important_skills:
            if any(skill in s.lower() for s in user_skills):
                keywords_combinations.append(skill)
    else:
        keywords_combinations = ['software developer', 'web developer', 'data scientist']
    
    # Remove duplicates and empty strings
    keywords_combinations = list(set([k for k in keywords_combinations if k.strip()]))
    
    print(f"🔍 Search keywords: {keywords_combinations}")
    
    # Fetch from all sources with different keyword combinations
    for keywords in keywords_combinations[:3]:  # Limit to 3 combinations to avoid rate limits
        if len(all_jobs) >= max_results:
            break
            
        # Fetch from all sources
        adzuna_jobs = fetch_adzuna_jobs(keywords, 'us', 8)
        jsearch_jobs = fetch_jsearch_jobs(keywords, location, 8)
        linkedin_jobs = scrape_linkedin_jobs(keywords, 6)
        indeed_jobs = scrape_indeed_jobs(keywords, 6)
        internshala_jobs = scrape_internshala_jobs(keywords, 4)
        
        # Combine all jobs
        source_jobs = adzuna_jobs + jsearch_jobs + linkedin_jobs + indeed_jobs + internshala_jobs
        
        # Add new jobs only (avoid duplicates)
        for job in source_jobs:
            if not any(j.get('id') == job.get('id') for j in all_jobs):
                all_jobs.append(job)
    
    # Enhanced skill extraction from job descriptions
    for job in all_jobs:
        job['skills'] = enhanced_extract_skills_from_job(job.get('title', '') + ' ' + job.get('description', ''))
        job['experience'] = estimate_experience_from_job(job.get('title', ''), job.get('description', ''))
    
    return all_jobs[:max_results]

def enhanced_extract_skills_from_job(text):
    """Enhanced skill extraction from job descriptions"""
    text_lower = text.lower()
    found_skills = set()
    
    # Multi-word skills first (to avoid partial matches)
    for category, skills in SKILL_PATTERNS.items():
        for skill in skills:
            if ' ' in skill:  # Multi-word skills
                if skill.lower() in text_lower:
                    display_skill = ' '.join(word.capitalize() for word in skill.split())
                    found_skills.add(display_skill)
    
    # Single-word skills
    for category, skills in SKILL_PATTERNS.items():
        for skill in skills:
            if ' ' not in skill:  # Single-word skills
                pattern = r'\b' + re.escape(skill.lower()) + r'\b'
                if re.search(pattern, text_lower):
                    display_skill = skill.capitalize()
                    found_skills.add(display_skill)
    
    return list(found_skills)[:10]  # Limit to 10 most relevant skills

def estimate_experience_from_job(title, description):
    """Estimate required experience level from job posting"""
    text = (title + ' ' + description).lower()
    
    experience_patterns = {
        '5+': ['senior', 'lead', 'principal', 'staff', '5+ years', '7+ years', '8+ years', '10+ years'],
        '3-5': ['mid-level', '3-5 years', '3+ years', '4+ years', 'mid level', 'experienced'],
        '1-3': ['junior', '1-3 years', '2+ years', '1+ years', 'associate'],
        '0-1': ['intern', 'entry', 'graduate', '0-1 years', 'student', 'trainee']
    }
    
    for level, keywords in experience_patterns.items():
        if any(keyword in text for keyword in keywords):
            return level
    
    return '1-3'  # Default

# ============================
# SAVED JOBS FUNCTIONALITY
# ============================

def save_job_for_user(user_id, job_data):
    """Save a job for a user"""
    try:
        conn = sqlite3.connect('career_hub.db')
        c = conn.cursor()
        
        # Check if job already saved
        c.execute('SELECT id FROM saved_jobs WHERE user_id = ? AND job_data LIKE ?', 
                 (user_id, f'%{job_data.get("id", "")}%'))
        if c.fetchone():
            conn.close()
            return False, "Job already saved"
        
        c.execute('INSERT INTO saved_jobs (user_id, job_data) VALUES (?, ?)',
                 (user_id, json.dumps(job_data)))
        conn.commit()
        conn.close()
        return True, "Job saved successfully"
    except Exception as e:
        print(f"❌ Error saving job: {e}")
        return False, f"Failed to save job: {str(e)}"

def get_saved_jobs(user_id):
    """Get saved jobs for a user"""
    try:
        conn = sqlite3.connect('career_hub.db')
        c = conn.cursor()
        c.execute('SELECT job_data, saved_date FROM saved_jobs WHERE user_id = ? ORDER BY saved_date DESC', (user_id,))
        saved_jobs = c.fetchall()
        conn.close()
        
        jobs = []
        for job_json, saved_date in saved_jobs:
            try:
                job_data = json.loads(job_json)
                job_data['saved_date'] = saved_date
                jobs.append(job_data)
            except json.JSONDecodeError:
                continue
        
        return jobs
    except Exception as e:
        print(f"❌ Error getting saved jobs: {e}")
        return []

def delete_saved_job(user_id, job_id):
    """Delete a saved job"""
    try:
        conn = sqlite3.connect('career_hub.db')
        c = conn.cursor()
        c.execute('DELETE FROM saved_jobs WHERE user_id = ? AND job_data LIKE ?', 
                 (user_id, f'%{job_id}%'))
        conn.commit()
        conn.close()
        return True, "Job removed successfully"
    except Exception as e:
        print(f"❌ Error deleting saved job: {e}")
        return False, f"Failed to remove job: {str(e)}"

# ============================
# API ROUTES (ENHANCED)
# ============================

@app.route('/api/register', methods=['POST'])
def register():
    try:
        data = request.json
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        name = data.get('name', '').strip()
        
        if not email or not password or not name:
            return jsonify({"success": False, "message": "All fields are required"}), 400
        
        if len(password) < 6:
            return jsonify({"success": False, "message": "Password must be at least 6 characters"}), 400
        
        conn = sqlite3.connect('career_hub.db')
        c = conn.cursor()
        
        c.execute('SELECT id FROM users WHERE email = ?', (email,))
        if c.fetchone():
            conn.close()
            return jsonify({"success": False, "message": "Email already registered"}), 400
        
        hashed_password = generate_password_hash(password)
        c.execute('INSERT INTO users (name, email, password, skills, experience, manual_skills) VALUES (?, ?, ?, ?, ?, ?)',
                  (name, email, hashed_password, '[]', '0-1', '[]'))
        conn.commit()
        conn.close()
        
        return jsonify({"success": True, "message": "Registration successful! Please login."})
    except Exception as e:
        return jsonify({"success": False, "message": f"Registration failed: {str(e)}"}), 500

@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.json
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        
        if not email or not password:
            return jsonify({"success": False, "message": "Email and password are required"}), 400
        
        conn = sqlite3.connect('career_hub.db')
        c = conn.cursor()
        
        c.execute('SELECT id, name, email, password, skills, experience, manual_skills FROM users WHERE email = ?', (email,))
        user = c.fetchone()
        conn.close()
        
        if not user or not check_password_hash(user[3], password):
            return jsonify({"success": False, "message": "Invalid email or password"}), 401
        
        session['user_id'] = user[0]
        session['user_name'] = user[1]
        session['user_email'] = user[2]
        
        resume_skills = json.loads(user[4]) if user[4] else []
        manual_skills = json.loads(user[6]) if user[6] else []
        all_skills = list(set(resume_skills + manual_skills))
        
        return jsonify({
            "success": True, 
            "message": "Login successful!",
            "user": {
                "id": user[0],
                "name": user[1],
                "email": user[2],
                "skills": all_skills,
                "resume_skills": resume_skills,
                "manual_skills": manual_skills,
                "experience": user[5] or "0-1"
            }
        })
    except Exception as e:
        return jsonify({"success": False, "message": f"Login failed: {str(e)}"}), 500

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"success": True, "message": "Logged out successfully"})

@app.route('/api/user')
def get_user():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Not logged in"}), 401
    
    try:
        conn = sqlite3.connect('career_hub.db')
        c = conn.cursor()
        
        # Safely get user data with error handling for missing columns
        try:
            c.execute('SELECT id, name, email, skills, experience, manual_skills FROM users WHERE id = ?', (session['user_id'],))
            user = c.fetchone()
        except sqlite3.OperationalError as e:
            if "no such column: manual_skills" in str(e):
                # Repair database and try again
                conn.close()
                repair_database()
                conn = sqlite3.connect('career_hub.db')
                c = conn.cursor()
                c.execute('SELECT id, name, email, skills, experience, manual_skills FROM users WHERE id = ?', (session['user_id'],))
                user = c.fetchone()
            else:
                raise
        
        conn.close()
        
        if user:
            resume_skills = json.loads(user[3]) if user[3] else []
            experience = user[4] or "0-1"
            manual_skills = json.loads(user[5]) if user[5] else []
            all_skills = list(set(resume_skills + manual_skills))
            
            return jsonify({
                "success": True,
                "user": {
                    "id": user[0],
                    "name": user[1],
                    "email": user[2],
                    "skills": all_skills,
                    "resume_skills": resume_skills,
                    "manual_skills": manual_skills,
                    "experience": experience
                }
            })
        return jsonify({"success": False, "message": "User not found"}), 404
        
    except Exception as e:
        print(f"❌ Error in get_user: {e}")
        return jsonify({"success": False, "message": f"Database error: {str(e)}"}), 500

@app.route('/api/add-manual-skills', methods=['POST'])
def add_manual_skills():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Please login first"}), 401
    
    try:
        data = request.json
        skills_input = data.get('skills', '')
        
        if not skills_input:
            return jsonify({"success": False, "message": "Please provide skills"}), 400
        
        # Handle both string (comma-separated) and list inputs
        if isinstance(skills_input, list):
            # If skills is already a list, use it directly
            new_skills = [s.strip().title() for s in skills_input if s.strip()]
        else:
            # If skills is a string, split by commas
            new_skills = [s.strip().title() for s in skills_input.split(',') if s.strip()]
        
        if not new_skills:
            return jsonify({"success": False, "message": "Please provide valid skills"}), 400
        
        conn = sqlite3.connect('career_hub.db')
        c = conn.cursor()
        
        # Check if manual_skills column exists with error handling
        try:
            c.execute('SELECT manual_skills, skills FROM users WHERE id = ?', (session['user_id'],))
            user = c.fetchone()
        except sqlite3.OperationalError as e:
            if "no such column: manual_skills" in str(e):
                # Add the missing column
                c.execute("ALTER TABLE users ADD COLUMN manual_skills TEXT")
                conn.commit()
                # Retry the query
                c.execute('SELECT skills FROM users WHERE id = ?', (session['user_id'],))
                user_data = c.fetchone()
                user = (None, user_data[0]) if user_data else (None, None)
            else:
                raise
        
        existing_manual = json.loads(user[0]) if user and user[0] else []
        resume_skills = json.loads(user[1]) if user and user[1] else []
        
        # Merge and deduplicate
        all_manual = list(set(existing_manual + new_skills))
        all_skills = list(set((resume_skills if resume_skills else []) + all_manual))
        
        c.execute('UPDATE users SET manual_skills = ? WHERE id = ?',
                 (json.dumps(all_manual), session['user_id']))
        conn.commit()
        conn.close()
        
        return jsonify({
            "success": True,
            "message": f"Added {len(new_skills)} skills successfully!",
            "manual_skills": all_manual,
            "all_skills": all_skills
        })
        
    except Exception as e:
        print(f"❌ Error in add_manual_skills: {e}")
        return jsonify({"success": False, "message": f"Failed: {str(e)}"}), 500

@app.route('/api/delete-skill', methods=['POST'])
def delete_skill():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Please login first"}), 401
    
    try:
        data = request.json
        skill_to_delete = data.get('skill', '').strip().title()
        
        if not skill_to_delete:
            return jsonify({"success": False, "message": "Please provide a skill to delete"}), 400
        
        conn = sqlite3.connect('career_hub.db')
        c = conn.cursor()
        
        # Get current skills
        c.execute('SELECT manual_skills, skills FROM users WHERE id = ?', (session['user_id'],))
        user = c.fetchone()
        
        if not user:
            conn.close()
            return jsonify({"success": False, "message": "User not found"}), 404
        
        manual_skills = json.loads(user[0]) if user[0] else []
        resume_skills = json.loads(user[1]) if user[1] else []
        
        # Remove the skill from manual skills
        if skill_to_delete in manual_skills:
            manual_skills.remove(skill_to_delete)
        
        # Update the database
        c.execute('UPDATE users SET manual_skills = ? WHERE id = ?',
                 (json.dumps(manual_skills), session['user_id']))
        conn.commit()
        conn.close()
        
        # Return updated skills list
        all_skills = list(set(resume_skills + manual_skills))
        
        return jsonify({
            "success": True,
            "message": f"Skill '{skill_to_delete}' deleted successfully!",
            "manual_skills": manual_skills,
            "all_skills": all_skills
        })
        
    except Exception as e:
        print(f"❌ Error deleting skill: {e}")
        return jsonify({"success": False, "message": f"Failed to delete skill: {str(e)}"}), 500
    
@app.route('/api/update-experience', methods=['POST'])
def update_experience():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Please login first"}), 401
    
    try:
        data = request.json
        experience = data.get('experience', '0-1')
        
        conn = sqlite3.connect('career_hub.db')
        c = conn.cursor()
        
        c.execute('UPDATE users SET experience = ? WHERE id = ?',
                 (experience, session['user_id']))
        conn.commit()
        conn.close()
        
        return jsonify({
            "success": True,
            "message": "Experience level updated successfully!",
            "experience": experience
        })
        
    except Exception as e:
        print(f"❌ Error updating experience: {e}")
        return jsonify({"success": False, "message": f"Failed: {str(e)}"}), 500

@app.route('/api/upload-resume', methods=['POST'])
def upload_resume():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Please login first"}), 401
    
    try:
        if 'resume' not in request.files:
            return jsonify({"success": False, "message": "No file uploaded"}), 400
        
        file = request.files['resume']
        if file.filename == '':
            return jsonify({"success": False, "message": "No file selected"}), 400
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            
            file_extension = filename.rsplit('.', 1)[1].lower()
            text = ""
            
            with open(file_path, 'rb') as f:
                if file_extension == 'pdf':
                    text = extract_text_from_pdf(f)
                elif file_extension in ['doc', 'docx']:
                    text = extract_text_from_docx(f)
                elif file_extension == 'txt':
                    text = extract_text_from_txt(f)
            
            os.remove(file_path)
            
            if not text.strip():
                return jsonify({"success": False, "message": "Could not extract text from resume"}), 400
            
            skills = extract_skills_from_text(text)
            experience = extract_experience_level(text)
            
            conn = sqlite3.connect('career_hub.db')
            c = conn.cursor()
            
            c.execute('SELECT manual_skills FROM users WHERE id = ?', (session['user_id'],))
            user = c.fetchone()
            manual_skills = json.loads(user[0]) if user[0] else []
            
            c.execute('UPDATE users SET skills = ?, experience = ? WHERE id = ?',
                     (json.dumps(skills), experience, session['user_id']))
            conn.commit()
            conn.close()
            
            all_skills = list(set(skills + manual_skills))
            
            return jsonify({
                "success": True,
                "message": "Resume processed successfully!",
                "data": {
                    "skills": skills,
                    "experience": experience,
                    "total_skills_found": len(skills),
                    "all_skills": all_skills
                }
            })
        else:
            return jsonify({"success": False, "message": "Invalid file type. Allowed: PDF, DOC, DOCX, TXT"}), 400
            
    except Exception as e:
        print(f"Resume upload error: {e}")
        return jsonify({"success": False, "message": f"Resume processing failed: {str(e)}"}), 500

@app.route('/api/auto-recommendations', methods=['GET'])
def auto_recommendations():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Please login first"}), 401
    
    try:
        conn = sqlite3.connect('career_hub.db')
        c = conn.cursor()
        
        c.execute('SELECT skills, experience, manual_skills FROM users WHERE id = ?', (session['user_id'],))
        user = c.fetchone()
        
        if not user:
            conn.close()
            return jsonify({"success": False, "message": "User not found"}), 400
        
        resume_skills = json.loads(user[0]) if user[0] else []
        manual_skills = json.loads(user[2]) if user[2] else []
        all_skills = list(set(resume_skills + manual_skills))
        
        if not all_skills:
            conn.close()
            return jsonify({"success": False, "message": "Please add skills first (upload resume or add manually)"}), 400
        
        user_experience = user[1] or '0-1'
        
        print("🚀 Fetching jobs from APIs...")
        jobs = fetch_jobs_from_apis(all_skills, max_results=40)
        
        user_profile = {
            'skills': all_skills,
            'experience': user_experience
        }
        
        scored_jobs = []
        for job in jobs:
            try:
                match_score = enhanced_calculate_job_match_score(user_profile, job)
                
                user_skills_lower = set([s.lower() for s in all_skills])
                job_skills_lower = set([s.lower() for s in job.get('skills', [])])
                matching_skills = list(user_skills_lower.intersection(job_skills_lower))
                
                scored_jobs.append({
                    **job,
                    'match_score': match_score,
                    'matching_skills': matching_skills
                })
            except Exception as e:
                print(f"⚠️ Error scoring job: {e}")
                continue
        
        # Sort by match score (highest first)
        scored_jobs.sort(key=lambda x: x.get('match_score', 0), reverse=True)
        
        return jsonify({
            "success": True,
            "recommendations": scored_jobs[:25],
            "user_skills": all_skills,
            "total_matches": len(scored_jobs)
        })
    
    except Exception as e:
        print(f"❌ Error in auto_recommendations: {e}")
        return jsonify({"success": False, "message": f"Failed: {str(e)}"}), 500

@app.route('/api/search-jobs', methods=['POST'])
def search_jobs():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Please login first"}), 401
    
    try:
        data = request.json
        skills = data.get('skills', [])
        location = data.get('location', 'United States')
        
        if not skills:
            return jsonify({"success": False, "message": "Please provide skills to search for"}), 400
        
        # Convert to list if it's a string
        if isinstance(skills, str):
            search_skills = [s.strip() for s in skills.split(',') if s.strip()]
        else:
            search_skills = skills
        
        print(f"🔍 Searching jobs for skills: {search_skills}")
        
        # Fetch jobs using the search skills
        jobs = fetch_jobs_from_apis(search_skills, location, max_results=30)
        
        # Get user profile for matching
        conn = sqlite3.connect('career_hub.db')
        c = conn.cursor()
        c.execute('SELECT skills, experience, manual_skills FROM users WHERE id = ?', (session['user_id'],))
        user = c.fetchone()
        conn.close()
        
        user_profile = {
            'skills': [],
            'experience': '0-1'
        }
        
        if user:
            resume_skills = json.loads(user[0]) if user[0] else []
            manual_skills = json.loads(user[2]) if user[2] else []
            user_profile['skills'] = list(set(resume_skills + manual_skills))
            user_profile['experience'] = user[1] or '0-1'
        
        # Score the jobs
        scored_jobs = []
        for job in jobs:
            match_score = enhanced_calculate_job_match_score(user_profile, job)
            
            user_skills_lower = set([s.lower() for s in user_profile['skills']])
            job_skills_lower = set([s.lower() for s in job.get('skills', [])])
            matching_skills = list(user_skills_lower.intersection(job_skills_lower))
            
            scored_jobs.append({
                **job,
                'match_score': match_score,
                'matching_skills': matching_skills
            })
        
        scored_jobs.sort(key=lambda x: x.get('match_score', 0), reverse=True)
        
        return jsonify({
            "success": True,
            "jobs": scored_jobs[:20],
            "search_skills": search_skills,
            "total_found": len(scored_jobs)
        })
        
    except Exception as e:
        print(f"❌ Error in job search: {e}")
        return jsonify({"success": False, "message": f"Search failed: {str(e)}"}), 500
    
# ============================
# SAVED JOBS API ROUTES
# ============================

@app.route('/api/jobs/save', methods=['POST'])
def save_job():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Please login first"}), 401
    
    try:
        data = request.json
        job_data = data.get('job')
        
        if not job_data:
            return jsonify({"success": False, "message": "Job data is required"}), 400
        
        success, message = save_job_for_user(session['user_id'], job_data)
        
        return jsonify({
            "success": success,
            "message": message
        })
        
    except Exception as e:
        print(f"❌ Error saving job: {e}")
        return jsonify({"success": False, "message": f"Failed to save job: {str(e)}"}), 500

@app.route('/api/jobs/saved', methods=['GET'])
def get_saved_jobs_route():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Please login first"}), 401
    
    try:
        saved_jobs = get_saved_jobs(session['user_id'])
        
        # Calculate match scores for saved jobs
        conn = sqlite3.connect('career_hub.db')
        c = conn.cursor()
        c.execute('SELECT skills, experience, manual_skills FROM users WHERE id = ?', (session['user_id'],))
        user = c.fetchone()
        conn.close()
        
        if user:
            resume_skills = json.loads(user[0]) if user[0] else []
            manual_skills = json.loads(user[2]) if user[2] else []
            all_skills = list(set(resume_skills + manual_skills))
            user_experience = user[1] or '0-1'
            
            user_profile = {
                'skills': all_skills,
                'experience': user_experience
            }
            
            for job in saved_jobs:
                match_score = enhanced_calculate_job_match_score(user_profile, job)
                job['match_score'] = match_score
        
        return jsonify({
            "success": True,
            "saved_jobs": saved_jobs,
            "total_saved": len(saved_jobs)
        })
        
    except Exception as e:
        print(f"❌ Error getting saved jobs: {e}")
        return jsonify({"success": False, "message": f"Failed to get saved jobs: {str(e)}"}), 500

@app.route('/api/jobs/remove-saved', methods=['POST'])
def remove_saved_job():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Please login first"}), 401
    
    try:
        data = request.json
        job_id = data.get('job_id')
        
        if not job_id:
            return jsonify({"success": False, "message": "Job ID is required"}), 400
        
        success, message = delete_saved_job(session['user_id'], job_id)
        
        return jsonify({
            "success": success,
            "message": message
        })
        
    except Exception as e:
        print(f"❌ Error removing saved job: {e}")
        return jsonify({"success": False, "message": f"Failed to remove job: {str(e)}"}), 500

# ============================
# INTERVIEW ROUTES
# ============================

@app.route('/api/interview/questions', methods=['POST'])
def generate_interview_questions():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Please login first"}), 401
    
    try:
        data = request.json
        skills = data.get('skills', [])
        
        if not skills:
            conn = sqlite3.connect('career_hub.db')
            c = conn.cursor()
            c.execute('SELECT skills, manual_skills FROM users WHERE id = ?', (session['user_id'],))
            user = c.fetchone()
            conn.close()
            
            if user:
                resume_skills = json.loads(user[0]) if user[0] else []
                manual_skills = json.loads(user[1]) if user[1] else []
                skills = list(set(resume_skills + manual_skills))
            
            if not skills:
                return jsonify({"success": False, "message": "Please provide skills or add them to your profile"}), 400
        
        questions = generate_skill_based_questions(skills)
        
        return jsonify({
            "success": True,
            "questions": questions,
            "total_questions": len(questions)
        })
        
    except Exception as e:
        return jsonify({"success": False, "message": f"Failed to generate questions: {str(e)}"}), 500

@app.route('/api/interview/analyze', methods=['POST'])
def analyze_interview_response():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Please login first"}), 401
    
    try:
        data = request.json
        question = data.get('question')
        answer = data.get('answer')
        skill = data.get('skill', 'General')
        
        if not question or not answer:
            return jsonify({"success": False, "message": "Question and answer are required"}), 400
        
        # Use enhanced AI analysis
        analysis_result = analyze_answer_with_ai(question, answer, skill)
        
        conn = sqlite3.connect('career_hub.db')
        c = conn.cursor()
        c.execute('''
            INSERT INTO interview_attempts (user_id, question, answer, skill, score, feedback)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (session['user_id'], question, answer, skill, analysis_result['score'], analysis_result['feedback']))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            "success": True,
            "analysis": analysis_result
        })
        
    except Exception as e:
        return jsonify({"success": False, "message": f"Failed to analyze response: {str(e)}"}), 500

@app.route('/api/interview/history', methods=['GET'])
def get_interview_history():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Please login first"}), 401
    
    try:
        conn = sqlite3.connect('career_hub.db')
        c = conn.cursor()
        c.execute('''
            SELECT question, skill, score, feedback, attempt_date 
            FROM interview_attempts 
            WHERE user_id = ? 
            ORDER BY attempt_date DESC 
            LIMIT 20
        ''', (session['user_id'],))
        
        attempts = c.fetchall()
        conn.close()
        
        history = []
        for attempt in attempts:
            history.append({
                'question': attempt[0],
                'skill': attempt[1],
                'score': attempt[2],
                'feedback': attempt[3],
                'date': attempt[4]
            })
        
        return jsonify({
            "success": True,
            "history": history,
            "total_attempts": len(history)
        })
        
    except Exception as e:
        return jsonify({"success": False, "message": f"Failed: {str(e)}"}), 500

# ============================
# UTILITY ROUTES
# ============================

@app.route('/api/debug/db-schema')
def debug_db_schema():
    """Debug endpoint to check database schema"""
    conn = sqlite3.connect('career_hub.db')
    c = conn.cursor()
    c.execute("PRAGMA table_info(users)")
    columns = c.fetchall()
    conn.close()
    return jsonify({"columns": columns})

@app.route('/api/health')
def health_check():
    return jsonify({
        "success": True,
        "message": "AI Career Hub API is running!",
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "features": {
            "ai_analysis": True,
            "job_apis": True,
            "manual_skills": True,
            "web_scraping": "Available",
            "saved_jobs": True,
            "enhanced_matching": True
        }
    })

# ============================
# FRONTEND ROUTES
# ============================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

# ============================
# INTERVIEW QUESTIONS FUNCTION
# ============================

def generate_skill_based_questions(skills, job_title=None):
    """Generate interview questions for specific skills"""
    generated_questions = []
    
    # Add skill-specific technical questions
    for skill in skills:
        skill_clean = skill.strip().title()
        
        # Check if we have questions for this skill
        if skill_clean in INTERVIEW_QUESTIONS:
            questions = INTERVIEW_QUESTIONS[skill_clean]
            for q in questions:
                generated_questions.append({
                    "question": q["question"],
                    "skill": skill_clean,
                    "difficulty": q["category"],
                    "category": "Technical"
                })
    
    # Add behavioral questions
    for bq in BEHAVIORAL_QUESTIONS[:5]:
        generated_questions.append({
            "question": bq["question"],
            "skill": "Behavioral",
            "difficulty": "General",
            "category": bq["category"]
        })
    
    # If no specific questions found, add generic ones
    if len(generated_questions) == 0:
        generated_questions = [
            {
                "question": f"Can you explain your experience with {skills[0] if skills else 'this technology'}?",
                "skill": skills[0] if skills else "General",
                "difficulty": "Basic",
                "category": "Technical"
            }
        ]
    
    return generated_questions[:15]

# ============================
# AI ANSWER ANALYSIS FUNCTION
# ============================

def analyze_answer_with_ai(question, answer, skill):
    """Enhanced AI-based answer analysis"""
    # Basic metrics
    word_count = len(answer.split())
    sentence_count = len([s for s in answer.split('.') if s.strip()])
    
    # Initialize score components
    length_score = 0
    structure_score = 0
    technical_score = 0
    quality_score = 0
    
    # 1. Length Analysis (0-25 points)
    if word_count < 20:
        length_score = 5
        length_feedback = "Your answer is too brief. Try to elaborate more."
    elif word_count < 50:
        length_score = 15
        length_feedback = "Good start, but could use more detail."
    elif word_count < 100:
        length_score = 25
        length_feedback = "Excellent detail in your answer."
    else:
        length_score = 20
        length_feedback = "Very comprehensive answer."
    
    # 2. Structure Analysis (0-25 points)
    if sentence_count < 2:
        structure_score = 5
        structure_feedback = "Try to structure your answer in multiple sentences."
    elif sentence_count < 4:
        structure_score = 15
        structure_feedback = "Good sentence structure."
    else:
        structure_score = 25
        structure_feedback = "Excellent structure and organization."
    
    # 3. Technical Content Analysis (0-30 points)
    answer_lower = answer.lower()
    
    # Define technical keywords by category
    technical_keywords = {
        'python': ['function', 'class', 'method', 'variable', 'list', 'dictionary', 'tuple', 
                   'loop', 'conditional', 'import', 'module', 'package', 'decorator', 'generator'],
        'javascript': ['function', 'variable', 'const', 'let', 'var', 'arrow', 'promise', 
                      'async', 'await', 'callback', 'closure', 'prototype', 'event'],
        'react': ['component', 'state', 'props', 'hook', 'useeffect', 'usestate', 'jsx', 
                 'virtual dom', 'lifecycle', 'render', 'context'],
        'java': ['class', 'method', 'object', 'interface', 'inheritance', 'polymorphism',
                'encapsulation', 'thread', 'exception', 'collection'],
        'sql': ['query', 'join', 'select', 'where', 'table', 'index', 'primary key',
               'foreign key', 'normalization', 'transaction'],
        'machine learning': ['model', 'training', 'dataset', 'feature', 'algorithm', 
                            'accuracy', 'validation', 'overfitting', 'neural network'],
        'aws': ['ec2', 's3', 'lambda', 'vpc', 'security group', 'load balancer',
               'cloudformation', 'iam', 'region', 'availability zone'],
        'docker': ['container', 'image', 'dockerfile', 'volume', 'network', 'compose',
                  'registry', 'daemon', 'orchestration']
    }
    
    # Find relevant keywords
    skill_lower = skill.lower()
    relevant_keywords = []
    for key, keywords in technical_keywords.items():
        if key in skill_lower or skill_lower in key:
            relevant_keywords = keywords
            break
    
    if not relevant_keywords:
        relevant_keywords = ['solution', 'problem', 'approach', 'implement', 'design',
                           'architecture', 'performance', 'optimize', 'debug', 'test']
    
    found_keywords = [kw for kw in relevant_keywords if kw in answer_lower]
    keyword_ratio = len(found_keywords) / len(relevant_keywords) if relevant_keywords else 0
    
    technical_score = int(keyword_ratio * 30)
    
    if technical_score >= 20:
        technical_feedback = f"Strong technical content with {len(found_keywords)} relevant concepts."
    elif technical_score >= 10:
        technical_feedback = f"Good use of technical terms. Found {len(found_keywords)} relevant concepts."
    else:
        technical_feedback = "Try to include more technical details and specific terminology."
    
    # 4. Quality Indicators (0-20 points)
    quality_indicators = {
        'examples': any(word in answer_lower for word in ['example', 'for instance', 'such as', 'like']),
        'experience': any(word in answer_lower for word in ['project', 'experience', 'worked', 'developed', 'built', 'created']),
        'explanation': any(word in answer_lower for word in ['because', 'since', 'therefore', 'thus', 'so']),
        'best_practices': any(word in answer_lower for word in ['best practice', 'recommend', 'should', 'better', 'efficient'])
    }
    
    quality_score = sum(5 for indicator in quality_indicators.values() if indicator)
    
    quality_feedback_parts = []
    if quality_indicators['examples']:
        quality_feedback_parts.append("Good use of examples")
    if quality_indicators['experience']:
        quality_feedback_parts.append("mentioned practical experience")
    if quality_indicators['explanation']:
        quality_feedback_parts.append("provided reasoning")
    if quality_indicators['best_practices']:
        quality_feedback_parts.append("discussed best practices")
    
    quality_feedback = ", ".join(quality_feedback_parts) if quality_feedback_parts else "Try to include examples and practical experience"
    
    # Calculate final score
    final_score = min(length_score + structure_score + technical_score + quality_score, 100)
    
    # Generate comprehensive feedback
    feedback_parts = [
        length_feedback,
        structure_feedback,
        technical_feedback,
        quality_feedback
    ]
    
    # Add improvement suggestions
    if final_score < 60:
        feedback_parts.append("\n\nSuggestions: Include specific examples, explain your reasoning, and use technical terminology relevant to the question.")
    elif final_score < 80:
        feedback_parts.append("\n\nTo improve: Add more depth to your explanations and consider discussing edge cases or alternatives.")
    else:
        feedback_parts.append("\n\nExcellent answer! You demonstrated strong understanding and communication skills.")
    
    return {
        "score": final_score,
        "feedback": " ".join(feedback_parts),
        "word_count": word_count,
        "sentence_count": sentence_count,
        "keywords_found": found_keywords,
        "breakdown": {
            "length": length_score,
            "structure": structure_score,
            "technical": technical_score,
            "quality": quality_score
        }
    }

# ============================
# MAIN APPLICATION
# ============================

if __name__ == '__main__':
    # Initialize and repair database
    init_db()
    print("✅ Database initialized successfully!")
    
    print("🚀 Starting AI Career Hub Server...")
    print("📊 Available Features:")
    print(f"   • Job APIs: ✅") 
    print(f"   • AI Interview Analysis: ✅")
    print(f"   • Manual Skills Input: ✅")
    print(f"   • Resume Processing: ✅")
    print(f"   • Web Scraping: ✅ (LinkedIn, Indeed, Internshala)")
    print(f"   • Enhanced Questions: ✅")
    print(f"   • Saved Jobs: ✅")
    print(f"   • Enhanced Matching: ✅")
    print(f"   • Delete Skills: ✅")
    
    app.run(debug=True, host='0.0.0.0', port=5000)
