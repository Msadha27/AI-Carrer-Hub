from flask import Flask, render_template, request, jsonify, session
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

# importing Sentence-BERT components (optional)
try:
    from sentence_transformers import SentenceTransformer
    SBERT_AVAILABLE = True
except ImportError:
    SBERT_AVAILABLE = False
    print("⚠️ sentence-transformers not available - using keyword matching")

# Try importing sklearn (optional for cosine similarity)
try:
    from sklearn.metrics.pairwise import cosine_similarity
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    print("⚠️ scikit-learn not available - using numpy for similarity")

# Try importing numpy (fallback for similarity)
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    print("⚠️ numpy not available - using pure Python calculations")

import threading
import time

app = Flask(__name__)
app.secret_key = 'ai-career-hub-secret-key-2024'
CORS(app)

# Configuration
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'txt'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

# API Configuration
ADZUNA_APP_ID = os.getenv('ADZUNA_APP_ID', 'y17426dca')
ADZUNA_APP_KEY = os.getenv('ADZUNA_APP_KEY', '351eba7055428c190eb976993c613a3d')
JSEARCH_API_KEY = os.getenv('JSEARCH_API_KEY', '2ee053f5f1msh07c75d362834877p188d49jsn2095772b2797')

# Initialize Sentence-BERT model
print("🔄 Loading Sentence-BERT model...")
model = None
try:
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer('all-MiniLM-L6-v2')
    print("✅ Sentence-BERT loaded successfully!")
except ImportError as e:
    print(f"⚠️ Sentence-BERT not available: {e}")
    print("💡 Using keyword-based matching (still works great!)")
    model = None
except Exception as e:
    print(f"⚠️ Model loading failed: {e}")
    print("💡 Using fallback keyword matching")
    model = None

# Cache for job embeddings
job_embeddings_cache = {}
cache_lock = threading.Lock()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Skill extraction patterns
SKILL_PATTERNS = {
    'Programming Languages': [
        'python', 'javascript', 'java', 'c++', 'c#', 'ruby', 'go', 'rust', 'swift',
        'kotlin', 'typescript', 'php', 'perl', 'scala', 'r', 'matlab', 'sql'
    ],
    'Web Frameworks': [
        'react', 'angular', 'vue', 'django', 'flask', 'express', 'node.js', 'nodejs',
        'spring boot', 'laravel', 'rails', 'asp.net', 'fastapi', 'next.js', 'nuxt.js'
    ],
    'Data Science & ML': [
        'machine learning', 'deep learning', 'tensorflow', 'pytorch', 'keras',
        'scikit-learn', 'pandas', 'numpy', 'matplotlib', 'seaborn', 'nltk',
        'computer vision', 'nlp', 'data analysis', 'statistics', 'data science'
    ],
    'Cloud & DevOps': [
        'aws', 'azure', 'gcp', 'docker', 'kubernetes', 'jenkins', 'terraform',
        'ansible', 'ci/cd', 'git', 'linux', 'bash', 'microservices', 'devops'
    ],
    'Databases': [
        'mysql', 'postgresql', 'mongodb', 'redis', 'elasticsearch', 'cassandra',
        'oracle', 'sqlite', 'dynamodb', 'firebase'
    ],
    'Other': [
        'rest api', 'graphql', 'agile', 'scrum', 'testing', 'selenium',
        'junit', 'jest', 'ui/ux', 'figma', 'git', 'github', 'gitlab'
    ]
}

def extract_text_from_pdf(file_stream):
    """Extract text from PDF file"""
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
    """Extract text from DOCX file"""
    try:
        doc = docx.Document(file_stream)
        text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
        return text
    except Exception as e:
        print(f"DOCX extraction error: {e}")
        return ""

def extract_text_from_txt(file_stream):
    """Extract text from TXT file"""
    try:
        return file_stream.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"TXT extraction error: {e}")
        return ""

def extract_skills_from_text(text):
    """Extract skills from resume text using pattern matching"""
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
    """Extract experience level from resume text"""
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

def extract_contact_info(text):
    """Extract contact information from resume"""
    contact_info = {'email': None, 'phone': None}
    
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    email_match = re.search(email_pattern, text)
    if email_match:
        contact_info['email'] = email_match.group(0)
    
    phone_patterns = [
        r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b',
        r'\(\d{3}\)\s*\d{3}[-.]?\d{4}',
        r'\+\d{1,3}\s*\d{3}[-.]?\d{3}[-.]?\d{4}'
    ]
    
    for pattern in phone_patterns:
        phone_match = re.search(pattern, text)
        if phone_match:
            contact_info['phone'] = phone_match.group(0)
            break
    
    return contact_info

# Sentence-BERT Matching Functions
def encode_text(text):
    """Encode text using Sentence-BERT"""
    if model is None:
        return None
    try:
        return model.encode(text, convert_to_tensor=False)
    except Exception as e:
        print(f"Encoding error: {e}")
        return None

def calculate_semantic_similarity(text1, text2):
    """Calculate semantic similarity between two texts"""
    if model is None or not SBERT_AVAILABLE:
        return fallback_similarity(text1, text2)
    
    try:
        emb1 = encode_text(text1)
        emb2 = encode_text(text2)
        
        if emb1 is None or emb2 is None:
            return fallback_similarity(text1, text2)
        
        # Use sklearn if available, otherwise numpy
        if SKLEARN_AVAILABLE:
            similarity = cosine_similarity([emb1], [emb2])[0][0]
        elif NUMPY_AVAILABLE:
            # Manual cosine similarity with numpy
            dot_product = np.dot(emb1, emb2)
            norm1 = np.linalg.norm(emb1)
            norm2 = np.linalg.norm(emb2)
            similarity = dot_product / (norm1 * norm2)
        else:
            # Pure Python cosine similarity (slowest but works)
            dot_product = sum(a * b for a, b in zip(emb1, emb2))
            norm1 = sum(a * a for a in emb1) ** 0.5
            norm2 = sum(b * b for b in emb2) ** 0.5
            similarity = dot_product / (norm1 * norm2)
        
        return float(similarity)
    except Exception as e:
        print(f"Similarity calculation error: {e}")
        return fallback_similarity(text1, text2)

def fallback_similarity(text1, text2):
    """Fallback keyword-based similarity"""
    words1 = set(text1.lower().split())
    words2 = set(text2.lower().split())
    intersection = words1.intersection(words2)
    union = words1.union(words2)
    return len(intersection) / len(union) if union else 0

def calculate_job_match_score(user_profile, job):
    """
    Calculate semantic match score between user profile and job
    Returns score 0-100 as integer
    """
    try:
        if model is None:
            score = fallback_job_matching(user_profile, job)
        else:
            # Combine user skills and experience into profile text
            user_text = ' '.join(user_profile.get('skills', [])) + ' ' + user_profile.get('experience', '')
            
            # Combine job title, description, and required skills
            job_text = f"{job.get('title', '')} {job.get('description', '')} {' '.join(job.get('skills', []))}"
            
            # Calculate semantic similarity
            similarity = calculate_semantic_similarity(user_text, job_text)
            
            # Convert to 0-100 scale
            base_score = similarity * 100
            
            # Bonus for experience level match
            if user_profile.get('experience') == job.get('experience'):
                base_score = min(base_score + 10, 100)
            
            # Bonus for exact skill matches (hybrid approach)
            user_skills_lower = set([s.lower() for s in user_profile.get('skills', [])])
            job_skills_lower = set([s.lower() for s in job.get('skills', [])])
            exact_matches = user_skills_lower.intersection(job_skills_lower)
            
            if exact_matches:
                bonus = min(len(exact_matches) * 5, 20)
                base_score = min(base_score + bonus, 100)
            
            score = base_score
        
        # Ensure we return an integer
        return int(round(score))
        
    except Exception as e:
        print(f"⚠️ Matching error: {e}")
        return fallback_job_matching(user_profile, job)

