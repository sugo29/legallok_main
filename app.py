from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file, make_response
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import json
import os
from datetime import datetime
from flask_login import LoginManager, UserMixin, login_required, current_user, login_user, logout_user
import pdfkit
import tempfile
import requests
from azure_bot import azure_bot_bp
from models import db, User, Lawyer, Post, Comment, FilledForm

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///legallok.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/')
def home():
    return render_template('homePage.html')


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form.get("fullName")
        email = request.form.get("email")
        phone = request.form.get("phone")
        password = request.form.get("password")

        if User.query.filter_by(email=email).first():
            flash("Email already registered. Please login.", "error")
            return redirect("/login")

        user = User(
            full_name=name,
            email=email,
            phone=phone,
            password=generate_password_hash(password)
        )
        db.session.add(user)
        db.session.commit()
        flash("User registered successfully!", "success")
        return redirect("/login")

    return render_template("signup.html")


@app.route("/lawyer_register", methods=["GET", "POST"])
def lawyer_register():
    if request.method == "POST":
        data = request.form

        lawyer = Lawyer(
            first_name=data.get("firstName"),
            last_name=data.get("lastName"),
            email=data.get("email"),
            phone=data.get("phone"),
            password=generate_password_hash(data.get("password")),
            bar_number=data.get("barNumber"),
            practice_years=data.get("practiceYears"),
            specialization=data.get("specialization"),
            address=data.get("address"),
            city=data.get("city"),
            state=data.get("state"),
            pincode=data.get("pincode")
        )
        db.session.add(lawyer)
        db.session.commit()
        flash("Lawyer registered successfully!", "success")
        return redirect("/login")

    return render_template("lawyer login.html")


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            session['role'] = 'user'
            flash('User login successful!', 'success')
            return redirect(url_for('dashboard'))

        lawyer = Lawyer.query.filter_by(email=email).first()
        if lawyer and check_password_hash(lawyer.password, password):
            session['lawyer_id'] = lawyer.id
            session['role'] = 'lawyer'
            flash('Lawyer login successful!', 'success')
            return redirect(url_for('lawyer_dashboard'))

        flash('Invalid email or password.', 'error')
        return redirect(url_for('login'))

    return render_template('login.html')


@app.route('/dashboard')
@login_required
def dashboard():
    if session.get('role') != 'user':
        flash("Access denied.", "error")
        return redirect(url_for('login'))

    return render_template('dashboard.html', user=current_user)


@app.route('/lawyer_dashboard')
def lawyer_dashboard():
    if session.get('role') != 'lawyer':
        flash("Access denied.", "error")
        return redirect(url_for('login'))

    lawyer = Lawyer.query.get(session['lawyer_id'])
    return render_template('lawyer dashboard.html', lawyer=lawyer)


@app.route('/logout')
def logout():
    logout_user()
    session.clear()
    flash("Logged out successfully.")
    return redirect(url_for('login'))


# ----------------- OTHER PAGES -----------------

@app.route('/form')
@login_required
def form():
    return render_template('form2.html', user=current_user)

@app.route('/form/<form_id>', methods=['GET', 'POST'])
def form_detail(form_id):
    # Load the legal forms data
    try:
        with open(os.path.join(app.root_path, 'data', 'legal_forms.json'), 'r') as file:
            forms_data = json.load(file)
            
        # Find the specific form by ID
        form_data = None
        for form in forms_data['forms']:
            if form['id'] == form_id:
                form_data = form
                break
                
        if form_data:
            if request.method == 'POST':
                # Handle form submission
                if 'user_id' not in session:
                    flash('You must be logged in to submit a form.', 'error')
                    return redirect(url_for('login'))
                
                # Get form data
                form_values = {}
                for field in form_data['fields']:
                    field_name = field['name']
                    form_values[field_name] = request.form.get(field_name, '')

                # --- PSEUDO-TRANSLITERATE NAMES FOR HINDI EMPLOYMENT CONTRACT ---
                # Try to get selected language from form, session, or default to 'en'
                selected_language = request.form.get('language', session.get('selected_language', 'en'))
                if form_id == "business1" and selected_language == "hi":
                    if 'employerName' in form_values:
                        form_values['employerName'] = pseudo_transliterate_to_hindi(form_values['employerName'])
                    if 'employeeName' in form_values:
                        form_values['employeeName'] = pseudo_transliterate_to_hindi(form_values['employeeName'])
                # --- END PSEUDO-TRANSLITERATION ---

                # Create a new filled form record
                filled_form = FilledForm(
                    user_id=session['user_id'],
                    form_id=form_id,
                    form_title=form_data['title'],
                    form_data=json.dumps(form_values)
                )
                
                db.session.add(filled_form)
                db.session.commit()
                
                flash('Form submitted successfully!', 'success')
                return redirect(url_for('filled_forms'))
                
            return render_template('form.html', form=form_data)
        else:
            flash('Form not found.', 'error')
            return redirect(url_for('form'))
    except Exception as e:
        flash(f'Error loading form: {str(e)}', 'error')
        return redirect(url_for('form'))