def fallback_job_matching(user_profile, job):
    """Fallback keyword-based matching - returns integer"""
    try:
        user_skills = set([s.lower() for s in user_profile.get('skills', [])])
        job_skills = set([s.lower() for s in job.get('skills', [])])
        
        if not job_skills:
            return 50
        
        matching = user_skills.intersection(job_skills)
        score = (len(matching) / len(job_skills)) * 100
        
        if user_profile.get('experience') == job.get('experience'):
            score = min(score + 10, 100)
        
        return int(round(score))
    except Exception as e:
        print(f"⚠️ Fallback matching error: {e}")
        return 50  # Default score if something goes wrong

# Job API Integration Functions
def fetch_adzuna_jobs(keywords, location='us', max_results=20):
    """Fetch jobs from Adzuna API - ENHANCED DEBUGGING"""
    try:
        print(f"🔍 [ADZUNA] Searching for: '{keywords}' in {location}")
        print(f"🔑 [ADZUNA] Using App ID: {ADZUNA_APP_ID[:8]}...")
        
        url = f"https://api.adzuna.com/v1/api/jobs/{location}/search/1"
        params = {
            'app_id': ADZUNA_APP_ID,
            'app_key': ADZUNA_APP_KEY,
            'results_per_page': max_results,
            'what': keywords,
            'content-type': 'application/json',
            'where': location
        }
        
        print(f"🌐 [ADZUNA] Making request to: {url}")
        print(f"📋 [ADZUNA] Params: { {k: v if k != 'app_key' else '***' + v[-4:] for k, v in params.items()} }")
        
        response = requests.get(url, params=params, timeout=15)
        print(f"📡 [ADZUNA] Response Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"📊 [ADZUNA] Raw response keys: {list(data.keys())}")
            print(f"📊 [ADZUNA] Results count: {len(data.get('results', []))}")
            
            jobs = []
            for job in data.get('results', []):
                salary_min = job.get('salary_min', 0)
                salary_max = job.get('salary_max', 0)
                salary = salary_min if salary_min else salary_max if salary_max else 0
                
                job_data = {
                    'title': job.get('title', 'N/A'),
                    'company': job.get('company', {}).get('display_name', 'N/A'),
                    'location': job.get('location', {}).get('display_name', 'N/A'),
                    'description': job.get('description', '')[:500],
                    'url': job.get('redirect_url', ''),
                    'salary': salary,
                    'posted_date': job.get('created', ''),
                    'source': 'Adzuna'
                }
                jobs.append(job_data)
                if len(jobs) <= 3:  # Only print first 3 for brevity
                    print(f"   📝 [ADZUNA] Found: {job_data['title'][:50]}... at {job_data['company']}")
            
            print(f"✅ [ADZUNA] Fetched {len(jobs)} jobs")
            return jobs
        else:
            print(f"❌ [ADZUNA] API error {response.status_code}: {response.text[:200]}")
            return []
            
    except Exception as e:
        print(f"❌ [ADZUNA] Exception: {str(e)}")
        return []

def fetch_jsearch_jobs(query, location='United States', max_results=20):
    """Fetch jobs from JSearch API - ENHANCED DEBUGGING"""
    try:
        print(f"🔍 [JSEARCH] Searching for: '{query}' in {location}")
        print(f"🔑 [JSEARCH] Using API Key: {JSEARCH_API_KEY[:8]}...")
        
        url = "https://jsearch.p.rapidapi.com/search"
        headers = {
            "X-RapidAPI-Key": JSEARCH_API_KEY,
            "X-RapidAPI-Host": "jsearch.p.rapidapi.com"
        }
        
        # Better query construction
        search_query = f"{query} {location}" if location else query
        params = {
            "query": search_query,
            "page": "1",
            "num_pages": "2",
            "date_posted": "all",
        }
        
        print(f"🌐 [JSEARCH] Making request to: {url}")
        print(f"📋 [JSEARCH] Params: {params}")
        
        response = requests.get(url, headers=headers, params=params, timeout=20)
        print(f"📡 [JSEARCH] Response Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"📊 [JSEARCH] Raw response keys: {list(data.keys()) if data else 'No data'}")
            print(f"📊 [JSEARCH] Data count: {len(data.get('data', [])) if data else 0}")
            
            jobs = []
            for job in data.get('data', [])[:max_results]:
                salary_min = job.get('job_min_salary', 0)
                salary_max = job.get('job_max_salary', 0)
                salary = salary_min if salary_min else salary_max if salary_max else 0
                
                job_data = {
                    'title': job.get('job_title', 'N/A'),
                    'company': job.get('employer_name', 'N/A'),
                    'location': job.get('job_city', 'Remote') or job.get('job_country', 'Remote'),
                    'description': job.get('job_description', '')[:500],
                    'url': job.get('job_apply_link', ''),
                    'salary': salary,
                    'posted_date': job.get('job_posted_at_datetime_utc', ''),
                    'source': 'JSearch'
                }
                jobs.append(job_data)
                if len(jobs) <= 3:  # Only print first 3 for brevity
                    print(f"   📝 [JSEARCH] Found: {job_data['title'][:50]}... at {job_data['company']}")
            
            print(f"✅ [JSEARCH] Fetched {len(jobs)} jobs")
            return jobs
        else:
            print(f"❌ [JSEARCH] API error {response.status_code}: {response.text[:200]}")
            return []
            
    except Exception as e:
        print(f"❌ [JSEARCH] Exception: {str(e)}")
        return []

def get_fallback_jobs(user_skills, location='United States'):
    """Get fallback jobs when APIs fail"""
    print("🔄 Using fallback job sources...")
    
    fallback_jobs = []
    
    # Add some generic job searches based on skills
    for skill in user_skills[:3]:
        fallback_jobs.extend([
            {
                'title': f'{skill} Developer',
                'company': 'Tech Company',
                'location': location,
                'type': 'Full-time',
                'skills': [skill, 'Programming', 'Development'],
                'description': f'Looking for a skilled {skill} developer to join our team.',
                'experience': '1-3',
                'salary': '$80,000-$100,000',
                'url': 'https://example.com/jobs/1',
                'source': 'Fallback'
            },
            {
                'title': f'Junior {skill} Engineer', 
                'company': 'Startup Inc',
                'location': 'Remote',
                'type': 'Full-time',
                'skills': [skill, 'Software Engineering'],
                'description': f'Entry-level position for {skill} engineers.',
                'experience': '0-1', 
                'salary': '$60,000-$80,000',
                'url': 'https://example.com/jobs/2',
                'source': 'Fallback'
            }
        ])
    
    return fallback_jobs[:10]

def fetch_jobs_from_apis(user_skills, location='United States', max_results=30):
    """
    Fetch jobs from multiple APIs and combine results - IMPROVED KEYWORDS
    """
    all_jobs = []
    
    # Better keyword generation - use individual skills as separate searches
    keywords = ' OR '.join(user_skills[:3])  # Use OR for broader search
    simple_keywords = ' '.join(user_skills[:3])  # Simple space-separated
    
    print(f"🎯 Starting job search for skills: {user_skills}")
    print(f"🔍 Using keywords: '{keywords}'")
    print(f"🔍 Simple keywords: '{simple_keywords}'")
    
    # Try different search strategies
    search_terms = [
        simple_keywords,  # Basic search
        keywords,         # OR search
        user_skills[0] if user_skills else "software"  # Fallback to first skill
    ]
    
    for search_term in search_terms[:2]:  # Try first two strategies
        print(f"🔄 Trying Adzuna API with: '{search_term}'")
        adzuna_jobs = fetch_adzuna_jobs(search_term, 'us', max_results=10)
        all_jobs.extend(adzuna_jobs)
        
        print(f"🔄 Trying JSearch API with: '{search_term}'")
        jsearch_jobs = fetch_jsearch_jobs(search_term, location, max_results=10)
        all_jobs.extend(jsearch_jobs)
        
        if all_jobs:  # If we got results, break early
            break
    
    # Remove duplicates based on title and company
    unique_jobs = []
    seen = set()
    for job in all_jobs:
        job_key = (job['title'].lower(), job['company'].lower())
        if job_key not in seen:
            seen.add(job_key)
            unique_jobs.append(job)
    
    print(f"📊 Total unique API jobs fetched: {len(unique_jobs)}")
    
    # If no jobs from APIs, use fallback
    if not unique_jobs:
        print("⚠️ No jobs from APIs, using fallback jobs")
        unique_jobs = get_fallback_jobs(user_skills, location)
    
    # Parse and normalize job data
    normalized_jobs = []
    for job in unique_jobs:
        job_skills = extract_skills_from_job_description(job.get('description', ''))
        exp_level = estimate_experience_from_job(job.get('title', ''), job.get('description', ''))
        
        normalized_jobs.append({
            'title': job['title'],
            'company': job['company'],
            'location': job['location'],
            'type': estimate_job_type(job.get('title', '')),
            'skills': job_skills,
            'description': job['description'],
            'experience': exp_level,
            'salary': format_salary(job.get('salary', 0)),
            'url': job['url'],
            'posted_date': job.get('posted_date', ''),
            'source': job.get('source', 'API')
        })
    
    return normalized_jobs

def extract_skills_from_job_description(description):
    """Extract skills from job description"""
    found_skills = set()
    desc_lower = description.lower()
    
    for category, skills in SKILL_PATTERNS.items():
        for skill in skills:
            if skill.lower() in desc_lower:
                display_skill = ' '.join(word.capitalize() for word in skill.split())
                found_skills.add(display_skill)
    
    return list(found_skills)[:10]

def estimate_experience_from_job(title, description):
    """Estimate required experience level from job posting"""
    text = (title + ' ' + description).lower()
    
    if any(word in text for word in ['senior', 'lead', 'principal', 'staff', '5+ years', '7+ years']):
        return '5+'
    elif any(word in text for word in ['mid-level', '3-5 years', '3+ years']):
        return '3-5'
    elif any(word in text for word in ['junior', '1-3 years', '2+ years']):
        return '1-3'
    elif any(word in text for word in ['intern', 'entry', 'graduate', '0-1 years']):
        return '0-1'
    
    return '1-3'

def estimate_job_type(title):
    """Estimate job type from title"""
    title_lower = title.lower()
    if 'intern' in title_lower:
        return 'Internship'
    return 'Full-time'

def format_salary(salary):
    """Format salary for display"""
    if not salary or salary == 0:
        return 'Competitive'
    
    if salary < 50:
        return f'${salary}/hour'
    elif salary < 1000:
        return f'${salary}k/year'
    else:
        return f'${salary:,}/year'

# Database Functions
def init_db():
    conn = sqlite3.connect('career_hub.db')
    c = conn.cursor()
    
    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT NOT NULL,
                  email TEXT UNIQUE NOT NULL,
                  password TEXT NOT NULL,
                  skills TEXT,
                  experience TEXT,
                  preferences TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Jobs table
    c.execute('''CREATE TABLE IF NOT EXISTS jobs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  title TEXT NOT NULL,
                  company TEXT NOT NULL,
                  location TEXT NOT NULL,
                  type TEXT NOT NULL,
                  skills TEXT NOT NULL,
                  description TEXT NOT NULL,
                  experience TEXT NOT NULL,
                  salary TEXT NOT NULL,
                  url TEXT,
                  source TEXT DEFAULT 'Database',
                  posted_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Applications table
    c.execute('''CREATE TABLE IF NOT EXISTS applications
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  job_id INTEGER,
                  job_url TEXT,
                  status TEXT DEFAULT 'Applied',
                  applied_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY (user_id) REFERENCES users (id),
                  FOREIGN KEY (job_id) REFERENCES jobs (id))''')
    
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
    
    # Job preparation table
    c.execute('''CREATE TABLE IF NOT EXISTS job_preparation
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  job_id INTEGER,
                  job_title TEXT,
                  company TEXT,
                  preparation_notes TEXT,
                  questions_generated TEXT,
                  status TEXT DEFAULT 'Preparing',
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY (user_id) REFERENCES users (id))''')
    
    # Seed sample jobs if empty
    c.execute('SELECT COUNT(*) FROM jobs')
    if c.fetchone()[0] == 0:
        sample_jobs = [
            ('Software Engineer Intern', 'TechCorp', 'San Francisco, CA', 'Internship', 
             'Python,JavaScript,React,SQL', 'Join our team to build cutting-edge web applications.', 
             '0-1', '$30/hour', 'https://techcorp.com', 'Sample'),
            ('Full Stack Developer', 'StartupXYZ', 'Remote', 'Full-time', 
             'Node.js,React,MongoDB,AWS', 'Build scalable applications for our growing platform.', 
             '2-4', '$100k/year', 'https://startupxyz.com/jobs', 'Sample'),
        ]
        c.executemany('INSERT INTO jobs (title, company, location, type, skills, description, experience, salary, url, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', sample_jobs)
    
    conn.commit()
    conn.close()

# Interview Question Generation Functions
def generate_skill_based_questions(skills, job_title=None):
    """Generate interview questions for specific skills"""
    question_templates = {
        'Python': [
            {
                "question": "What are Python decorators and how would you use them in a real project?",
                "skill": "Python",
                "difficulty": "Intermediate",
                "category": "Technical",
                "hints": ["Think about function wrappers", "Consider authentication or logging use cases"],
                "expected_keywords": ["wrapper", "syntax", "@decorator", "functions"]
            },
            {
                "question": "Explain the difference between lists and tuples in Python. When would you use each?",
                "skill": "Python", 
                "difficulty": "Basic",
                "category": "Technical",
                "hints": ["Think about mutability", "Consider performance implications"],
                "expected_keywords": ["mutable", "immutable", "performance", "memory"]
            },
            {
                "question": "How does Python handle memory management?",
                "skill": "Python",
                "difficulty": "Advanced",
                "category": "Technical",
                "hints": ["Discuss garbage collection", "Mention reference counting"],
                "expected_keywords": ["garbage collection", "reference counting", "memory allocation"]
            }
        ],
        'JavaScript': [
            {
                "question": "What are closures in JavaScript and can you provide a practical example?",
                "skill": "JavaScript",
                "difficulty": "Intermediate", 
                "category": "Technical",
                "hints": ["Think about function scope", "Consider private variables"],
                "expected_keywords": ["scope", "function", "private", "variables"]
            },
            {
                "question": "Explain the concept of promises and async/await in JavaScript.",
                "skill": "JavaScript",
                "difficulty": "Intermediate",
                "category": "Technical", 
                "hints": ["Think about asynchronous operations", "Consider error handling"],
                "expected_keywords": ["asynchronous", "then/catch", "async/await", "error handling"]
            }
        ],
        'React': [
            {
                "question": "What are React hooks and why were they introduced?",
                "skill": "React",
                "difficulty": "Basic",
                "category": "Technical",
                "hints": ["Think about class components vs functional components", "Consider state management"],
                "expected_keywords": ["useState", "useEffect", "functional components", "state"]
            },
            {
                "question": "Explain the virtual DOM and how React uses it for performance.",
                "skill": "React",
                "difficulty": "Intermediate",
                "category": "Technical",
                "hints": ["Think about DOM manipulation costs", "Consider diffing algorithms"],
                "expected_keywords": ["virtual dom", "reconciliation", "performance", "diffing"]
            }
        ],
        'SQL': [
            {
                "question": "What are the different types of JOINs in SQL and when would you use each?",
                "skill": "SQL", 
                "difficulty": "Intermediate",
                "category": "Technical",
                "hints": ["Think about table relationships", "Consider left vs inner joins"],
                "expected_keywords": ["inner join", "left join", "right join", "full outer join"]
            },
            {
                "question": "How would you optimize a slow-running SQL query?",
                "skill": "SQL",
                "difficulty": "Advanced",
                "category": "Technical",
                "hints": ["Think about indexes", "Consider query execution plans"],
                "expected_keywords": ["indexes", "explain", "optimization", "query plan"]
            }
        ],
        'Data Science': [
            {
                "question": "What is the bias-variance tradeoff in machine learning?",
                "skill": "Data Science",
                "difficulty": "Intermediate",
                "category": "Technical", 
                "hints": ["Think about model complexity", "Consider overfitting vs underfitting"],
                "expected_keywords": ["bias", "variance", "overfitting", "underfitting", "model complexity"]
            },
            {
                "question": "How would you handle missing values in a dataset?",
                "skill": "Data Science",
                "difficulty": "Basic",
                "category": "Technical",
                "hints": ["Consider different imputation methods", "Think about data distribution"],
                "expected_keywords": ["imputation", "mean", "median", "drop", "interpolation"]
            }
        ],
        'AWS': [
            {
                "question": "Explain the difference between EC2 and Lambda and when to use each.",
                "skill": "AWS",
                "difficulty": "Intermediate",
                "category": "Technical",
                "hints": ["Think about long-running vs event-driven workloads", "Consider serverless architecture"],
                "expected_keywords": ["ec2", "lambda", "serverless", "scaling", "cost"]
            }
        ]
    }
    
    # Behavioral questions based on job level
    behavioral_questions = [
        {
            "question": "Tell me about a challenging technical problem you solved and how you approached it.",
            "skill": "Behavioral",
            "difficulty": "Intermediate",
            "category": "Behavioral",
            "hints": ["Use STAR method", "Focus on your thought process"],
            "expected_keywords": ["problem", "solution", "results", "learning"]
        },
        {
            "question": "How do you handle conflicting priorities or tight deadlines?",
            "skill": "Behavioral",
            "difficulty": "Basic", 
            "category": "Behavioral",
            "hints": ["Discuss prioritization", "Mention communication with team"],
            "expected_keywords": ["prioritization", "communication", "time management", "deadlines"]
        }
    ]
    
    generated_questions = []
    
    # Add skill-specific questions
    for skill in skills:
        skill_lower = skill.lower()
        for template_skill, questions in question_templates.items():
            if template_skill.lower() in skill_lower or skill_lower in template_skill.lower():
                generated_questions.extend(questions[:2])  # Take max 2 questions per skill
                break
    
    # Add behavioral questions
    generated_questions.extend(behavioral_questions)
    
    # Add job-specific questions if job title provided
    if job_title:
        job_specific = [
            {
                "question": f"Why are you interested in this {job_title} position at our company?",
                "skill": "Company Fit",
                "difficulty": "Basic",
                "category": "Behavioral",
                "hints": ["Research the company", "Connect your skills to the role"],
                "expected_keywords": ["interest", "alignment", "skills", "company culture"]
            },
            {
                "question": f"What specific experience do you have that makes you a good fit for this {job_title} role?",
                "skill": "Experience",
                "difficulty": "Intermediate", 
                "category": "Behavioral",
                "hints": ["Be specific about projects", "Quantify your achievements"],
                "expected_keywords": ["experience", "projects", "achievements", "skills"]
            }
        ]
        generated_questions.extend(job_specific)
    
    # If no specific skills matched, provide general questions
    if len(generated_questions) < 3:
        generated_questions.extend([
            {
                "question": "How do you stay updated with the latest technologies and trends in your field?",
                "skill": "General", 
                "difficulty": "Basic",
                "category": "Behavioral",
                "hints": ["Mention specific resources", "Talk about side projects"],
                "expected_keywords": ["learning", "blogs", "projects", "communities"]
            }
        ])
    
    return generated_questions[:15]  # Limit to 15 questions

def analyze_interview_answer(question, answer, skill):
    """Analyze interview answer and provide detailed feedback"""
    
    # Basic analysis
    word_count = len(answer.split())
    sentence_count = len([s for s in answer.split('.') if s.strip()])
    
    # Calculate base score based on answer length and quality indicators
    base_score = min(word_count * 0.5, 40)  # Up to 40 points for length
    
    # Add points for structure (sentences)
    structure_score = min(sentence_count * 5, 20)
    base_score += structure_score
    
    # Keyword matching for technical questions
    technical_keywords = [
        'python', 'javascript', 'react', 'sql', 'database', 'algorithm',
        'function', 'method', 'class', 'object', 'variable', 'loop',
        'conditional', 'api', 'framework', 'library', 'debug', 'test',
        'aws', 'azure', 'gcp', 'docker', 'kubernetes', 'server', 'client',
        'frontend', 'backend', 'fullstack', 'devops', 'ci/cd', 'agile'
    ]
    
    found_keywords = [kw for kw in technical_keywords if kw in answer.lower()]
    keyword_score = min(len(found_keywords) * 3, 20)
    base_score += keyword_score
    
    # Quality indicators
    quality_indicators = {
        'example_mentioned': any(word in answer.lower() for word in ['example', 'for instance', 'such as']),
        'experience_mentioned': any(word in answer.lower() for word in ['project', 'experience', 'worked', 'developed']),
        'solution_focused': any(word in answer.lower() for word in ['solution', 'solve', 'resolve', 'fix']),
        'learning_mentioned': any(word in answer.lower() for word in ['learned', 'understanding', 'knowledge', 'studied'])
    }
    
    # Add points for quality indicators
    quality_score = sum(5 for indicator in quality_indicators.values() if indicator)
    base_score += min(quality_score, 20)
    
    # Ensure score is within bounds
    final_score = min(int(base_score), 100)
    
    # Generate detailed feedback
    feedback_parts = []
    
    # Length feedback
    if word_count < 30:
        feedback_parts.append("Your answer is quite brief. Consider providing more detail and specific examples.")
    elif word_count < 80:
        feedback_parts.append("Good answer length. You've provided adequate detail.")
    else:
        feedback_parts.append("Excellent detail in your answer. You've thoroughly addressed the question.")
    
    # Structure feedback
    if sentence_count < 3:
        feedback_parts.append("Try to structure your answer in complete sentences with clear organization.")
    elif sentence_count < 6:
        feedback_parts.append("Good structure in your answer.")
    else:
        feedback_parts.append("Excellent organization and structure in your response.")
    
    # Technical content feedback
    if found_keywords:
        feedback_parts.append(f"Good use of technical terminology. You mentioned: {', '.join(found_keywords[:5])}.")
    else:
        feedback_parts.append("Consider using more technical terminology relevant to the question.")
    
    # Quality feedback
    quality_feedback = []
    if quality_indicators['example_mentioned']:
        quality_feedback.append("included relevant examples")
    if quality_indicators['experience_mentioned']:
        quality_feedback.append("drew from personal experience")
    if quality_indicators['solution_focused']:
        quality_feedback.append("focused on solutions")
    if quality_indicators['learning_mentioned']:
        quality_feedback.append("demonstrated learning mindset")
    
    if quality_feedback:
        feedback_parts.append(f"You effectively {', '.join(quality_feedback)}.")
    
    # Skill-specific feedback
    if skill.lower() != 'general' and skill.lower() != 'behavioral':
        feedback_parts.append(f"Good focus on demonstrating practical experience with {skill}.")
    
    feedback = " ".join(feedback_parts)
    
    return {
        "score": final_score,
        "feedback": feedback,
        "word_count": word_count,
        "sentence_count": sentence_count,
        "keywords_found": found_keywords,
        "quality_indicators": quality_indicators,
        "analysis": {
            "length_adequate": word_count >= 50,
            "has_structure": sentence_count >= 3,
            "technical_terms_used": len(found_keywords) >= 3,
            "includes_examples": quality_indicators['example_mentioned'],
            "draws_from_experience": quality_indicators['experience_mentioned']
        }
    }

# API Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/interview')
def interview_page():
    return render_template('interview.html')

@app.route('/interview-history')
def interview_history_page():
    return render_template('interview-history.html')

@app.route('/job-preparation')
def job_preparation_page():
    return render_template('job-preparation.html')

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
        c.execute('INSERT INTO users (name, email, password, skills, experience, preferences) VALUES (?, ?, ?, ?, ?, ?)',
                  (name, email, hashed_password, '[]', '', '{}'))
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
        
        conn = sqlite3.connect('career_hub.db')
        c = conn.cursor()
        
        c.execute('SELECT id, name, email, password, skills, experience, preferences FROM users WHERE email = ?', (email,))
        user = c.fetchone()
        conn.close()
        
        if not user or not check_password_hash(user[3], password):
            return jsonify({"success": False, "message": "Invalid credentials"}), 401
        
        session['user_id'] = user[0]
        session['user_email'] = user[2]
        
        return jsonify({
            "success": True,
            "user": {
                "id": user[0],
                "name": user[1],
                "email": user[2],
                "skills": json.loads(user[4]) if user[4] else [],
                "experience": user[5] or '',
                "preferences": json.loads(user[6]) if user[6] else {}
            }
        })
    except Exception as e:
        return jsonify({"success": False, "message": f"Login failed: {str(e)}"}), 500

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"success": True, "message": "Logged out successfully"})

@app.route('/api/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Not authenticated"}), 401
    
    conn = sqlite3.connect('career_hub.db')
    c = conn.cursor()
    
    if request.method == 'GET':
        c.execute('SELECT name, email, skills, experience, preferences FROM users WHERE id = ?', (session['user_id'],))
        user = c.fetchone()
        conn.close()
        
        if user:
            return jsonify({
                "success": True,
                "profile": {
                    "name": user[0],
                    "email": user[1],
                    "skills": json.loads(user[2]) if user[2] else [],
                    "experience": user[3] or '',
                    "preferences": json.loads(user[4]) if user[4] else {}
                }
            })
        return jsonify({"success": False, "message": "User not found"}), 404
    
    elif request.method == 'POST':
        try:
            data = request.json
            skills = json.dumps(data.get('skills', []))
            experience = data.get('experience', '')
            preferences = json.dumps(data.get('preferences', {}))
            
            c.execute('UPDATE users SET skills = ?, experience = ?, preferences = ? WHERE id = ?',
                      (skills, experience, preferences, session['user_id']))
            conn.commit()
            conn.close()
            
            return jsonify({"success": True, "message": "Profile updated successfully"})
        except Exception as e:
            conn.close()
            return jsonify({"success": False, "message": f"Update failed: {str(e)}"}), 500

@app.route('/api/upload-resume', methods=['POST'])
def upload_resume():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Please login first"}), 401
    
    if 'resume' not in request.files:
        return jsonify({"success": False, "message": "No file uploaded"}), 400
    
    file = request.files['resume']
    
    if not file.filename or not allowed_file(file.filename):
        return jsonify({"success": False, "message": "Invalid file type"}), 400
    
    try:
        filename = secure_filename(file.filename)
        file_ext = filename.rsplit('.', 1)[1].lower()
        
        if file_ext == 'pdf':
            text = extract_text_from_pdf(io.BytesIO(file.read()))
        elif file_ext == 'docx':
            text = extract_text_from_docx(io.BytesIO(file.read()))
        elif file_ext == 'txt':
            text = extract_text_from_txt(io.BytesIO(file.read()))
        else:
            return jsonify({"success": False, "message": "Unsupported file format"}), 400
        
        if not text or len(text.strip()) < 50:
            return jsonify({"success": False, "message": "Could not extract sufficient text"}), 400
        
        skills = extract_skills_from_text(text)
        experience = extract_experience_level(text)
        contact_info = extract_contact_info(text)
        
        if not skills:
            return jsonify({"success": False, "message": "No recognizable skills found"}), 400
        
        conn = sqlite3.connect('career_hub.db')
        c = conn.cursor()
        c.execute('UPDATE users SET skills = ?, experience = ? WHERE id = ?',
                  (json.dumps(skills), experience, session['user_id']))
        conn.commit()
        conn.close()
        
        return jsonify({
            "success": True,
            "message": f"Resume analyzed! Found {len(skills)} skills.",
            "data": {
                "skills": skills,
                "experience": experience,
                "contact_info": contact_info,
                "total_skills_found": len(skills)
            }
        })
    
    except Exception as e:
        return jsonify({"success": False, "message": f"Failed to process: {str(e)}"}), 500

@app.route('/api/auto-recommendations', methods=['GET'])
def auto_recommendations():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Please login first"}), 401
    
    try:
        conn = sqlite3.connect('career_hub.db')
        c = conn.cursor()
        
        c.execute('SELECT skills, experience, preferences FROM users WHERE id = ?', (session['user_id'],))
        user = c.fetchone()
        
        if not user or not user[0]:
            conn.close()
            return jsonify({"success": False, "message": "Please upload your resume first"}), 400
        
        user_skills = json.loads(user[0])
        user_experience = user[1] or '0-1'
        preferences = json.loads(user[2]) if user[2] else {}
        
        # Fetch jobs from APIs
        print("🚀 Attempting to fetch real jobs from APIs...")
        api_jobs = fetch_jobs_from_apis(user_skills, preferences.get('location', 'United States'))
        
        # Get sample jobs from database as fallback
        c.execute('SELECT id, title, company, location, type, skills, description, experience, salary, url, source FROM jobs')
        db_jobs = c.fetchall()
        conn.close()
        
        # Combine API and DB jobs
        all_jobs = []
        
        # Add API jobs first
        for job in api_jobs:
            all_jobs.append(job)
        
        # Add DB jobs as fallback
        for job in db_jobs:
            all_jobs.append({
                'id': job[0],
                'title': job[1],
                'company': job[2],
                'location': job[3],
                'type': job[4],
                'skills': job[5].split(','),
                'description': job[6],
                'experience': job[7],
                'salary': job[8],
                'url': job[9],
                'source': job[10]
            })
        
        print(f"📈 Total jobs available: {len(all_jobs)} (API: {len(api_jobs)}, DB: {len(db_jobs)})")
        
        # Calculate match scores
        user_profile = {
            'skills': user_skills,
            'experience': user_experience
        }
        
        scored_jobs = []
        for job in all_jobs:
            try:
                match_score = calculate_job_match_score(user_profile, job)
                
                # Ensure match_score is an integer
                if isinstance(match_score, (int, float)):
                    match_score = int(match_score)
                else:
                    match_score = 0  # Default if not a number
                
                # Find matching skills
                user_skills_lower = set([s.lower() for s in user_skills])
                job_skills_lower = set([s.lower() for s in job.get('skills', [])])
                matching_skills = list(user_skills_lower.intersection(job_skills_lower))
                
                if match_score >= 20:
                    scored_jobs.append({
                        **job,
                        'match_score': match_score,
                        'matching_skills': matching_skills
                    })
            except Exception as e:
                print(f"⚠️ Error scoring job {job.get('title', 'Unknown')}: {e}")
                continue
        
        # Sort by match score with error handling
        try:
            scored_jobs.sort(key=lambda x: x.get('match_score', 0), reverse=True)
        except Exception as e:
            print(f"⚠️ Error sorting jobs: {e}")
            # If sorting fails, just use the original order but ensure match_score is int
            for job in scored_jobs:
                if not isinstance(job.get('match_score'), int):
                    job['match_score'] = 0
        
        return jsonify({
            "success": True,
            "recommendations": scored_jobs[:30],
            "user_skills": user_skills,
            "total_matches": len(scored_jobs),
            "api_results": len(api_jobs),
            "db_results": len(db_jobs),
            "matching_method": "Sentence-BERT" if model else "Keyword-based"
        })
    
    except Exception as e:
        print(f"❌ Error in auto_recommendations: {e}")
        import traceback
        print(f"🔍 Full traceback: {traceback.format_exc()}")
        return jsonify({"success": False, "message": f"Failed: {str(e)}"}), 500

@app.route('/api/recommendations', methods=['POST'])
def get_recommendations():
    try:
        data = request.json
        user_skills = data.get('skills', [])
        job_type = data.get('type', 'all')
        location = data.get('location', '')
        
        # Fetch from APIs if skills provided
        if user_skills:
            api_jobs = fetch_jobs_from_apis(user_skills, location or 'United States')
        else:
            api_jobs = []
        
        conn = sqlite3.connect('career_hub.db')
        c = conn.cursor()
        
        query = 'SELECT id, title, company, location, type, skills, description, experience, salary, url, source FROM jobs WHERE 1=1'
        params = []
        
        if job_type != 'all':
            query += ' AND type = ?'
            params.append(job_type)
        
        if location:
            query += ' AND (location LIKE ? OR location = ?)'
            params.extend([f'%{location}%', 'Remote'])
        
        c.execute(query, params)
        db_jobs = c.fetchall()
        conn.close()
        
        # Combine results
        all_jobs = []
        
        for job in api_jobs:
            all_jobs.append(job)
        
        for job in db_jobs:
            all_jobs.append({
                'id': job[0],
                'title': job[1],
                'company': job[2],
                'location': job[3],
                'type': job[4],
                'skills': job[5].split(','),
                'description': job[6],
                'experience': job[7],
                'salary': job[8],
                'url': job[9],
                'source': job[10]
            })
        
        # Score jobs
        user_profile = {'skills': user_skills, 'experience': ''}
        scored_jobs = []
        
        for job in all_jobs:
            match_score = calculate_job_match_score(user_profile, job)
            
            user_skills_lower = set([s.lower() for s in user_skills])
            job_skills_lower = set([s.lower() for s in job.get('skills', [])])
            matching_skills = list(user_skills_lower.intersection(job_skills_lower))
            
            scored_jobs.append({
                **job,
                'match_score': match_score,
                'matching_skills': matching_skills
            })
        
        scored_jobs.sort(key=lambda x: x['match_score'], reverse=True)
        
        return jsonify({"success": True, "recommendations": scored_jobs[:30]})
    except Exception as e:
        return jsonify({"success": False, "message": f"Failed: {str(e)}"}), 500

# Interview Practice Routes
@app.route('/api/generate-interview-questions', methods=['POST'])
def generate_interview_questions():
    """Generate interview questions based on job description"""
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Please login first"}), 401
    
    try:
        data = request.json
        job_description = data.get('job_description', '')
        skills = data.get('skills', [])
        job_title = data.get('job_title', '')
        
        if not job_description and not skills:
            return jsonify({"success": False, "message": "Please provide job description or skills"}), 400
        
        # Extract skills from job description if not provided
        if not skills and job_description:
            skills = extract_skills_from_job_description(job_description)
        
        # Generate questions based on skills
        questions = generate_skill_based_questions(skills, job_title)
        
        return jsonify({
            "success": True,
            "questions": questions,
            "skills_covered": list(set([q['skill'] for q in questions])),
            "total_questions": len(questions)
        })
        
    except Exception as e:
        print(f"Error generating questions: {e}")
        return jsonify({"success": False, "message": f"Failed to generate questions: {str(e)}"}), 500

@app.route('/api/submit-interview-answer', methods=['POST'])
def submit_interview_answer():
    """Submit and analyze an interview answer"""
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Please login first"}), 401
    
    try:
        data = request.json
        question = data.get('question', '')
        answer = data.get('answer', '')
        skill = data.get('skill', 'General')
        
        if not question or not answer:
            return jsonify({"success": False, "message": "Question and answer are required"}), 400
        
        # Analyze the answer
        analysis_result = analyze_interview_answer(question, answer, skill)
        
        # Save to database
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
        print(f"Error analyzing answer: {e}")
        return jsonify({"success": False, "message": f"Failed to analyze answer: {str(e)}"}), 500

@app.route('/api/interview-stats', methods=['GET'])
def get_interview_stats():
    """Get user's interview statistics"""
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Please login first"}), 401
    
    try:
        conn = sqlite3.connect('career_hub.db')
        c = conn.cursor()
        
        # Get total attempts and average score
        c.execute('SELECT COUNT(*), AVG(score) FROM interview_attempts WHERE user_id = ?', (session['user_id'],))
        total_attempts, avg_score = c.fetchone()
        avg_score = round(avg_score, 1) if avg_score else 0
        
        # Get attempts by skill
        c.execute('''
            SELECT skill, COUNT(*), AVG(score) 
            FROM interview_attempts 
            WHERE user_id = ? 
            GROUP BY skill
        ''', (session['user_id'],))
        
        skill_stats = []
        for skill, count, skill_avg in c.fetchall():
            skill_stats.append({
                "skill": skill,
                "attempts": count,
                "average_score": round(skill_avg, 1) if skill_avg else 0
            })
        
        # Get recent attempts
        c.execute('''
            SELECT question, skill, score, attempt_date 
            FROM interview_attempts 
            WHERE user_id = ? 
            ORDER BY attempt_date DESC 
            LIMIT 5
        ''', (session['user_id'],))
        
        recent_attempts = []
        for question, skill, score, attempt_date in c.fetchall():
            recent_attempts.append({
                "question": question[:100] + "..." if len(question) > 100 else question,
                "skill": skill,
                "score": score,
                "attempt_date": attempt_date
            })
        
        conn.close()
        
        return jsonify({
            "success": True,
            "stats": {
                "total_attempts": total_attempts or 0,
                "average_score": avg_score,
                "skill_stats": skill_stats,
                "recent_attempts": recent_attempts
            }
        })
        
    except Exception as e:
        print(f"Error getting interview stats: {e}")
        return jsonify({"success": False, "message": f"Failed to get stats: {str(e)}"}), 500

@app.route('/api/auto-interview-questions', methods=['GET'])
def auto_interview_questions():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Please login first"}), 401
    
    try:
        conn = sqlite3.connect('career_hub.db')
        c = conn.cursor()
        c.execute('SELECT skills FROM users WHERE id = ?', (session['user_id'],))
        user = c.fetchone()
        conn.close()
        
        if not user or not user[0]:
            return jsonify({"success": False, "message": "Please upload resume first"}), 400
        
        user_skills = json.loads(user[0])
        
        # Generate questions based on user skills
        questions = generate_skill_based_questions(user_skills)
        
        return jsonify({
            "success": True,
            "questions": questions,
            "skills_covered": list(set([q['skill'] for q in questions])),
            "total_questions": len(questions)
        })
    
    except Exception as e:
        return jsonify({"success": False, "message": f"Failed: {str(e)}"}), 500

# Job Preparation Routes
@app.route('/api/start-job-preparation', methods=['POST'])
def start_job_preparation():
    """Start job preparation for a specific job"""
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Please login first"}), 401
    
    try:
        data = request.json
        job_id = data.get('job_id')
        job_title = data.get('job_title')
        company = data.get('company')
        job_description = data.get('job_description', '')
        
        # Extract skills from job description
        skills = extract_skills_from_job_description(job_description)
        
        # Generate interview questions
        questions = generate_skill_based_questions(skills, job_title)
        
        # Save to job preparation table
        conn = sqlite3.connect('career_hub.db')
        c = conn.cursor()
        c.execute('''
            INSERT INTO job_preparation (user_id, job_id, job_title, company, preparation_notes, questions_generated)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (session['user_id'], job_id, job_title, company, 
              json.dumps({"skills": skills, "description": job_description}),
              json.dumps(questions)))
        conn.commit()
        preparation_id = c.lastrowid
        conn.close()
        
        return jsonify({
            "success": True,
            "preparation_id": preparation_id,
            "questions": questions,
            "skills": skills,
            "message": "Job preparation started successfully!"
        })
        
    except Exception as e:
        print(f"Error starting job preparation: {e}")
        return jsonify({"success": False, "message": f"Failed to start preparation: {str(e)}"}), 500

@app.route('/api/job-preparation-history', methods=['GET'])
def get_job_preparation_history():
    """Get user's job preparation history"""
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Please login first"}), 401
    
    try:
        conn = sqlite3.connect('career_hub.db')
        c = conn.cursor()
        
        c.execute('''
            SELECT id, job_title, company, preparation_notes, questions_generated, status, created_at
            FROM job_preparation 
            WHERE user_id = ?
            ORDER BY created_at DESC
        ''', (session['user_id'],))
        
        preparations = []
        for prep in c.fetchall():
            notes = json.loads(prep[3]) if prep[3] else {}
            questions = json.loads(prep[4]) if prep[4] else []
            
            preparations.append({
                "id": prep[0],
                "job_title": prep[1],
                "company": prep[2],
                "skills": notes.get('skills', []),
                "questions_count": len(questions),
                "status": prep[5],
                "created_at": prep[6]
            })
        
        conn.close()
        
        return jsonify({
            "success": True,
            "preparations": preparations
        })
        
    except Exception as e:
        print(f"Error getting preparation history: {e}")
        return jsonify({"success": False, "message": f"Failed to get preparation history: {str(e)}"}), 500

# Other existing routes...
@app.route('/api/debug-apis', methods=['GET'])
def debug_apis():
    """Test endpoint to debug API connectivity"""
    print("🧪 Testing API connectivity...")
    
    # Test Adzuna
    print("\n=== TESTING ADZUNA ===")
    adzuna_test = fetch_adzuna_jobs("python", "us", 5)
    
    # Test JSearch
    print("\n=== TESTING JSEARCH ===")
    jsearch_test = fetch_jsearch_jobs("python", "United States", 5)
    
    return jsonify({
        "adzuna_working": len(adzuna_test) > 0,
        "adzuna_results": len(adzuna_test),
        "jsearch_working": len(jsearch_test) > 0, 
        "jsearch_results": len(jsearch_test),
        "adzuna_app_id": ADZUNA_APP_ID[:8] + "...",
        "jsearch_api_key": JSEARCH_API_KEY[:8] + "..."
    })