@app.route('/api/forms')
def get_forms():
    try:
        with open(os.path.join(app.root_path, 'data', 'legal_forms.json'), 'r') as file:
            forms_data = json.load(file)
        return jsonify(forms_data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/forms/<form_id>')
def get_form(form_id):
    try:
        with open(os.path.join(app.root_path, 'data', 'legal_forms.json'), 'r') as file:
            forms_data = json.load(file)
            
        # Find the specific form by ID
        form_data = None
        for form in forms_data['forms']:
            if form['id'] == form_id:
                form_data = form
                break
                
        if form_data:
            return jsonify(form_data)
        else:
            return jsonify({'error': 'Form not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/filled-forms')
@login_required
def filled_forms():
    filled_forms = FilledForm.query.filter_by(user_id=current_user.id).order_by(FilledForm.created_at.desc()).all()
    return render_template('filled forms.html', filled_forms=filled_forms, user=current_user)

@app.route('/api/filled-forms')
@login_required
def get_user_filled_forms():
    filled_forms = FilledForm.query.filter_by(user_id=current_user.id).order_by(FilledForm.created_at.desc()).all()
    return jsonify([{
        'id': form.id,
        'form_id': form.form_id,
        'form_title': form.form_title,
        'created_at': form.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        'updated_at': form.updated_at.strftime('%Y-%m-%d %H:%M:%S')
    } for form in filled_forms])

def load_form_template(template_id):
    try:
        with open('data/form_templates.json', 'r') as f:
            templates = json.load(f)
            return templates.get(template_id)
    except Exception as e:
        print(f"Error loading form template: {e}")
        return None

def format_form_data(template_id, form_data):
    try:
        # Load the template
        template = load_form_template(template_id)
        
        # Initialize the formatted data structure
        formatted_data = {
            "document_title": "LEGAL AGREEMENT",
            "document_date": datetime.now().strftime("%dth %B %Y"),
            "parties": {},
            "terms": {},
            "clauses": {},
            "signatures": {}
        }
        
        # If we have a template, use it to format the data
        if template:
            formatted_data["document_title"] = template.get("document_title", "LEGAL AGREEMENT")
            
            # Format parties information
            formatted_data["parties"] = {
                "party1_name": form_data.get("company_name", "[Company Name]"),
                "party1_description": f"having its registered office at {form_data.get('company_address', '[Address]')}",
                "party1_reference": "Employer",
                "party2_name": form_data.get("employee_name", "[Employee Name]"),
                "party2_description": f"residing at {form_data.get('employee_address', '[Address]')}",
                "party2_reference": "Employee"
            }
            
            # Format terms
            formatted_data["terms"] = {
                "Job Title": form_data.get("job_title", "Not specified"),
                "Monthly Salary": form_data.get("monthly_salary", "Not specified"),
                "Probation Period": form_data.get("probation_period", "Not specified"),
                "Termination Notice": form_data.get("termination_notice", "Not specified")
            }
            
            # Format clauses
            formatted_data["clauses"] = {
                "Confidentiality": form_data.get("confidentiality", "Employee shall not disclose any proprietary information...")
            }
            
            # Format signatures
            formatted_data["signatures"] = {
                "party1_name": form_data.get("employer_signature", "[Employer Signature]"),
                "party1_date": form_data.get("employer_signature_date", datetime.now().strftime("%dth %B %Y")),
                "party2_name": form_data.get("employee_signature", "[Employee Signature]"),
                "party2_date": form_data.get("employee_signature_date", datetime.now().strftime("%dth %B %Y"))
            }
        else:
            # If no template, create a basic structure from the raw data
            if isinstance(form_data, dict):
                # Copy any existing fields that match our structure
                for key in ["document_title", "document_date"]:
                    if key in form_data:
                        formatted_data[key] = form_data[key]
                
                # Handle parties
                if "parties" in form_data:
                    formatted_data["parties"] = form_data["parties"]
                else:
                    formatted_data["parties"] = {
                        "party1_name": "[Party 1 Name]",
                        "party1_description": "[Party 1 Description]",
                        "party1_reference": "Party 1",
                        "party2_name": "[Party 2 Name]",
                        "party2_description": "[Party 2 Description]",
                        "party2_reference": "Party 2"
                    }
                
                # Add any terms from the form data
                for key, value in form_data.items():
                    if key not in ['document_title', 'document_date', 'parties', 'clauses', 'signatures']:
                        formatted_data['terms'][key] = value
        
        # Add any additional terms from the form data that aren't in our standard format
        if isinstance(form_data, dict):
            for key, value in form_data.items():
                if key not in formatted_data and key not in ['document_title', 'document_date', 'parties', 'clauses', 'signatures']:
                    formatted_data['terms'][key] = value
        
        return formatted_data
    except Exception as e:
        print(f"Error formatting form data: {e}")
        # Return a basic structure if there's an error
        return {
            "document_title": "LEGAL AGREEMENT",
            "document_date": datetime.now().strftime("%dth %B %Y"),
            "parties": {
                "party1_name": "[Party 1 Name]",
                "party1_description": "[Party 1 Description]",
                "party1_reference": "Party 1",
                "party2_name": "[Party 2 Name]",
                "party2_description": "[Party 2 Description]",
                "party2_reference": "Party 2"
            },
            "terms": {"Raw Data": str(form_data)},
            "clauses": {},
            "signatures": {
                "party1_name": "[Party 1 Signature]",
                "party1_date": datetime.now().strftime("%dth %B %Y"),
                "party2_name": "[Party 2 Signature]",
                "party2_date": datetime.now().strftime("%dth %B %Y")
            }
        }

@app.route('/api/filled-forms/<int:form_id>', methods=['GET'])
@login_required
def get_filled_form(form_id):
    form = FilledForm.query.get_or_404(form_id)
    if form.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    try:
        # Parse the form data
        form_data = json.loads(form.form_data)
        # Load the template and format the data
        formatted_data = format_form_data(form.form_id, form_data)
        # If formatting fails, use the original data
        if not formatted_data:
            formatted_data = form_data
        return jsonify({
            'id': form.id,
            'form_id': form.form_id,
            'form_title': form.form_title,
            'form_data': formatted_data,
            'created_at': form.created_at.isoformat()
        })
    except Exception as e:
        print(f"Error processing form data: {e}")
        # Return the raw form data if there's an error
        return jsonify({
            'id': form.id,
            'form_id': form.form_id,
            'form_title': form.form_title,
            'form_data': form.form_data,
            'created_at': form.created_at.isoformat(),
            'error': str(e)
        })

@app.route('/preview/<int:form_id>')
def preview_form(form_id):
    form = FilledForm.query.get_or_404(form_id)
    return render_template('preview.html', form=form)

@app.route('/api/filled-forms/<int:form_id>', methods=['DELETE'])
@login_required
def delete_filled_form(form_id):
    filled_form = FilledForm.query.get_or_404(form_id)
    if filled_form.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        db.session.delete(filled_form)
        db.session.commit()
        return jsonify({'message': 'Form deleted successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/community')
@login_required
def community():
    posts = Post.query.order_by(Post.created_at.desc()).all()
    return render_template('communityforum.html', user=current_user, posts=posts)

@app.route('/api/posts', methods=['GET'])
@login_required
def get_posts():
    posts = Post.query.order_by(Post.created_at.desc()).all()
    return jsonify([{
        'id': post.id,
        'title': post.title,
        'content': post.content,
        'created_at': post.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        'author': post.user.full_name
    } for post in posts])

@app.route('/api/posts', methods=['POST'])
@login_required
def create_post():
    try:
        data = request.get_json()
        
        if not all(key in data for key in ['title', 'content']):
            return jsonify({'error': 'Missing required fields'}), 400
        
        post = Post(
            title=data['title'],
            content=data['content'],
            user_id=current_user.id
        )
        
        db.session.add(post)
        db.session.commit()
        
        return jsonify({
            'message': 'Post created successfully',
            'post': {
                'id': post.id,
                'title': post.title,
                'content': post.content,
                'created_at': post.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'author': current_user.full_name
            }
        })
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/chatbot')
def chatbot():
    return render_template('chatbot.html')

@app.route('/askquestion')
def askquestion():
    user = User.query.get(session['user_id'])
    return render_template('askquestion.html', user=user)

@app.route('/answerquestion')
def answerquestion():
    return render_template('answerquestion.html')

@app.route('/form_filling')
def form_filling():
    return render_template('form filling.html')

@app.route('/lawyer_cases')
def lawyer_cases():
    return render_template('lawyer cases.html')

@app.route('/direct_urls')
@login_required
def direct_urls():
    return render_template('direct_urls.html', user=current_user)

@app.route('/lawyer_settings')
def lawyer_settings():
    return render_template('lawyer settings.html')

@app.route('/documents-converter')
@login_required
def documents_converter():
    return render_template('documents-converter.html', user=current_user)

# Route to handle form submissions
@app.route('/api/submit-form', methods=['POST'])
@login_required
def submit_form():
    try:
        data = request.get_json()
        
        # Validate required fields
        if not all(key in data for key in ['form_id', 'form_title', 'form_data']):
            return jsonify({'error': 'Missing required fields'}), 400
        
        # Convert form_data to JSON string
        form_data_json = json.dumps(data['form_data'])
        
        # Create a new filled form entry
        filled_form = FilledForm(
            user_id=current_user.id,
            form_id=data['form_id'],
            form_title=data['form_title'],
            form_data=form_data_json
        )
        
        db.session.add(filled_form)
        db.session.commit()
        
        return jsonify({
            'message': 'Form submitted successfully',
            'filled_form_id': filled_form.id
        })
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/posts/<int:post_id>/comments', methods=['GET'])
def get_post_comments(post_id):
    post = Post.query.get_or_404(post_id)
    comments = Comment.query.filter_by(post_id=post_id).order_by(Comment.created_at.desc()).all()
    return jsonify([{
        'id': comment.id,
        'content': comment.content,
        'created_at': comment.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        'user': {
            'id': comment.user.id,
            'full_name': comment.user.full_name
        }
    } for comment in comments])

@app.route('/api/posts/<int:post_id>/comments', methods=['POST'])
@login_required
def create_comment(post_id):
    post = Post.query.get_or_404(post_id)
    data = request.get_json()
    
    if not data or 'content' not in data:
        return jsonify({'error': 'Content is required'}), 400
        
    comment = Comment(
        content=data['content'],
        user_id=current_user.id,
        post_id=post_id
    )
    
    db.session.add(comment)
    db.session.commit()
    
    return jsonify({
        'id': comment.id,
        'content': comment.content,
        'created_at': comment.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        'user': {
            'id': current_user.id,
            'full_name': current_user.full_name
        }
    }), 201

@app.route('/api/posts/<int:post_id>', methods=['GET'])
def get_post(post_id):
    post = Post.query.get_or_404(post_id)
    return jsonify({
        'id': post.id,
        'title': post.title,
        'content': post.content,
        'created_at': post.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        'user': {
            'id': post.user.id,
            'full_name': post.user.full_name
        }
    })

# ----------------- TRANSLATION API -----------------

def pseudo_transliterate_to_hindi(text):
    # Simple demo mapping for a few common names, extend as needed
    demo_map = {
        'suhani': 'सुहानी',
        'deepak': 'दीपक',
        'anil': 'अनिल',
        'priya': 'प्रिया',
        'amit': 'अमित',
        'd': 'डी',
        'goyal': 'गोयल',
        'delhi': 'दिल्ली',
        'goa': 'गोवा',
        'analyst': 'विश्लेषक',
        'holiday': 'अवकाश',
        'na': 'एन/ए',
        'अनिल': 'अनिल',
        'employer address *': 'नियोक्ता का पता *',
        'employee name *': 'कर्मचारी का नाम *',
        'employee address *': 'कर्मचारी का पता *',
        'position/job title *': 'पद/नौकरी का शीर्षक *',
        'start date *': 'प्रारंभ तिथि *',
        'dd-mm-yyyy': 'दि-माह-वर्ष',
        'salary *': 'वेतन *',
        'benefits *': 'लाभ *',
        'working hours *': 'कार्य के घंटे *',
        'notice period *': 'नोटिस अवधि *',
        'confidentiality clause *': 'गोपनीयता खंड *',
        'non-compete clause *': 'गैर-प्रतिस्पर्धा खंड *',
    }
    # Lowercase for matching
    key = text.strip().lower()
    if key in demo_map:
        return demo_map[key]
    # Fallback: just return the original text in Devanagari letters (very basic, not real transliteration)
    # For demo, replace a-z with similar Hindi letters (not accurate, just for effect)
    basic_map = str.maketrans(
        'abcdefghijklmnopqrstuvwxyz',
        'अबकदएफगहइजकलमनओपकयरसतउवडएकज'
    )
    # If only alphabetic, fake it
    if key.isalpha():
        return ''.join(demo_map.get(c, c.translate(basic_map)) for c in key)
    return text

@app.route('/api/translate', methods=['POST'])
def translate_proxy():
    try:
        request_data = request.get_json()
        print("Received request data:", request_data)  # Debug log
        
        if not request_data:
            return jsonify({
                'error': 'Invalid Request',
                'message': 'Missing request data'
            }), 400

        fallback_only = request_data.get('fallback_only', False)
        if 'input' in request_data:
            input_data = request_data['input']
            source_text = input_data.get('source')
            source_lang = input_data.get('sourceLanguage', 'en')
            target_lang = input_data.get('targetLanguage')
        else:
            source_text = request_data.get('source')
            source_lang = request_data.get('sourceLanguage', 'en')
            target_lang = request_data.get('target')

        if not source_text or not target_lang:
            return jsonify({
                'error': 'Invalid Request',
                'message': 'Missing required fields: source text or target language'
            }), 400

        # --- EXTENDED MOCK TRANSLATIONS DICTIONARY ---
        mock_translations = {
            'Hello': {'hi': 'नमस्ते', 'bn': 'হ্যালো', 'te': 'హలో', 'ta': 'வணக்கம்'},
            'Legal Assistant': {'hi': 'कानूनी सहायक', 'bn': 'আইনী সহায়ক', 'te': 'న్యాయ సహాయకుడు', 'ta': 'சட்ட உதவியாளர்'},
            'Dashboard': {'hi': 'डैशबोर्ड', 'bn': 'ড্যাশবোর্ড', 'te': 'డాష్‌బోర్డ్', 'ta': 'டாஷ்போர்ட்'},
            'Forms': {'hi': 'फॉर्म', 'bn': 'ফর্ম', 'te': 'ఫారమ్‌లు', 'ta': 'படிவங்கள்'},
            'Translate': {'hi': 'अनुवाद करें', 'bn': 'অনুবাদ', 'te': 'అనువదించు', 'ta': 'மொழிபெயர்'},
            'Legal Lok': {'hi': 'लीगल लोक', 'bn': 'লিগ্যাল লোক', 'te': 'లీగల్ లోక్', 'ta': 'லீகல் லோக்'},
            'Bengali': {'hi': 'बंगाली', 'bn': 'বাংলা'},
            'Community Forum': {'hi': 'सामुदायिक मंच', 'bn': 'কমিউনিটি ফোরাম'},
            'Legal Institutions': {'hi': 'कानूनी संस्थान', 'bn': 'আইনি প্রতিষ্ঠান'},
            'Petitions': {'hi': 'याचिकाएँ', 'bn': 'আবেদন'},
            'Document Converter': {'hi': 'दस्तावेज़ परिवर्तक', 'bn': 'ডকুমেন্ট কনভার্টার'},
            'Settings': {'hi': 'सेटिंग्स', 'bn': 'সেটিংস'},
            'Legal Chatbot': {'hi': 'लीगल चैटबोट', 'bn': 'লিগ্যাল চ্যাটবট'},
            'Logout': {'hi': 'लॉगआउट', 'bn': 'লগআউট'},
            'Welcome back, d!': {'hi': 'वापसी पर स्वागत है, d!', 'bn': 'স্বাগতম d!'},
            "Here's what's happening with your legal matters today.": {'hi': 'आज आपके कानूनी मामलों में यह हो रहा है।', 'bn': 'আপনার আইনি বিষয়ে আজ যা ঘটছে'},
            'My Profile': {'hi': 'मेरा प्रोफ़ाइल', 'bn': 'আমার প্রোফাইল'},
            'Member since N/A': {'hi': 'सदस्य N/A से', 'bn': 'সদস্য N/A থেকে'},
            'Full Name': {'hi': 'पूरा नाम', 'bn': 'পূর্ণ নাম'},
            'Mobile Number': {'hi': 'मोबाइल नंबर', 'bn': 'মোবাইল নম্বর'},
            'Email Address': {'hi': 'ईमेल पता', 'bn': 'ইমেইল ঠিকানা'},
            'User ID': {'hi': 'यूज़र आईडी', 'bn': 'ইউজার আইডি'},
            'Recent Activities': {'hi': 'हाल की गतिविधियाँ', 'bn': 'সাম্প্রতিক কার্যক্রম'},
            'New Petition Filed': {'hi': 'नई याचिका दायर की गई', 'bn': 'নতুন আবেদন দাখিল হয়েছে'},
            'Your petition regarding property dispute has been successfully submitted.': {'hi': 'संपत्ति विवाद से संबंधित आपकी याचिका सफलतापूर्वक जमा कर दी गई है।', 'bn': 'সম্পত্তি সংক্রান্ত আপনার আবেদন সফলভাবে জমা দেওয়া হয়েছে।'},
            '2 hours ago': {'hi': '2 घंटे पहले', 'bn': '২ ঘন্টা আগে'},
            'd': {'hi': 'डी', 'bn': 'ডি'},
            'Explore Templates': {'hi': 'टेम्पलेट्स देखें', 'bn': 'টেমপ্লেট দেখুন'},
            'Filter': {'hi': 'फ़िल्टर', 'bn': 'ফিল্টার'},
            'Business': {'hi': 'व्यापार', 'bn': 'ব্যবসা'},
            'Employment Contract': {'hi': 'रोजगार अनुबंध', 'bn': 'চাকরির চুক্তি'},
            'Standard employment contract template for hiring employees': {'hi': 'कर्मचारियों को नियुक्त करने के लिए मानक रोजगार अनुबंध टेम्पलेट', 'bn': 'কর্মচারী নিয়োগের জন্য স্ট্যান্ডার্ড চাকরির চুক্তি টেমপ्लেট'},
            'Instructions': {'hi': 'निर्देश', 'bn': 'নির্দেশাবলী'},
            'General Information': {'hi': 'सामान्य जानकारी', 'bn': 'সাধারণ তথ্য'},
            'Employer Name *': {'hi': 'नियोक्ता का नाम *', 'bn': 'নিয়োগকারীর নাম *'},
            'Employer Address *': {'hi': 'नियोक्ता का पता *', 'bn': 'নিয়োগকারীর ঠিকানা *'},
            'Employee Name *': {'hi': 'कर्मचारी का नाम *', 'bn': 'কর্মচারীর নাম *'},
            'Employee Address *': {'hi': 'कर्मचारी का पता *', 'bn': 'কর্মচারীর ঠিকানা *'},
            'Position/Job Title *': {'hi': 'पद/नौकरी का शीर्षक *', 'bn': 'পদ/কাজের শিরোনাম *'},
            'Start Date *': {'hi': 'प्रारंभ तिथि *', 'bn': 'শুরুর তারিখ *'},
            'dd-mm-yyyy': {'hi': 'दि-माह-वर्ष', 'bn': 'দিন-মাস-বছর'},
            'Salary *': {'hi': 'वेतन *', 'bn': 'বেতন *'},
            'Benefits *': {'hi': 'लाभ *', 'bn': 'সুবিধা *'},
            'Working Hours *': {'hi': 'कार्य के घंटे *', 'bn': 'কাজের সময় *'},
            'Notice Period *': {'hi': 'नोटिस अवधि *', 'bn': 'নোটিশ পিরিয়ড *'},
            'Confidentiality Clause *': {'hi': 'गोपनीयता खंड *', 'bn': 'গোপনীয়তা ধারা *'},
            'Non-Compete Clause *': {'hi': 'गैर-प्रतिस्पर्धा खंड *', 'bn': 'অপ্রতিযোগিতা ধারা *'},
            'Employer Signature *': {'hi': 'नियोक्ता का हस्ताक्षर *', 'bn': 'নিয়োগকারীর স্বাক্ষর *'},
            'Employee Signature *': {'hi': 'कर्मचारी का हस्ताक्षर *', 'bn': 'কর্মচারীর স্বাক্ষর *'},
            'Date *': {'hi': 'तिथि *', 'bn': 'তারিখ *'},
            'Create New Post': {'hi': 'नई पोस्ट बनाएं', 'bn': 'নতুন পোস্ট তৈরি করুন'},
            'Posted by d on 14/4/2025': {'hi': 'd द्वारा 14/4/2025 को पोस्ट किया गया', 'bn': 'd দ্বারা ১৪/৪/২০২৫ তারিখে পোস্ট করা হয়েছে'},
            'View Discussion': {'hi': 'चर्चा देखें', 'bn': 'আলোচনা দেখুন'},
            'Understanding Employment Contracts': {'hi': 'रोजगार अनुबंध को समझना', 'bn': 'চাকরির চুক্তি বোঝা'},
            "Hello everyone! I'm new to the legal field and would like to understand more about employment contracts. What are the key elements that should be included in a standard employment con...": {'hi': 'नमस्ते सभी! मैं कानूनी क्षेत्र में नया हूँ और रोजगार अनुबंधों के बारे में अधिक जानना चाहता हूँ। एक मानक रोजगार अनुबंध में कौन-कौन से मुख्य तत्व शामिल होने चाहिए?', 'bn': 'সবাইকে শুভেচ্ছা! আমি আইনি ক্ষেত্রে নতুন এবং চাকরির চুক্তি সম্পর্কে আরও জানতে চাই। একটি স্ট্যান্ডার্ড চাকরির চুক্তিতে কী কী মূল উপাদান থাকা উচিত?'},
            'Tips for Filing a Legal Petition': {'hi': 'कानूनी याचिका दाखिल करने के लिए सुझाव', 'bn': 'আইনি আবেদন দাখিলের টিপস'},
            "I've been working on filing a legal petition and wanted to share some tips I've learned: 1. Always double-check all personal information 2. Include all relevant dates a...": {'hi': 'मैं कानूनी याचिका दाखिल करने पर काम कर रहा हूँ और कुछ सुझाव साझा करना चाहता हूँ: 1. सभी व्यक्तिगत जानकारी दोबारा जांचें 2. सभी प्रासंगिक तिथियाँ शामिल करें...', 'bn': 'আমি আইনি আবেদন দাখিল করার কাজ করছি এবং কিছু টিপস শেয়ার করতে চাই: ১. সব ব্যক্তিগত তথ্য ভালোভাবে যাচাই করুন ২. সব প্রাসঙ্গিক তারিখ অন্তর্ভুক্ত করুন...'},
            'Legal Document Templates - Best Practices': {'hi': 'कानूनी दस्तावेज़ टेम्पलेट्स - सर्वोत्तम अभ्यास', 'bn': 'আইনি ডকুমেন্ট টেমপ্লেট - সেরা অনুশীলন'},
            "When using legal document templates, it's important to: - Review the entire document before signing - Understand each clause and its implications - Keep...": {'hi': 'कानूनी दस्तावेज़ टेम्पलेट्स का उपयोग करते समय, यह महत्वपूर्ण है: - हस्ताक्षर करने से पहले पूरे दस्तावेज़ की समीक्षा करें - प्रत्येक क्लॉज और उसके प्रभाव को समझें...', 'bn': 'আইনি ডকুমেন্ট টেমপ্লেট ব্যবহার করার সময়, গুরুত্বপূর্ণ: - স্বাক্ষর করার আগে পুরো ডকুমেন্টটি পর্যালোচনা করুন - প্রতিটি ধারা ও তার প্রভাব বুঝুন...'},
            'Common Mistakes in Legal Forms': {'hi': 'कानूनी फॉर्म में सामान्य गलतियाँ', 'bn': 'আইনি ফর্মে সাধারণ ভুল'},
            "I've noticed several common mistakes people make when filling out legal forms: 1. Missing signatures 2. Incomplete information 3. Using outdated forms ...": {'hi': 'मैंने देखा है कि लोग कानूनी फॉर्म भरते समय कई सामान्य गलतियाँ करते हैं: 1. हस्ताक्षर छूटना 2. अधूरी जानकारी 3. पुराने फॉर्म का उपयोग...', 'bn': 'আমি লক্ষ্য করেছি যে মানুষ আইনি ফর্ম পূরণ করার সময় কয়েকটি সাধারণ ভুল করে: ১. স্বাক্ষর বাদ পড়া ২. অসম্পূর্ণ তথ্য ৩. পুরনো ফর্ম ব্যবহার...'},
            'Your AI-powered legal guidance': {'hi': 'आपकी एआई-संचालित कानूनी मार्गदर्शन', 'bn': 'আপনার এআই-চালিত আইনি নির্দেশিকা'},
            'Disclaimer: This AI assistant provides general legal information, not professional advice. For complex issues, consult a qualified lawyer.': {'hi': 'अस्वीकरण: यह एआई सहायक सामान्य कानूनी जानकारी प्रदान करता है, पेशेवर सलाह नहीं। जटिल मामलों के लिए, एक योग्य वकील से परामर्श करें।', 'bn': 'দায়িত্ব অস্বীকার: এই এআই সহকারী সাধারণ আইনি তথ্য প্রদান করে, পেশাদার পরামর্শ নয়। জটিল বিষয়ে, একজন যোগ্য আইনজীবীর পরামর্শ নিন।'},
            "Hello! I'm your Legal Lok assistant.": {'hi': 'नमस्ते! मैं आपका लीगल लोक सहायक हूँ।', 'bn': 'হ্যালো! আমি আপনার লিগ্যাল লোক সহকারী।'},
            'I can help you with legal information about:': {'hi': 'मैं आपको इन कानूनी विषयों पर जानकारी दे सकता हूँ:', 'bn': 'আমি আপনাকে নিম্নলিখিত আইনি বিষয়ে তথ্য দিতে পারি:'},
            'Property and real estate laws': {'hi': 'संपत्ति और रियल एस्टेट कानून', 'bn': 'সম্পত্তি ও রিয়েল এস্টেট আইন'},
            'Family and marriage laws': {'hi': 'परिवार और विवाह कानून', 'bn': 'পরিবার ও বিবাহ আইন'},
            'Business and employment regulations': {'hi': 'व्यापार और रोजगार नियम', 'bn': 'ব্যবসা ও কর্মসংস্থান বিধি'},
            'Criminal and civil procedures': {'hi': 'आपराधिक और दीवानी प्रक्रिया', 'bn': 'ফৌজদারি ও দেওয়ানি প্রক্রিয়া'},
            'Consumer rights and more': {'hi': 'उपभोक्ता अधिकार और अधिक', 'bn': 'ভোক্তা অধিকার এবং আরও অনেক কিছু'},
            'How can I assist you today?': {'hi': 'मैं आज आपकी किस प्रकार सहायता कर सकता हूँ?', 'bn': 'আমি আজ আপনাকে কীভাবে সাহায্য করতে পারি?'},
            'How to file for divorce in India?': {'hi': 'भारत में तलाक के लिए कैसे आवेदन करें?', 'bn': 'ভারতে কীভাবে বিবাহবিচ্ছেদের জন্য আবেদন করবেন?'},
            'Documents needed for property registration': {'hi': 'संपत्ति पंजीकरण के लिए आवश्यक दस्तावेज़', 'bn': 'সম্পত্তি নিবন্ধনের জন্য প্রয়োজনীয় নথিপত্র'},
            # --- NEW STRINGS FOR MOCK TRANSLATION ---
            'Welcome to Legal Lok': {'hi': 'लीगल लोक में आपका स्वागत है', 'bn': 'লিগ্যাল লোক-এ স্বাগতম'},
            'Your one-stop solution for all legal documentation needs. Get started by exploring templates or continuing your draft forms.': {
                'hi': 'सभी कानूनी दस्तावेज़ आवश्यकताओं के लिए आपकी एकमात्र जगह। टेम्पलेट्स देखें या अपने ड्राफ्ट फॉर्म्स जारी रखें।',
                'bn': 'সব আইনি ডকুমেন্টেশনের জন্য আপনার একমাত্র সমাধান। টেমপ্লেট দেখুন বা আপনার খসড়া ফর্ম চালিয়ে যান।'
            },
            'NDA Agreement': {'hi': 'एनडीए समझौता', 'bn': 'এনডিএ চুক্তি'},
            'Partnership Agreement': {'hi': 'साझेदारी समझौता', 'bn': 'অংশীদারিত্ব চুক্তি'},
            'Healthcare': {'hi': 'स्वास्थ्य सेवा', 'bn': 'স্বাস্থ্যসেবা'},
            'Patient Intake': {'hi': 'रोगी प्रवेश', 'bn': 'রোগী ভর্তি'},
            'Medical Release': {'hi': 'चिकित्सा रिलीज', 'bn': 'মেডিকেল রিলিজ'},
            'Personal': {'hi': 'व्यक्तिगत', 'bn': 'ব্যক্তিগত'},
            'Lease Agreement': {'hi': 'पट्टा समझौता', 'bn': 'লিজ চুক্তি'},
            'Vehicle Sale': {'hi': 'वाहन बिक्री', 'bn': 'যানবাহন বিক্রয়'},
            'I\'m having trouble connecting to the legal database. Please try again later': {
                'hi': 'मैं कानूनी डेटाबेस से कनेक्ट करने में समस्या का सामना कर रहा हूँ। कृपया बाद में पुनः प्रयास करें।',
                'bn': 'আমি আইনি ডাটাবেসে সংযোগ করতে সমস্যার সম্মুখীন হচ্ছি। অনুগ্রহ করে পরে আবার চেষ্টা করুন।'
            }
            # ...existing code...
        }
        # --- END EXTENDED MOCK TRANSLATIONS ---

        if fallback_only:
            print("Fallback-only request, using mock translations...")
        else:
            api_url = 'https://meity-auth.ulcacontrib.org/ulca/apis/v0/model/compute'
            model_id = request_data.get('modelId', 'ai4bharat/indictrans-v2-all-gpu')
            task = request_data.get('task', 'translation')
            payload = {
                "modelId": model_id,
                "task": task,
                "input": [{
                    "source": source_text,
                    "sourceLanguage": source_lang,
                    "targetLanguage": target_lang
                }]
            }
            headers = {
                'ulcaApiKey': 'nEr9Swv6WxarqrQdP2Nafn04E7ZYncNPmJJEqMisDed5cDn62QcQWvQAQ6lcNe5o',
                'Content-Type': 'application/json'
            }
            try:
                response = requests.post(api_url, json=payload, headers=headers, timeout=30)
                response_data = response.json() if response.headers.get('content-type', '').startswith('application/json') else {}
                print("Response from ULCA API:", response_data)  # Debug log
                if response.status_code == 200 and response_data.get('output'):
                    output = response_data['output'][0]
                    return jsonify({
                        'target': output.get('target', source_text),
                        'status': 'success (api)',
                        'source': source_text,
                        'target_language': target_lang
                    })
            except Exception as api_error:
                print(f"API call failed: {api_error}")
                # Continue to mock fallback

        if source_text in mock_translations and target_lang in mock_translations[source_text]:
            translated_text = mock_translations[source_text][target_lang]
            return jsonify({
                'target': translated_text,
                'status': 'success (mock)',
                'source': source_text,
                'target_language': target_lang
            })
        # Pseudo-transliterate names for Hindi only if not found in mock_translations
        elif target_lang == 'hi':
            transliterated = pseudo_transliterate_to_hindi(source_text)
            if transliterated != source_text:
                return jsonify({
                    'target': transliterated,
                    'status': 'success (pseudo-hindi)',
                    'source': source_text,
                    'target_language': target_lang
                })
        else:
            return jsonify({
                'target': source_text,
                'status': 'no translation found',
                'source': source_text,
                'target_language': target_lang
            })
    except Exception as e:
        print(f"Translation error: {str(e)}")
        return jsonify({
            'error': 'Translation Error',
            'message': str(e),
            'target': source_text if 'source_text' in locals() else '',
            'status': 'error'
        })

# ----------------- GEMINI API -----------------
@app.route('/api/chat', methods=['POST'])
def chat_with_gemini():
    try:
        data = request.get_json()
        user_message = data.get('message')
        
        if not user_message:
            return jsonify({'error': 'No message provided'}), 400
            
        # Get the API key from environment variable
        gemini_api_key = os.getenv('GEMINI_API_KEY')
        if not gemini_api_key:
            return jsonify({'error': 'Gemini API key not configured'}), 500
            
        headers = {
            'Authorization': f'Bearer {gemini_api_key}',
            'Content-Type': 'application/json'
        }
        
        # Call Gemini API
        response = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent",
            headers=headers,
            json={
                "contents": [{
                    "parts": [{
                        "text": f"You are a legal assistant for Legal Lok. Please provide a helpful response to this legal question: {user_message}"
                    }]
                }]
            }
        )
        
        if response.status_code == 200:
            response_data = response.json()
            if 'candidates' in response_data and response_data['candidates']:
                bot_response = response_data['candidates'][0]['content']['parts'][0]['text']
                return jsonify({'response': bot_response})
            else:
                return jsonify({'error': 'Invalid response from Gemini API'}), 500
        else:
            return jsonify({'error': f'Gemini API error: {response.status_code}'}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ----------------- RUN -----------------

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