@app.route('/api/apply', methods=['POST'])
def apply_job():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Please login to apply"}), 401
    
    try:
        data = request.json
        job_id = data.get('job_id')
        job_url = data.get('job_url', '')
        
        conn = sqlite3.connect('career_hub.db')
        c = conn.cursor()
        
        c.execute('SELECT id FROM applications WHERE user_id = ? AND (job_id = ? OR job_url = ?)', 
                  (session['user_id'], job_id, job_url))
        if c.fetchone():
            conn.close()
            return jsonify({"success": False, "message": "Already applied to this job"}), 400
        
        c.execute('INSERT INTO applications (user_id, job_id, job_url, status) VALUES (?, ?, ?, ?)',
                  (session['user_id'], job_id, job_url, 'Applied'))
        conn.commit()
        conn.close()
        
        return jsonify({"success": True, "message": "Application submitted successfully!"})
    except Exception as e:
        return jsonify({"success": False, "message": f"Failed: {str(e)}"}), 500

@app.route('/api/applications', methods=['GET'])
def get_applications():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Not authenticated"}), 401
    
    try:
        conn = sqlite3.connect('career_hub.db')
        c = conn.cursor()
        
        c.execute('''SELECT a.id, a.status, a.applied_date, a.job_url, j.title, j.company, j.location, j.type
                     FROM applications a
                     LEFT JOIN jobs j ON a.job_id = j.id
                     WHERE a.user_id = ?
                     ORDER BY a.applied_date DESC''', (session['user_id'],))
        
        applications = []
        for app in c.fetchall():
            applications.append({
                "id": app[0],
                "status": app[1],
                "applied_date": app[2],
                "job_url": app[3],
                "job_title": app[4] or 'External Job',
                "company": app[5] or 'N/A',
                "location": app[6] or 'N/A',
                "type": app[7] or 'N/A'
            })
        
        conn.close()
        return jsonify({"success": True, "applications": applications})
    except Exception as e:
        return jsonify({"success": False, "message": f"Failed: {str(e)}"}), 500

@app.route('/api/analyze-answer', methods=['POST'])
def analyze_answer():
    try:
        data = request.json
        question = data.get('question', '')
        answer = data.get('answer', '').strip()
        skill = data.get('skill', '')
        
        if not answer:
            return jsonify({"success": False, "message": "Please provide an answer"}), 400
        
        # Use Sentence-BERT for semantic analysis if available
        if model:
            # Calculate semantic quality
            question_embedding = encode_text(question)
            answer_embedding = encode_text(answer)
            
            if question_embedding is not None and answer_embedding is not None:
                relevance = cosine_similarity([question_embedding], [answer_embedding])[0][0]
                base_score = min(relevance * 150, 100)
            else:
                base_score = 50
        else:
            base_score = 50
        
        word_count = len(answer.split())
        
        # Adjust based on length
        if word_count < 20:
            base_score = min(base_score, 40)
        elif word_count > 50:
            base_score = min(base_score + 20, 100)
        
        score = round(base_score)
        
        feedback_parts = []
        if word_count < 30:
            feedback_parts.append("Consider providing more detail")
        else:
            feedback_parts.append("Good depth of explanation")
        
        if model:
            feedback_parts.append("Semantic analysis shows strong relevance" if score > 70 else "Try to address the question more directly")
        
        feedback = '. '.join(feedback_parts) + '.'
        
        # Save if logged in
        if 'user_id' in session:
            conn = sqlite3.connect('career_hub.db')
            c = conn.cursor()
            c.execute('INSERT INTO interview_attempts (user_id, question, answer, skill, score, feedback) VALUES (?, ?, ?, ?, ?, ?)',
                      (session['user_id'], question, answer, skill, score, feedback))
            conn.commit()
            conn.close()
        
        suggestions = []
        if word_count < 50:
            suggestions.append("Expand with more details and examples")
        if score < 70:
            suggestions.append("Focus on directly answering the question")
        if not suggestions:
            suggestions = ["Great answer! Consider edge cases"]
        
        return jsonify({
            "success": True,
            "score": score,
            "feedback": feedback,
            "word_count": word_count,
            "suggestions": suggestions,
            "analysis_method": "Sentence-BERT" if model else "Rule-based"
        })
    except Exception as e:
        return jsonify({"success": False, "message": f"Failed: {str(e)}"}), 500

@app.route('/api/interview-history', methods=['GET'])
def get_interview_history():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Not authenticated"}), 401
    
    try:
        conn = sqlite3.connect('career_hub.db')
        c = conn.cursor()
        
        c.execute('''SELECT question, skill, score, feedback, attempt_date 
                     FROM interview_attempts 
                     WHERE user_id = ? 
                     ORDER BY attempt_date DESC 
                     LIMIT 20''', (session['user_id'],))
        
        history = []
        for attempt in c.fetchall():
            history.append({
                "question": attempt[0],
                "skill": attempt[1],
                "score": attempt[2],
                "feedback": attempt[3],
                "attempt_date": attempt[4]
            })
        
        conn.close()
        return jsonify({"success": True, "history": history})
    except Exception as e:
        return jsonify({"success": False, "message": f"Failed: {str(e)}"}), 500

@app.route('/api/stats', methods=['GET'])
def get_stats():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Not authenticated"}), 401
    
    try:
        conn = sqlite3.connect('career_hub.db')
        c = conn.cursor()
        
        c.execute('SELECT COUNT(*) FROM applications WHERE user_id = ?', (session['user_id'],))
        total_applications = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*), AVG(score) FROM interview_attempts WHERE user_id = ?', (session['user_id'],))
        interview_stats = c.fetchone()
        total_practice = interview_stats[0]
        avg_score = round(interview_stats[1], 1) if interview_stats[1] else 0
        
        c.execute('''SELECT skill, AVG(score), COUNT(*) 
                     FROM interview_attempts 
                     WHERE user_id = ? 
                     GROUP BY skill''', (session['user_id'],))
        skill_performance = [{"skill": row[0], "avg_score": round(row[1], 1), "attempts": row[2]} 
                            for row in c.fetchall()]
        
        conn.close()
        
        return jsonify({
            "success": True,
            "stats": {
                "total_applications": total_applications,
                "total_practice": total_practice,
                "average_score": avg_score,
                "skill_performance": skill_performance
            }
        })
    except Exception as e:
        return jsonify({"success": False, "message": f"Failed: {str(e)}"}), 500

@app.route('/api/test-scoring', methods=['GET'])
def test_scoring():
    """Test endpoint to debug scoring issues"""
    test_job = {
        'title': 'Test Developer',
        'company': 'Test Corp',
        'location': 'Remote',
        'type': 'Full-time',
        'skills': ['Python', 'JavaScript'],
        'description': 'Test job description',
        'experience': '1-3',
        'salary': '$100k',
        'url': 'https://example.com',
        'source': 'Test'
    }
    
    test_profile = {
        'skills': ['Python', 'SQL', 'React'],
        'experience': '1-3'
    }
    
    score = calculate_job_match_score(test_profile, test_job)
    
    return jsonify({
        "success": True,
        "test_score": score,
        "score_type": type(score).__name__,
        "model_available": model is not None
    })

if __name__ == '__main__':
    init_db()
    print("=" * 60)
    print("🚀 AI Career Hub Server Starting (UPGRADED)")
    print("=" * 60)
    print("✅ Database initialized")
    print(f"🤖 Sentence-BERT: {'Enabled' if model else 'Disabled (using fallback)'}")
    print(f"🌐 Job APIs: Adzuna={'✅' if ADZUNA_APP_ID else '❌'}, JSearch={'✅' if JSEARCH_API_KEY else '❌'}")
    print("📍 Server: http://localhost:5000")
    print("=" * 60)
    app.run(debug=True, port=5000, host='0.0.0.0')

